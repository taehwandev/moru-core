"""Select an exact native admission bootstrap without executing a capability probe.

Owner: unittest bootstrap selection. Allowed: stdlib and artifact_plan's exact
source/executable receipt. Forbidden: spawning, installation, receipt generation,
project imports or authority. Caller: agent_verification_hook._execute_admitted;
verification: tests/test_native_unittest_admission.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from support.native_launcher_install import artifact_plan


def admission_bootstrap(command: list[str], runner: Path, environment: dict[str, str]) -> list[str]:
    """Choose before spawn; an unsupported/stale candidate retains isolated Python."""
    if (environment.get("MORU_LAUNCHER_BACKEND", "auto") in {"auto", "rust"}
            and command and _native_executable(command[0])):
        # An old launcher may interpret an unknown flag as a Python fallback.
        # Verify both current source membership/bytes and candidate executable
        # bytes; use that candidate directly, never an unverified installed copy.
        plan = artifact_plan(runner.parent.parent, runner)
        if plan is not None:
            return [str(plan["source"]), str(runner), "--unittest-admission", *command]
    return [sys.executable, "-I", "-S", str(runner), *command]


def _native_executable(program: str) -> bool:
    try:
        path = Path(program)
        return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)
    except (OSError, ValueError, TypeError):
        return False
