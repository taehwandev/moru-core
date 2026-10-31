#!/usr/bin/env python3
"""Adapt Antigravity lifecycle hooks to Moru's shared gates.

Antigravity runs a hook command with a camelCase JSON payload on stdin and reads
a JSON verdict from stdout. Moru's gates speak Claude Code's payload, so this
module only translates; every policy decision stays in the gate it calls.

Events:
- ``pre-invocation``: deliver the advisory workflow route and the request's task
  guidance once per user input, as a system message.
- ``pre-tool``: run the shared pre-mutation gate for run_command/write_file/
  edit_file. A deny or ask becomes advisory context unless MORU_AGY_GATE=strict.
- ``stop``: run the shared Stop gate; its block becomes ``continue`` once.

Every failure allows: a gate that traps a session is worse than one that misses.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = "antigravity"
EDIT_TOOLS = {"write_file": "Write", "edit_file": "Edit"}
UNCHANGED_NOTE = "unchanged since this session already received it"
TIMEOUT_SECONDS = 25


def workspace(payload: dict) -> str:
    paths = payload.get("workspacePaths")
    if isinstance(paths, list) and paths:
        return str(paths[0])
    return os.getcwd()


def session_id(payload: dict) -> str:
    return str(payload.get("conversationId") or "")


def run_script(name: str, args: list[str], stdin: dict | str, cwd: str, env: dict | None = None) -> str:
    text = stdin if isinstance(stdin, str) else json.dumps(stdin)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        input=text, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        cwd=cwd if Path(cwd).is_dir() else None, env={**os.environ, **(env or {})}, check=False,
    )
    return result.stdout


def parse_json(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


MARKER_DIR = Path.home() / ".moru" / "agy-hook"
MARKER_MAX_AGE_SECONDS = 7 * 24 * 3600


def already_delivered(conversation: str, text: str, kind: str = "route") -> bool:
    """Whether this conversation already holds exactly this text; record it if not.

    The shared route cache only exists once a project has run a hook, so a new
    workspace would otherwise be re-sent the same text on every model call.
    """

    safe = "".join(ch for ch in conversation if ch.isalnum() or ch in "-_")
    if not safe:
        return False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    marker = MARKER_DIR / f"{safe}.{kind}.digest"
    try:
        if marker.read_text(encoding="utf-8") == digest:
            return True
    except OSError:
        pass
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(digest, encoding="utf-8")
        cutoff = time.time() - MARKER_MAX_AGE_SECONDS
        for old in MARKER_DIR.glob("*.digest"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
    except OSError:
        pass
    return False


def pre_invocation(payload: dict) -> dict:
    cwd = workspace(payload)
    prompt = str(payload.get("lastUserInput") or "")
    claude = {"session_id": session_id(payload), "cwd": cwd, "prompt": prompt,
              "hook_event_name": "UserPromptSubmit"}
    route = run_script("workflow.py", ["route", "triage", "--advisory", "--hook-stdin"], claude, cwd,
                       {"SPILL_AI_TOOL": RUNTIME}).strip()
    if not route or UNCHANGED_NOTE in route:
        return {}
    entry = run_script("agent-entry.py", ["--runtime", RUNTIME, "--cwd", cwd, "--no-default-search-roots",
                                          "--request", prompt], "", cwd).strip()
    text = route if not entry else f"{route}\n\n## Project entry\n{entry}"
    if already_delivered(session_id(payload), text):
        return {}
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}


def pre_tool(payload: dict) -> dict:
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    name = str(call.get("name") or "")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    if name == "run_command":
        tool, tool_input = "Bash", {"command": str(args.get("CommandLine") or "")}
    elif name in EDIT_TOOLS:
        path = args.get("Path") or args.get("TargetFile") or ""
        tool, tool_input = EDIT_TOOLS[name], {"file_path": str(path)}
    else:
        return {"decision": "allow"}
    cwd = workspace(payload)
    claude = {"session_id": session_id(payload), "cwd": cwd, "tool_name": tool, "tool_input": tool_input,
              "hook_event_name": "PreToolUse"}
    out = parse_json(run_script("claude_pretool_gate.py", [], claude, cwd, {"MORU_PRETOOL_RUNTIME": RUNTIME}))
    specific = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
    decision = specific.get("permissionDecision")
    reason = str(specific.get("permissionDecisionReason") or specific.get("additionalContext") or "")
    if decision in {"deny", "ask"}:
        if os.environ.get("MORU_AGY_GATE", "").strip().lower() == "strict":
            return {"decision": "deny", "reason": reason or "Blocked by the Moru workflow gate."}
        return {"decision": "allow", "reason": f"Moru workflow note (not enforced): {reason}".strip()}
    verdict = {"decision": "allow"}
    if reason:
        verdict["reason"] = reason
    return verdict


THREE_D_SKILL = "web-3d-interaction"
UNVERIFIED_REMINDER = (
    "Before you finish: say in your final report which user-visible properties (motion direction, "
    "framing of every camera mode, lighting, controls) you observed in a running page, and mark "
    "every one you did not observe as unverified. A build or unit tests do not cover them."
)


def routed_through_3d(payload: dict) -> bool:
    """Whether this conversation's Moru run was routed through the web 3D skill.

    Reads only the run's recorded route documents, never the transcript or the
    model's messages.
    """

    try:
        sys.path.insert(0, str(SCRIPTS))
        from agent_run_registry import RUN_STATES
        from agent_runtime_session import resolve_runtime_evidence

        evidence = resolve_runtime_evidence(
            Path(workspace(payload)), {"runtime": RUNTIME, "session_id": session_id(payload)},
            frozenset(RUN_STATES), latest_of_several=True,
        )
        if evidence is None:
            return False
        docs = json.loads(Path(evidence).read_text(encoding="utf-8")).get("route", {}).get("required_docs", [])
        return any(THREE_D_SKILL in str(doc) for doc in docs)
    except Exception:  # noqa: BLE001 - a reminder is advisory and must never trap a stop
        return False


def unverified_reminder(payload: dict, execution: int) -> dict:
    """Once per conversation, ask for an honest verification statement at stop."""

    if execution >= 1 or not routed_through_3d(payload):
        return {}
    if already_delivered(session_id(payload), UNVERIFIED_REMINDER, "stop"):
        return {}
    return {"decision": "continue", "reason": UNVERIFIED_REMINDER}


def stop(payload: dict) -> dict:
    cwd = workspace(payload)
    try:
        execution = int(payload.get("executionNum") or 0)
    except (TypeError, ValueError):
        execution = 0
    claude = {"session_id": session_id(payload), "cwd": cwd, "hook_event_name": "Stop",
              "stop_hook_active": execution >= 1}
    out = parse_json(run_script("claude_stop_gate.py", [], claude, cwd))
    if out.get("decision") == "block":
        return {"decision": "continue", "reason": str(out.get("reason") or "")}
    return unverified_reminder(payload, execution)


HANDLERS = {"pre-invocation": pre_invocation, "pre-tool": pre_tool, "stop": stop}
FAIL_OPEN = {"pre-invocation": {}, "pre-tool": {"decision": "allow"}, "stop": {}}


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    if event not in HANDLERS:
        return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        verdict = HANDLERS[event](payload if isinstance(payload, dict) else {})
    except Exception:  # noqa: BLE001 - a failing adapter must never trap the session
        verdict = FAIL_OPEN[event]
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
