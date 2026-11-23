"""Open a local-write run for a clear work request the runtime has not entered yet.

Owner: the pretool gate's automatic workflow entry.
Allowed imports: the standard library, ``support.global_state`` and, lazily,
``workflow`` for the intake classifier. The gate imports this module; this
module never imports the gate.
Callers/tests: ``claude_pretool_gate.main`` and ``workflow._print_advisory_once``;
coverage lives in ``tests/test_claude_pretool_auto_start.py``.
Verification: run that module.

A work request in Claude or Codex was refused at the first write until the
agent re-typed it into an eight-argument ``start``. In one week that denial
(``workflow_entry_missing``) was the most frequent gate block, and every
recovery was the same command. The user chose to let the gate make that start:

* the prompt hook records the session's latest user prompt (local state, one
  file per session, overwritten every turn);
* when a write is refused only because no writable run exists, the gate starts
  ``small-change`` with that prompt, a generic intent and the ``local_write``
  effect, then judges the same call again.

What this does not widen: a direct question never opens a run; the started run
is ``local_write``, so commits, pushes, releases and destructive steps keep
their own approvals; worktree isolation, paused/failed runs and publication
holds are judged exactly as before because the call is re-judged after the
start, not waved through. A failed start is remembered per session and request
so it is not retried on every call.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from support.global_state import global_state_dir, user_store_write_error

AUTO_ROUTE = "small-change"
AUTO_INTENT = "auto_work"
AUTO_EFFECT = "local_write"
# Denial codes whose only remedy is a writable start. Everything else -- worktree
# isolation, paused or failed runs, publication -- keeps its own verdict.
AUTO_START_CODES = frozenset({"workflow_entry_missing", "read_only_run_mutation"})
MAX_REQUEST_AGE_SECONDS = 6 * 60 * 60
# The PreToolUse hook is given 10 seconds; leave room to re-judge the call.
START_TIMEOUT_SECONDS = 7.0
MAX_PROMPT_CHARS = 8000
SESSION_ENV = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID"}
DISABLE_ENV = "MORU_AUTO_WORK_START"


def enabled() -> bool:
    return os.environ.get(DISABLE_ENV, "1").strip().lower() not in {"0", "false", "off", "no"}


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _request_path(session_id: str) -> Path:
    return global_state_dir() / "session-requests" / f"{_key(session_id)}.json"


def record_request(payload_text: str) -> None:
    """Keep the latest prompt of this runtime session. Never raises."""

    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    session_id, prompt = payload.get("session_id"), payload.get("prompt")
    if not isinstance(session_id, str) or not session_id or not isinstance(prompt, str):
        return
    prompt = prompt.strip()
    if not prompt or len(prompt) > MAX_PROMPT_CHARS or user_store_write_error():
        return
    path = _request_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"prompt": prompt, "recorded_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError:
        return


def current_request(session_id: str, now: float | None = None) -> str:
    """The session's latest prompt while it is recent, else ""."""

    if not session_id:
        return ""
    try:
        record = json.loads(_request_path(session_id).read_text(encoding="utf-8"))
        prompt, at = str(record["prompt"]), float(record["recorded_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if (now if now is not None else time.time()) - at > MAX_REQUEST_AGE_SECONDS:
        return ""
    return prompt


def is_work_request(prompt: str) -> bool:
    """Whether the prompt asks for work rather than an answer."""

    try:
        from workflow import classify_request

        mode = classify_request(prompt, continuation_scope="", conversation_first=True).get("response_mode")
    except Exception:  # noqa: BLE001 - an unreadable intake opens nothing
        return False
    return mode not in {None, "answer_first"}


def _failure_path(session_id: str, prompt: str) -> Path:
    return global_state_dir() / "session-requests" / f"{_key(session_id)}.{_key(prompt)}.failed"


def _target_summary(tool: str, target: str) -> str:
    label = f"auto work start: {tool} {target}".strip()
    return label if len(label) <= 160 else label[:159] + "…"


def start_run(
    root: Path, session_id: str, runtime: str, tool: str, target: str,
    *, runner=subprocess.run, now: float | None = None,
) -> str:
    """Start the writable run and return its id, or "" when nothing started."""

    prompt = current_request(session_id, now)
    if not prompt or not is_work_request(prompt):
        return ""
    failed = _failure_path(session_id, prompt)
    if failed.exists():
        return ""
    scripts = Path(__file__).resolve().parent
    env = {**os.environ, "MORU_HOOK_SOFT_FAIL": "0"}
    variable = SESSION_ENV.get(runtime)
    if variable:
        env[variable] = session_id
    command = [
        sys.executable, str(scripts / "agent-hook.py"), "start",
        "--project", str(root), "--rules", str(scripts.parent),
        "--command", AUTO_ROUTE, "--request", prompt,
        "--intent", AUTO_INTENT, "--target-summary", _target_summary(tool, target),
        "--requested-effect", AUTO_EFFECT,
    ]
    try:
        result = runner(command, capture_output=True, text=True, timeout=START_TIMEOUT_SECONDS,
                        env=env, cwd=str(root), stdin=subprocess.DEVNULL)
        output = f"{result.stdout}\n{result.stderr}"
        ok = result.returncode == 0 and "SUCCESS start" in output
    except (OSError, subprocess.SubprocessError):
        ok, output = False, ""
    if not ok:
        if not user_store_write_error():
            try:
                failed.parent.mkdir(parents=True, exist_ok=True)
                failed.write_text("", encoding="utf-8")
            except OSError:
                pass
        return ""
    for line in output.splitlines():
        if line.strip().startswith("- run id:"):
            return line.split(":", 1)[1].strip()
    return "started"
