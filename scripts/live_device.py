"""Tell an agent whether Android or iOS Live is running and whether its save reached the app.

Owner: reading ``<project>/.moru/live-device/events.jsonl``; the Moru app is the
only writer and appends every event a Devices Live plugin reports.
Allowed imports: the standard library and the sibling ``live_web_checks``
(file matching, time parsing, project-relative paths).
Forbidden imports: the workflow route, the agent lifecycle and hook installers.
Callers/tests: agents following the ``live-device`` card; coverage lives in
``tests/test_live_device.py``.
Verification: run that module, then ``live_device.py status`` and ``check``
against a scratch project with a hand-written log.

A log line is ``{"time", "platform", "device", "event": {"event", "files",
"ms", "reason", "detail", ...}}`` with moru-live-events/1 inside. ``status``
exits 0 while any device runs Live and 5 when none does. ``check`` reports, per
device, the newest result for the given files: exit 0 when every device applied
it (or rebuilt and relaunched with it), 4 when one failed or waits for a
rebuild, 5 when a device has no result yet. Only the tail of a large log is read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from live_web_checks import _relative, _same_file, _since_epoch, _strings

PROBLEM_EXIT = 4
MISSING_EXIT = 5
TAIL_BYTES = 128 * 1024
RESULTS = {"applied", "unchanged", "failed", "needs_rebuild"}


def events_log(project: Path) -> Path:
    return project / ".moru" / "live-device" / "events.jsonl"


def read_events(project: Path, tail_bytes: int = TAIL_BYTES) -> list[dict]:
    """The well-formed entries in the last ``tail_bytes`` of the log, oldest first."""
    try:
        with events_log(project).open("rb") as handle:
            start = max(handle.seek(0, os.SEEK_END) - tail_bytes, 0)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    if start > 0:
        data = data.split(b"\n", 1)[1] if b"\n" in data else b""
    entries = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("event"), dict):
            entries.append(entry)
    return entries


def _kind(entry: dict) -> str:
    return str(entry["event"].get("event", ""))


def by_device(entries: list[dict]) -> dict[str, list[dict]]:
    devices: dict[str, list[dict]] = {}
    for entry in entries:
        devices.setdefault(f"{entry.get('platform', '?')} {entry.get('device', '?')}", []).append(entry)
    return devices


def live_devices(entries: list[dict]) -> dict[str, list[dict]]:
    """Devices whose last event is not ``stopped``, with their events."""
    return {name: items for name, items in by_device(entries).items() if _kind(items[-1]) != "stopped"}


def result_for(items: list[dict], files: list[str], since: Optional[float]) -> tuple[str, Optional[dict]]:
    """(``ok``, ``problem`` or ``pending``, the deciding entry) for one device's events."""
    for index in range(len(items) - 1, -1, -1):
        entry = items[index]
        moment = _since_epoch(entry.get("time", ""))
        if since is not None and (moment is None or moment < since):
            break
        kind = _kind(entry)
        touched = _strings(entry["event"].get("files"))
        if files and not any(_same_file(have, want) for have in touched for want in files):
            continue
        if kind == "applying":
            return "pending", entry
        if kind not in RESULTS:
            continue
        if kind == "needs_rebuild" and any(_kind(later) == "ready" for later in items[index + 1:]):
            return "ok", entry
        return ("ok" if kind in {"applied", "unchanged"} else "problem"), entry
    return "pending", None


def describe(name: str, entry: Optional[dict], items: list[dict]) -> str:
    if entry is None:
        return f"{name}: no result yet"
    event = entry["event"]
    kind = _kind(entry)
    files = ", ".join(_strings(event.get("files"))) or "(no files)"
    text = f"{name}: {kind} {entry.get('time', '?')} {files}"
    if isinstance(event.get("ms"), int):
        text += f" in {event['ms'] / 1000:.1f}s"
    if kind == "needs_rebuild":
        relaunched = any(_kind(later) == "ready" for later in items[items.index(entry) + 1:])
        text += "; rebuilt and relaunched" if relaunched else "; waits for Rebuild in Moru"
    for key in ("reason", "detail"):
        if event.get(key):
            text += f"; {key}: {str(event[key]).splitlines()[0]}"
    return text


def status(project: Path, args: argparse.Namespace) -> int:
    live = live_devices(read_events(project))
    if args.json:
        print(json.dumps({name: items[-1] for name, items in live.items()}))
    elif not live:
        print("Live is off")
    for name, items in live.items():
        if not args.json:
            ready = next((item for item in reversed(items) if _kind(item) == "ready"), None)
            app = ready["event"].get("package", "?") if ready else "?"
            print(f"{name}: Live on for {app}, last {_kind(items[-1])} {items[-1].get('time', '?')}")
    return 0 if live else MISSING_EXIT


def check(project: Path, args: argparse.Namespace) -> int:
    live = live_devices(read_events(project))
    if not live:
        print(json.dumps({"status": "off", "devices": {}}) if args.json else "Live is off")
        return MISSING_EXIT
    files = [_relative(project, raw) for raw in args.files]
    since = _since_epoch(args.since) if args.since else None
    results = {name: result_for(items, files, since) for name, items in live.items()}
    states = {state for state, _ in results.values()}
    code = PROBLEM_EXIT if "problem" in states else MISSING_EXIT if "pending" in states else 0
    if args.json:
        print(json.dumps({"status": {0: "ok", PROBLEM_EXIT: "problems", MISSING_EXIT: "pending"}[code],
                          "devices": {name: {"state": state, "entry": entry} for name, (state, entry) in results.items()}}))
    else:
        for name, (_, entry) in results.items():
            print(describe(name, entry, live[name]))
    return code


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Android/iOS Live state and save results for agents.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "check"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
        command.add_argument("--json", action="store_true")
        if name == "check":
            command.add_argument("--files", nargs="+", default=[])
            command.add_argument("--since", default=None)
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    return status(project, args) if args.command == "status" else check(project, args)


if __name__ == "__main__":
    sys.exit(main())
