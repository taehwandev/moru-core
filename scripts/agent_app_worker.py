"""Start and stop delegated workers as visible sessions inside the Moru app.

Owner: lead-side launcher for app-hosted worker sessions through `moru-ade`.
Allowed imports: standard library only.
Forbidden imports: lifecycle gates, ledgers, provider runtimes; this never
records gates or grants authority, it only opens and stops app sessions.
Callers/tests: the lead agent per
workflows/skills/multi-agent-collaboration/references/on-demand-orchestration.md;
tests/test_agent_app_worker.py.
Verification: tests/test_agent_app_worker.py with a stub moru-ade.

A background subagent cannot be watched or interrupted by the lead in every
runtime. A worker started here runs in its own Moru app session the operator
can see, and `stop` ends only that session, so the lead can halt writers when
a shared contract changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

APP_HELPER = Path("/Applications/Moru.app/Contents/Helpers/moru-ade")
RUNTIMES = ("claude", "codex", "agy", "terminal")
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._:-]{0,199}$")
TIMEOUT_SECONDS = 30


def resolve_binary(environ: dict[str, str] | None = None) -> Path | None:
    """The app's moru-ade: MORU_ADE_BIN set by the app, else the standard install."""
    environ = os.environ if environ is None else environ
    override = environ.get("MORU_ADE_BIN", "")
    for candidate in ([Path(override)] if override else []) + [APP_HELPER]:
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _call(binary: Path, args: list[str], stdin: str | None = None) -> dict[str, Any]:
    result = subprocess.run([str(binary), *args], input=stdin, capture_output=True, text=True,
                            timeout=TIMEOUT_SECONDS, check=False)
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())[:300]
        raise RuntimeError(f"moru-ade {' '.join(args[:2])} failed (exit {result.returncode}): {detail}")
    text = (result.stdout or "").strip()
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        parsed = {"raw": text}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _pick(parsed: dict[str, Any], *keys: str) -> str:
    resolved = parsed.get("resolved") if isinstance(parsed.get("resolved"), dict) else {}
    for key in keys:
        value = resolved.get(key) or parsed.get(key)
        if isinstance(value, str) and _ID_RE.fullmatch(value.strip()):
            return value.strip()
    return ""


def start_worker(binary: Path, project: Path, runtime: str, prompt: str) -> dict[str, str]:
    """Open the project, create a task and start one visible session with the brief."""
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of {', '.join(RUNTIMES)}")
    if not prompt.strip():
        raise ValueError("worker brief is empty")
    project_id = _pick(_call(binary, ["open", str(project)]), "projectId")
    if not project_id:
        raise RuntimeError("moru-ade open returned no project id")
    task_id = _pick(_call(binary, ["task", "create", "--project", project_id]), "taskId")
    if not task_id:
        raise RuntimeError("moru-ade task create returned no task id")
    run = _call(binary, ["task", "run", "--project", project_id, "--task", task_id,
                         "--runtime", runtime, "--prompt-file", "-", "--submit"], stdin=prompt)
    run_id = _pick(run, "runId", "moruRunId", "run_id", "id")
    if not run_id:
        raise RuntimeError("moru-ade task run returned no run id")
    return {"projectId": project_id, "taskId": task_id, "runId": run_id, "runtime": runtime}


def stop_worker(binary: Path, project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
    """Stop only the session that run started."""
    for value in (project_id, task_id, run_id):
        if not _ID_RE.fullmatch(value):
            raise ValueError("project, task and run ids must be the ids start printed")
    _call(binary, ["task", "stop-run", "--project", project_id, "--task", task_id, "--run", run_id])
    return {"stopped": run_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visible Moru app worker sessions for a lead agent.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("available", help="exit 0 when the Moru app launcher is usable")
    start = sub.add_parser("start", help="start one worker session in the Moru app")
    start.add_argument("--project", required=True, type=Path)
    start.add_argument("--runtime", default="claude", choices=RUNTIMES)
    start.add_argument("--brief-file", required=True, help="worker brief file, or - for stdin")
    stop = sub.add_parser("stop", help="stop one worker session started by start")
    for name in ("--project-id", "--task-id", "--run-id"):
        stop.add_argument(name, required=True)
    args = parser.parse_args(argv)
    binary = resolve_binary()
    if binary is None:
        print("Moru app launcher unavailable; use the runtime's own worker instead.", file=sys.stderr)
        return 3
    try:
        if args.action == "available":
            result: dict[str, Any] = {"available": True}
        elif args.action == "start":
            project = args.project.resolve()
            if not project.is_dir():
                raise ValueError("--project must be an existing directory")
            brief = sys.stdin.read() if args.brief_file == "-" else Path(args.brief_file).read_text(encoding="utf-8")
            result = start_worker(binary, project, args.runtime, brief)
        else:
            result = stop_worker(binary, args.project_id, args.task_id, args.run_id)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"app worker {args.action} failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
