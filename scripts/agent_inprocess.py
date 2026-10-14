"""Run local Moru Core Python entrypoints without spawning Python again."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Any


_PROCESS_STATE_LOCK = threading.RLock()


def run_callable_as_command(
    *,
    command: list[str],
    cwd: Path,
    callback: Callable[[], int | None],
) -> dict[str, Any]:
    old_cwd = Path.cwd()
    stdout = io.StringIO()
    stderr = io.StringIO()
    returncode = 0
    with _PROCESS_STATE_LOCK:
        try:
            os.chdir(cwd)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    result = callback()
                    returncode = int(result or 0)
                except SystemExit as error:
                    returncode = _system_exit_code(error)
                except Exception:
                    returncode = 1
                    traceback.print_exc()
        finally:
            os.chdir(old_cwd)
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": returncode,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "in_process": True,
    }


def run_script_main(script: Path, argv: list[str], cwd: Path) -> dict[str, Any]:
    command = [sys.executable, str(script), *argv]

    def _run() -> int | None:
        module = _load_script_module(script)
        old_argv = sys.argv
        try:
            sys.argv = [str(script), *argv]
            return module.main()
        finally:
            sys.argv = old_argv

    return run_callable_as_command(command=command, cwd=cwd, callback=_run)


def run_workflow_validate(tao_root: Path) -> dict[str, Any]:
    from workflow_validate import validate

    return run_callable_as_command(
        command=[sys.executable, str(tao_root / "scripts" / "workflow.py"), "validate"],
        cwd=tao_root,
        callback=validate,
    )


def _load_script_module(script: Path) -> Any:
    module_name = f"_tao_{script.stem.replace('-', '_')}_{abs(hash(script))}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load script: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _system_exit_code(error: SystemExit) -> int:
    if error.code is None:
        return 0
    if isinstance(error.code, int):
        return error.code
    return 1
