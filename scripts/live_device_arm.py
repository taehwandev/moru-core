"""Where an agent's Android/iOS Live stands when Moru only arms Live: who may run it, and asking Moru to.

Owner: the armed-Live state Moru writes (``~/Library/Application Support/Moru/live-device/armed.json``)
and the request files agents leave for Moru (``requests/`` next to it).
Turning Live on in Moru arms a device for a repository without building; the app
is built and run from the worktree of the first agent that asks (``start``), and
that worktree owns the device until it asks to ``stop`` or Live is turned off.
Agents sharing that worktree share Live; another worktree gets "busy" at once.
Allowed imports: the standard library.
Forbidden imports: the workflow route, the agent lifecycle and hook installers.
Callers/tests: ``live_device.py`` (``status``, ``start``, ``open``, ``stop``);
coverage lives in ``tests/test_live_device_arm.py``.
Verification: run that module.

``armed.json`` is ``{"devices": [{"task", "repo", "platform", "device", "owner",
"state"}]}``: ``repo`` is the git common directory every worktree of the
project shares, ``owner`` the worktree running Live there (null while armed and
unstarted), ``state`` one of ``armed``, ``preparing``, ``ready``, ``failed``.
A request is ``{"id", "time", "action", "project", "repo", "platform", "link"}``
with ``action`` ``start``, ``open`` or ``stop``; Moru removes it once handled.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


def data_dir() -> Path:
    """Where every Moru of this user (a dev build too) keeps the armed state; ``MORU_LIVE_DEVICE_DIR`` overrides it."""
    configured = os.environ.get("MORU_LIVE_DEVICE_DIR")
    return Path(configured) if configured else Path.home() / "Library" / "Application Support" / "Moru" / "live-device"


def repo_key(project: Path) -> str:
    """The git common directory of ``project`` (the same for all its worktrees), else the folder itself."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return str(Path(result.stdout.strip()).resolve())
    return str(project.resolve())


def armed_devices(project: Path, platform: Optional[str] = None, base: Optional[Path] = None) -> list[dict]:
    """The devices Moru armed for ``project``'s repository (optionally one platform's)."""
    try:
        state = json.loads(((base or data_dir()) / "armed.json").read_text())
    except (OSError, ValueError):
        return []
    key = repo_key(project)
    devices = state.get("devices") if isinstance(state, dict) else None
    return [
        device for device in devices or []
        if isinstance(device, dict) and device.get("repo") == key and (platform is None or device.get("platform") == platform)
    ]


def owned_by(device: dict, project: Path) -> bool:
    owner = device.get("owner")
    return bool(owner) and Path(owner).resolve() == project.resolve()


def request(project: Path, action: str, platform: Optional[str] = None, link: Optional[str] = None,
            base: Optional[Path] = None) -> str:
    """Leaves ``action`` for Moru and returns its id."""
    folder = (base or data_dir()) / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    ident = uuid.uuid4().hex
    body = {
        "id": ident, "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": action,
        "project": str(project.resolve()), "repo": repo_key(project), "platform": platform, "link": link,
    }
    temporary = folder / f".{ident}.tmp"
    temporary.write_text(json.dumps(body))
    temporary.replace(folder / f"{ident}.json")
    return ident


def wait_until(done: Callable[[], bool], seconds: float, step: float = 0.25,
               sleep: Optional[Callable[[float], None]] = None) -> bool:
    """Polls ``done`` until it holds or ``seconds`` pass."""
    sleep = sleep or time.sleep
    end = time.monotonic() + seconds
    while True:
        if done():
            return True
        if time.monotonic() >= end:
            return False
        sleep(step)


def describe(device: dict, project: Path) -> str:
    name = f"{device.get('platform', '?')} {device.get('device', '?')}"
    if owned_by(device, project):
        return f"{name}: Live runs from this worktree ({device.get('state', '?')})"
    if device.get("owner"):
        return f"{name}: Live is busy, run from {device['owner']} ({device.get('state', '?')})"
    return f"{name}: Live armed, not started; run live_device.py start"


def start(project: Path, platform: Optional[str], link: Optional[str], wait: float,
          ready_since: Callable[[str, float], Optional[str]], base: Optional[Path] = None,
          answer_seconds: float = 8.0, sleep: Optional[Callable[[float], None]] = None) -> tuple[int, list[str]]:
    """Asks Moru to run Live from ``project`` on its armed devices; (exit code, lines).

    Exit 0 when every armed device runs from this worktree (and, with ``wait``,
    is ready), 6 when another worktree has one, 5 when nothing is armed or Moru
    does not answer, 4 when preparation failed. A device this worktree already
    runs is not rebuilt.
    """
    devices = armed_devices(project, platform, base)
    if not devices:
        return 5, ["Live is not armed for this project; build and run as usual"]
    if all(device.get("owner") and not owned_by(device, project) for device in devices):
        return 6, [describe(device, project) for device in devices]
    fresh = not all(owned_by(device, project) for device in devices)
    # A device this worktree already runs counts as ready from its last start.
    asked = time.time() if fresh else 0.0
    if fresh:
        request(project, "start", platform, link, base)
        wait_until(lambda: all(d.get("owner") for d in armed_devices(project, platform, base)), answer_seconds, sleep=sleep)
    elif link:
        request(project, "open", platform, link, base)
    devices = armed_devices(project, platform, base)
    lines = [describe(device, project) for device in devices]
    if any(not device.get("owner") for device in devices):
        return 5, lines + ["Moru has not answered; the Devices tool must be open in Moru"]
    if not all(owned_by(device, project) for device in devices):
        return 6, lines
    if wait > 0:
        names = [f"{d.get('platform')} {d.get('device')}" for d in devices]
        results: dict[str, Optional[str]] = {}

        def all_ready() -> bool:
            for name in names:
                results[name] = ready_since(name, asked)
            return all(results.values())

        wait_until(all_ready, wait, step=1.0, sleep=sleep)
        lines = [f"{name}: {results[name] or 'still preparing'}" for name in names]
        if any(result is None for result in results.values()):
            return 5, lines
        if any(result.startswith("failed") for result in results.values() if result):
            return 4, lines
    return 0, lines


def send(project: Path, action: str, link: Optional[str], base: Optional[Path] = None) -> tuple[int, list[str]]:
    """``open`` a link in, or ``stop``, the Live this worktree runs; (exit code, lines)."""
    mine = [device for device in armed_devices(project, None, base) if owned_by(device, project)]
    if not mine:
        return 5, ["Live does not run from this worktree; run live_device.py start first"]
    request(project, action, None, link, base)
    what = f"open {link}" if action == "open" else "stop"
    return 0, [f"{d.get('platform')} {d.get('device')}: asked Moru to {what}" for d in mine]
