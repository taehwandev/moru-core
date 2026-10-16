"""Moves armed Android/iOS Live to the worktree an agent starts mobile UI work in, as its run starts.

Owner: the start hook's Live step. When a Moru run starts in a linked git
worktree of a project whose Live the user armed or runs, and the run is about
the app's screens (an android, ios or kmp platform, or a UI concern), Live is
asked to run from that worktree: it moves without reinstalling from the Task
folder or an idle worktree, and stays put when another agent is working with
it. Nothing happens for other work or when Live is off, so agents that do not
need a device never take it. Live is not handed back when the run finishes;
the user reviews the result on the device, and the next worktree takes it.
Allowed imports: the standard library and ``live_device_arm``.
Forbidden imports: the workflow route, the agent lifecycle and hook installers.
Callers/tests: ``agent-hook.py`` start; ``tests/test_live_device_follow.py``.
Verification: run that module.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional

import live_device_arm

MOBILE_PLATFORMS = frozenset({"android", "ios", "kmp"})
UI_CONCERNS = frozenset({"ui", "compose", "swiftui", "uikit", "design", "design-system", "preview", "device-testing", "navigation"})


def linked_worktree(project: Path) -> bool:
    """Whether ``project`` is a linked worktree (its git dir differs from the common one)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    lines = result.stdout.split()
    return result.returncode == 0 and len(lines) == 2 and Path(lines[0]).resolve() != Path(lines[1]).resolve()


def on_start(project: Path, platforms: Iterable[str], concerns: Iterable[str], base: Optional[Path] = None) -> list[str]:
    """Asks Moru to run armed Live from ``project`` when this run is mobile UI work there; the lines to print."""
    wanted = {str(p).lower() for p in platforms} & MOBILE_PLATFORMS or {str(c).lower() for c in concerns} & UI_CONCERNS
    if not wanted or not linked_worktree(project):
        return []
    devices = live_device_arm.armed_devices(project, base=base)
    movable = [d for d in devices if not live_device_arm.owned_by(d, project) and live_device_arm.movable(d, project)]
    if not movable:
        return []
    live_device_arm.request(project, "start", base=base,
                            takeover=[d.get("device") for d in movable if live_device_arm.idle_owner(d)])
    names = ", ".join(f"{d.get('platform')} {d.get('device')}" for d in movable)
    return [f"Live: moving {names} to this worktree without reinstalling; follow the live-device card "
            f"(live_device.py status shows when it is ready)"]
