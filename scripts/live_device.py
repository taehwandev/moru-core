"""Tell an agent whether Android or iOS Live is running and whether its save reached the app.

Owner: reading ``<project>/.moru/live-device/events.jsonl``; the Moru app is the
only writer and appends every event a Devices Live plugin reports.
Allowed imports: the standard library, the sibling ``live_web_checks``
(file matching, time parsing, project-relative paths) and ``live_device_arm``
(armed Live, start/open/stop requests).
Forbidden imports: the workflow route, the agent lifecycle and hook installers.
Callers/tests: agents following the ``live-device`` card; coverage lives in
``tests/test_live_device.py``.
Verification: run that module, then ``live_device.py status`` and ``check``
against a scratch project with a hand-written log.

A log line is ``{"time", "platform", "device", "event": {"event", "files",
"ms", "reason", "detail", ...}}`` with moru-live-events/1 inside. ``status``
exits 0 while devices run Live, 4 for preparation in progress or failure, and 5
when none does; when Moru offers Live (see ``live_device_arm``) it exits 3 while
a device does not run from this worktree (``start`` brings it here). ``start`` asks Moru to build and run from this worktree, ``open``
shows a deep link in the running app and ``stop`` hands the device back.
``check`` reports, per
device, the newest result for the given files: exit 0 when every device applied
it (or rebuilt and relaunched with it), 4 when one failed or its automatic
rebuild failed, 5 when a device has no result yet or is still rebuilding. Only the tail of a large log is read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import live_device_arm
from live_web_checks import _relative, _same_file, _since_epoch, _strings

ARMED_EXIT = 3
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


def _preparation_result(items: list[dict]) -> Optional[dict]:
    """A new preparation owns the session until ready, even after an old ready."""
    for entry in reversed(items):
        kind = _kind(entry)
        if kind == "ready":
            return None
        if kind == "preparing" or (kind == "failed" and entry["event"].get("reason") == "prepare"):
            return entry
    return None


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
        if kind == "needs_rebuild":
            # The plugin rebuilds and relaunches by itself: done when it is ready again, a problem when that build fails.
            outcome = _rebuild_outcome(items[index + 1:])
            return {"ready": "ok", "failed": "problem"}.get(outcome, "pending"), entry
        return ("ok" if kind in {"applied", "unchanged"} else "problem"), entry
    return "pending", None


def _rebuild_outcome(later: list[dict]) -> Optional[str]:
    """How the plugin's own rebuild after a ``needs_rebuild`` ended: ``ready``, ``failed`` (preparation), or None."""
    for entry in later:
        kind = _kind(entry)
        if kind == "ready" or (kind == "failed" and entry["event"].get("reason") == "prepare"):
            return kind
    return None


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
        outcome = _rebuild_outcome(items[items.index(entry) + 1:])
        text += {"ready": "; rebuilt and relaunched", "failed": "; the automatic rebuild failed (see status)"}.get(
            outcome, "; rebuilding and relaunching by itself")
    for key in ("reason", "detail"):
        if event.get(key):
            text += f"; {key}: {str(event[key]).splitlines()[0]}"
    return text


def ready_line(project: Path, name: str, since: float) -> Optional[str]:
    """How ``name``'s newest start ended at or after ``since``: ready or failed; None while it prepares."""
    for entry in reversed(by_device(read_events(project)).get(name, [])):
        kind = _kind(entry)
        if kind == "preparing":
            return None
        moment = _since_epoch(entry.get("time", "")) or 0.0
        if kind == "ready":
            return f"ready for {entry['event'].get('package', '?')}" if moment >= since else None
        if kind == "failed" and entry["event"].get("reason") == "prepare" and moment >= since:
            return describe(name, entry, []).split(": ", 1)[1]
    return None


def _live_line(name: str, items: list[dict]) -> str:
    ready = next((item for item in reversed(items) if _kind(item) == "ready"), None)
    app = ready["event"].get("package", "?") if ready else "?"
    return f"{name}: Live on for {app}, last {_kind(items[-1])} {items[-1].get('time', '?')}"


def armed_status(project: Path, devices: list[dict]) -> int:
    """``status`` when Moru armed Live: this worktree's devices as before, the others by owner."""
    live = live_devices(read_events(project))
    codes = []
    for device in devices:
        name = f"{device.get('platform')} {device.get('device')}"
        if live_device_arm.owned_by(device, project) and name in live:
            preparation = _preparation_result(live[name])
            print(describe(name, preparation, live[name]) if preparation else _live_line(name, live[name]))
            codes.append(PROBLEM_EXIT if preparation else 0)
        else:
            print(live_device_arm.describe(device, project))
            mine = live_device_arm.owned_by(device, project)
            codes.append(ARMED_EXIT)
    return next((code for code in (PROBLEM_EXIT, ARMED_EXIT) if code in codes), 0)


def status(project: Path, args: argparse.Namespace) -> int:
    armed = live_device_arm.armed_devices(project)
    if armed and not args.json:
        return armed_status(project, armed)
    live = live_devices(read_events(project))
    preparation = {name: entry for name, items in live.items() if (entry := _preparation_result(items))}
    if args.json:
        print(json.dumps({name: items[-1] for name, items in live.items()}))
    elif not live:
        print("Live is off")
    for name, items in live.items():
        if not args.json:
            if name in preparation:
                print(describe(name, preparation[name], items))
                continue
            print(_live_line(name, items))
    return PROBLEM_EXIT if preparation else 0 if live else MISSING_EXIT


def check(project: Path, args: argparse.Namespace) -> int:
    live = live_devices(read_events(project))
    armed = live_device_arm.armed_devices(project)
    if not live and armed and not args.json:
        # Live runs, but not from this worktree: the save cannot have reached the app.
        return armed_status(project, armed)
    if not live:
        print(json.dumps({"status": "off", "devices": {}}) if args.json else "Live is off")
        return MISSING_EXIT
    files = [_relative(project, raw) for raw in args.files]
    since = _since_epoch(args.since) if args.since else None
    results = {
        name: ("problem", preparation) if (preparation := _preparation_result(items)) else result_for(items, files, since)
        for name, items in live.items()
    }
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
    for name in ("status", "check", "start", "open", "stop"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
        command.add_argument("--json", action="store_true")
        if name == "check":
            command.add_argument("--files", nargs="+", default=[])
            command.add_argument("--since", default=None)
        if name == "start":
            command.add_argument("--platform", choices=("android", "ios"), default=None)
            command.add_argument("--wait", type=float, default=300.0, help="seconds to wait for ready; 0 returns at once")
        if name in ("start", "open"):
            command.add_argument("--link", required=name == "open", default=None)
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    if args.command in ("status", "check"):
        return status(project, args) if args.command == "status" else check(project, args)
    if args.command == "start":
        code, lines = live_device_arm.start(project, args.platform, args.link, args.wait,
                                            lambda name, since: ready_line(project, name, since))
    else:
        code, lines = live_device_arm.send(project, args.command, getattr(args, "link", None))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
