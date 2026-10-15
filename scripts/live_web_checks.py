"""Read what the Moru app saw after each save of a live web page.

Owner: reading ``<project>/.moru/live-web/checks.jsonl``; the Moru app is the
only writer and appends one line per save.
Allowed imports: the standard library only.
Forbidden imports: the workflow route, the agent lifecycle and hook installers.
Callers/tests: ``path_claims.py check`` (``add_arguments`` and ``run``); coverage lives in
``tests/test_path_claims.py``.
Verification: run that module, then ``path_claims.py check`` against a scratch
project with a hand-written log.

A check line is ``{"time", "files", "views": [{"viewport", "elements",
"boxes": [[x, y, w, h], ...]}], "errors", "reloadFailed"}`` with
repository-relative files. ``check`` exits 0 for a clean check, 4 when it
reports errors or a failed reload and 5 when no matching check exists yet;
JSON output is ``{"status", "check"}`` with status ``ok``, ``problems`` or
``none``. Malformed lines are skipped and only the tail of a large log is read.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CHECK_PROBLEM_EXIT = 4
CHECK_MISSING_EXIT = 5
CHECK_TAIL_BYTES = 64 * 1024


def checks_log(project: Path) -> Path:
    return project / ".moru" / "live-web" / "checks.jsonl"


def read_checks(project: Path, tail_bytes: int = CHECK_TAIL_BYTES) -> list[dict]:
    """Return the well-formed checks in the last ``tail_bytes`` of the log, oldest first."""
    log = checks_log(project)
    try:
        with log.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(size - tail_bytes, 0)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    if start > 0:
        # The first line is probably cut in the middle; drop it.
        data = data.split(b"\n", 1)[1] if b"\n" in data else b""
    checks = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            checks.append(entry)
    return checks


def _strings(value) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _same_file(first: str, second: str) -> bool:
    first, second = first.strip("/"), second.strip("/")
    if not first or not second:
        return False
    return first == second or first.endswith("/" + second) or second.endswith("/" + first)


def _since_epoch(text: str) -> Optional[float]:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def latest_check(project: Path, files: Optional[list[str]] = None, since: Optional[str] = None) -> Optional[dict]:
    """The newest check touching any of ``files`` (any check when empty), at or after ``since``."""
    wanted = list(files or [])
    floor = _since_epoch(since) if since else None
    for check in reversed(read_checks(project)):
        if floor is not None:
            moment = _since_epoch(check.get("time", ""))
            if moment is None or moment < floor:
                continue
        if wanted and not any(_same_file(have, want) for have in _strings(check.get("files")) for want in wanted):
            continue
        return check
    return None


def check_problems(check: dict) -> bool:
    return bool(_strings(check.get("errors"))) or check.get("reloadFailed") is True


def _describe_view(view) -> str:
    if not isinstance(view, dict):
        return "?"
    count = view.get("elements")
    count = count if isinstance(count, int) else 0
    text = f"{view.get('viewport') or '?'} {count} element{'' if count == 1 else 's'}"
    boxes = view.get("boxes")
    first = boxes[0] if isinstance(boxes, list) and boxes else None
    if isinstance(first, list) and len(first) == 4 and all(isinstance(n, (int, float)) for n in first):
        text += f" ({round(first[2])}x{round(first[3])})"
    return text


def describe_check(check: dict) -> str:
    files = ", ".join(_strings(check.get("files"))) or "(no files)"
    views = check.get("views")
    shown = ", ".join(_describe_view(view) for view in views) if isinstance(views, list) and views else "no views"
    errors = _strings(check.get("errors"))
    error_text = f"errors {len(errors)}" + (f": {errors[0]}" if errors else "")
    reload_text = "reload FAILED" if check.get("reloadFailed") is True else "reload ok"
    return f"check {check.get('time', '?')} {files}: {shown}; {error_text}; {reload_text}"


def _relative(project: Path, raw: str) -> str:
    """A project-relative key for ``raw``; anything else is kept for suffix matching."""
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(project).as_posix()
        except ValueError:
            return raw
    return os.path.normpath(raw).replace(os.sep, "/")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--files", nargs="+", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--since", default=None)


def run(project: Path, args: argparse.Namespace) -> int:
    """Print the latest matching check and return the ``check`` exit code."""
    check = latest_check(project, [_relative(project, raw) for raw in args.files], args.since)
    if check is None:
        status, code = "none", CHECK_MISSING_EXIT
    elif check_problems(check):
        status, code = "problems", CHECK_PROBLEM_EXIT
    else:
        status, code = "ok", 0
    if args.json:
        print(json.dumps({"status": status, "check": check}))
    elif check is None:
        scope = " for " + ", ".join(args.files) if args.files else ""
        print(f"no check yet{scope}")
    else:
        print(describe_check(check))
    return code
