"""Local workflow label helpers used by the workflow CLI."""

from __future__ import annotations


import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agent_runtime_identity import detect_runtime
from workflow_catalog import SPILL_ACTION_LABELS, SPILL_ROUTE_LABELS


DEFAULT_SPILL_SETUP_HELPER = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Spill"
    / "adapters"
    / "setup"
    / "spill-token-metering-setup.mjs"
)
SPILL_HELPER_PATH_ENV = "MORU_SPILL_HELPER_PATH"
SPILL_ALLOWED_TOOLS = {"codex", "claude", "antigravity", "openai"}
SAFE_WORKFLOW_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
REQUIRED_SPILL_ACTION_LABELS = {
    "classify",
    "dispatch",
    "dispatch-finalize",
    "list",
    "query",
    "validate",
}


def spill_tool_label(env: dict[str, str] | None = None) -> str:
    tool, _ = detect_runtime(env)
    return tool if tool in SPILL_ALLOWED_TOOLS else "codex"


def spill_setup_helper_path() -> Path:
    override = os.environ.get(SPILL_HELPER_PATH_ENV, "")
    return Path(override) if override else DEFAULT_SPILL_SETUP_HELPER


def has_spill_setup_helper() -> bool:
    try:
        return spill_setup_helper_path().is_file()
    except OSError:
        # A sandbox can deny even stat() on an optional user-level adapter.
        return False


def write_spill_label(task_type: str, stage: str, *, if_absent: bool = False) -> None:
    """Write safe context before returning; never record a usage event.

    Waiting for the bounded local write prevents an older detached classify
    process from landing after a real task label. Discovery actions use
    if_absent so they cannot replace an active task. Advisory routes do not
    call this helper at all. stdin never inherits a runtime hook payload.
    """

    if not has_spill_setup_helper():
        return
    try:
        subprocess.run(
            [
                "node",
                str(spill_setup_helper_path()),
                "--label",
                spill_tool_label(),
                "--task-type",
                task_type,
                "--stage",
                stage,
                *(["--if-absent"] if if_absent else []),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def spill_label_for_args(args: Any) -> tuple[str, str]:
    if args.action == "route":
        return SPILL_ROUTE_LABELS[args.command]
    return SPILL_ACTION_LABELS.get(args.action, ("analysis", "classify"))


def validate_spill_label_contracts(command_names: set[str]) -> list[str]:
    failures: list[str] = []
    route_label_names = set(SPILL_ROUTE_LABELS)

    for command in sorted(command_names - route_label_names):
        failures.append(f"{command}: missing Spill workflow route label")
    for command in sorted(route_label_names - command_names):
        failures.append(f"{command}: Spill workflow route label has no matching command")

    action_label_names = set(SPILL_ACTION_LABELS)
    for action in sorted(REQUIRED_SPILL_ACTION_LABELS - action_label_names):
        failures.append(f"{action}: missing Spill workflow action label")

    for name, labels in sorted({**SPILL_ACTION_LABELS, **SPILL_ROUTE_LABELS}.items()):
        if not isinstance(labels, tuple) or len(labels) != 2:
            failures.append(f"{name}: Spill label must be a (task_type, stage) tuple")
            continue
        task_type, stage = labels
        if not SAFE_WORKFLOW_SLUG_RE.match(task_type):
            failures.append(f"{name}: invalid Spill task_type label `{task_type}`")
        if not SAFE_WORKFLOW_SLUG_RE.match(stage):
            failures.append(f"{name}: invalid Spill stage label `{stage}`")

    return failures
