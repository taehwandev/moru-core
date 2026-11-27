"""Let a project lead start, watch and stop headless sub runs through Moru Control.

Owner: lead-side request writer for headless sub runs and the lead inbox.
Allowed imports: standard library only.
Forbidden imports: lifecycle gates, ledgers, provider runtimes; this never
spawns an agent itself. Moru Control owns the process (it also recovers
orphans), so a sub run survives the lead session closing.
Callers/tests: a lead agent per
workflows/skills/multi-agent-collaboration/references/on-demand-orchestration.md;
tests/test_agent_sub_run.py.
Verification: tests/test_agent_sub_run.py.

Files (contract shared with Moru Control and the Moru app), under
<project>/.moru/hq/: sub-requests/<reqId>.json (written here) ->
<reqId>.processed.json {runId} or <reqId>.failed.json {error};
runs/<runId>/status.json and control.json; lead.json; lead-inbox/<id>.json
with <id>.done.json markers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIMES = ("claude", "codex", "agy")
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._:-]{0,127}$")
MAX_JSON_BYTES = 256 * 1024
MAX_PROMPT_CHARS = 20000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hq(project: Path) -> Path:
    return project / ".moru" / "hq"


def _safe_dir(path: Path) -> Path:
    """Create a 0700 directory chain under .moru/hq, refusing symlinks."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.resolve() != path.absolute().resolve():
        raise ValueError(f"refusing symlinked directory: {path}")
    return path


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    _safe_dir(path.parent)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _read(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def resolve_project(explicit: Path | None) -> Path:
    if explicit is not None:
        project = explicit.resolve()
    else:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if top.returncode != 0:
            raise ValueError("not inside a Git checkout; pass --project")
        project = Path(top.stdout.strip()).resolve()
    if not project.is_dir():
        raise ValueError("--project must be an existing directory")
    return project


def _id_or_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if value and _ID_RE.fullmatch(value) else None


def request_sub_run(project: Path, runtime: str, prompt: str, *, environ: dict[str, str] | None = None,
                    wait_seconds: float = 10.0, poll: float = 0.2) -> dict[str, Any]:
    """Write one sub request and wait briefly for Moru Control to accept it."""
    environ = dict(os.environ) if environ is None else environ
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of {', '.join(RUNTIMES)}")
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("brief must be non-empty and at most 20000 characters")
    lead = _read(_hq(project) / "lead.json") or {}
    req_id = f"subreq-{uuid.uuid4()}"
    request = {
        "schema": 1, "reqId": req_id, "runtime": runtime, "prompt": prompt,
        "parentSessionId": _id_or_none(environ.get("MORU_SESSION_ID")) or _id_or_none(lead.get("sessionId")),
        "parentRunId": _id_or_none(environ.get("MORU_RUN_ID")),
        "moruTaskId": _id_or_none(lead.get("taskId")),
        "requestedAt": _now(),
    }
    folder = _safe_dir(_hq(project) / "sub-requests")
    _write_atomic(folder / f"{req_id}.json", request)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        done = _read(folder / f"{req_id}.processed.json")
        if done and _id_or_none(done.get("runId")):
            return {"reqId": req_id, "runId": done["runId"], "state": "accepted"}
        failed = _read(folder / f"{req_id}.failed.json")
        if failed:
            raise RuntimeError(f"Moru Control refused the sub run: {str(failed.get('error') or 'unknown')[:300]}")
        time.sleep(poll)
    return {"reqId": req_id, "runId": None, "state": "pending",
            "note": "Moru Control has not picked it up yet; check `status --req-id` later or confirm the HQ dispatcher is running."}


def run_status(project: Path, run_id: str) -> dict[str, Any]:
    if not _id_or_none(run_id):
        raise ValueError("invalid run id")
    status = _read(_hq(project) / "runs" / run_id / "status.json")
    if status is None:
        raise ValueError("no such run in this project")
    return {key: status.get(key) for key in ("runId", "runtime", "state", "lastStep", "summary", "sessionId",
                                             "origin", "parentSessionId", "permissionBypass")}


def request_status(project: Path, req_id: str) -> dict[str, Any]:
    if not _id_or_none(req_id):
        raise ValueError("invalid request id")
    folder = _hq(project) / "sub-requests"
    done = _read(folder / f"{req_id}.processed.json")
    if done:
        return run_status(project, str(done.get("runId")))
    failed = _read(folder / f"{req_id}.failed.json")
    if failed:
        return {"reqId": req_id, "state": "refused", "error": str(failed.get("error") or "")[:300]}
    return {"reqId": req_id, "state": "pending"}


def stop_run(project: Path, run_id: str) -> dict[str, Any]:
    run_status(project, run_id)  # validates the id and that the run exists here
    _write_atomic(_hq(project) / "runs" / run_id / "control.json",
                  {"schema": 1, "action": "stop", "requestedAt": _now()})
    return {"runId": run_id, "stopRequested": True}


def open_inbox(project: Path) -> list[dict[str, Any]]:
    folder = _hq(project) / "lead-inbox"
    if not folder.is_dir() or folder.is_symlink():
        return []
    items = []
    for path in sorted(folder.glob("*.json")):
        if path.name.endswith(".done.json") or (folder / f"{path.stem}.done.json").exists():
            continue
        item = _read(path)
        if item and _id_or_none(item.get("id")) == path.stem:
            items.append({key: item.get(key) for key in ("id", "title", "request", "createdAt")})
    return items


def mark_inbox_done(project: Path, item_id: str) -> dict[str, Any]:
    if not _id_or_none(item_id) or not (_hq(project) / "lead-inbox" / f"{item_id}.json").is_file():
        raise ValueError("no such lead inbox item")
    _write_atomic(_hq(project) / "lead-inbox" / f"{item_id}.done.json",
                  {"schema": 1, "id": item_id, "doneAt": _now(), "by": "lead"})
    return {"id": item_id, "done": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless sub runs and inbox for a Moru project lead.")
    parser.add_argument("--project", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start", help="start one headless sub run through Moru Control")
    start.add_argument("--runtime", required=True, choices=RUNTIMES)
    start.add_argument("--brief-file", required=True, help="brief file, or - for stdin")
    start.add_argument("--wait", type=float, default=10.0)
    status = sub.add_parser("status", help="state of a sub run or request")
    group = status.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--req-id")
    stop = sub.add_parser("stop", help="stop one sub run")
    stop.add_argument("--run-id", required=True)
    sub.add_parser("inbox", help="open requests the secretary handed to this lead")
    done = sub.add_parser("inbox-done", help="mark a lead inbox request handled")
    done.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        project = resolve_project(args.project)
        if args.action == "start":
            brief = sys.stdin.read() if args.brief_file == "-" else Path(args.brief_file).read_text(encoding="utf-8")
            result: Any = request_sub_run(project, args.runtime, brief, wait_seconds=max(0.0, args.wait))
        elif args.action == "status":
            result = run_status(project, args.run_id) if args.run_id else request_status(project, args.req_id)
        elif args.action == "stop":
            result = stop_run(project, args.run_id)
        elif args.action == "inbox":
            result = open_inbox(project)
        else:
            result = mark_inbox_done(project, args.id)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"sub run {args.action} failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
