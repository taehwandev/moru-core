"""Install a stable Moru Core launcher for user-level runtime hooks."""

from __future__ import annotations

import os
from pathlib import Path


LAUNCHER_NAME = "moru-hook"
STATE_DIR_NAME = ".moru"
ROOT_POINTER_NAME = "moru-root"


def stable_launcher_path() -> Path:
    return Path.home() / STATE_DIR_NAME / "bin" / LAUNCHER_NAME


def stable_root_pointer_path() -> Path:
    return Path.home() / STATE_DIR_NAME / ROOT_POINTER_NAME


def is_disposable_root(root: Path) -> bool:
    """Whether this checkout is a task worktree, which outlives its task."""

    parts = Path(root).resolve(strict=False).parts
    return any(
        parts[index] == STATE_DIR_NAME
        and parts[index + 1] == "worktrees"
        for index in range(len(parts) - 1)
    )


def downgrades_the_shared_root(root: Path, pointer_path: Path) -> bool:
    """Whether this would repoint a durable shared root at a disposable one.

    Every runtime on the machine reads this pointer, so aiming it at a task
    worktree leaves the bridge dangling the moment that task is cleaned up --
    and the repair then needs the tooling the pointer no longer finds. It
    happens by accident: running the installer from a worktree is how you test
    it, and the side effect is machine-wide and silent.

    Installing *from* a worktree is not itself the problem, which is why the
    first attempt at this guard was wrong: it refused outright and broke
    developing Moru in a worktree against a throwaway home. The loss is specific
    -- replacing a durable root that still exists with a disposable one -- so
    that is what this asks. A first install, a repeat of the same target, and a
    pointer that is already a worktree all lose nothing and are left alone.
    """

    if not is_disposable_root(root):
        return False
    current = _read_text(pointer_path).strip()
    if not current:
        return False
    if Path(current) == Path(root).resolve(strict=False):
        return False
    if is_disposable_root(Path(current)):
        return False
    return Path(current).is_dir()


def ensure_stable_launcher(root: Path, dry_run: bool) -> list[dict]:
    """Install or verify the home-stable launcher and root pointer."""
    from support.native_launcher_install import artifact_plan, install_native, installed_matches

    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    if downgrades_the_shared_root(root, pointer_path):
        blocked = {
            "status": "blocked",
            "detail": (
                f"refusing to repoint the shared root from {_read_text(pointer_path).strip()} "
                f"to the task worktree {Path(root).resolve(strict=False)}; run the "
                "installer from the main checkout"
            ),
        }
        return [
            {"tool": "moru", "hook": "stable_launcher", "path": str(launcher_path), **blocked},
            {"tool": "moru", "hook": "root_pointer", "path": str(pointer_path), **blocked},
        ]
    root_text = f"{root.resolve()}\n"
    native = artifact_plan(root, launcher_path)
    native_ok = native is None or installed_matches(native)
    launcher_text = _launcher_script_text(native=native is not None)
    launcher_ok = (
        launcher_path.exists()
        and _read_text(launcher_path) == launcher_text
        and _is_executable(launcher_path)
        and native_ok
    )
    pointer_ok = pointer_path.exists() and _read_text(pointer_path) == root_text

    if dry_run:
        rows = [
            {"tool": "moru", "hook": "stable_launcher",
             "status": "ok" if launcher_ok else "missing", "path": str(launcher_path)},
            {"tool": "moru", "hook": "root_pointer",
             "status": "ok" if pointer_ok else "missing", "path": str(pointer_path)},
        ]
        return rows

    launcher_status = "ok"
    pointer_status = "ok"
    if native is not None and not native_ok:
        install_native(native)
    if not launcher_ok:
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        launcher_path.write_text(launcher_text)
        launcher_path.chmod(0o755)
        launcher_status = "installed"
    if not pointer_ok:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(root_text)
        pointer_status = "installed"
    return [
        {"tool": "moru", "hook": "stable_launcher", "status": launcher_status, "path": str(launcher_path)},
        {"tool": "moru", "hook": "root_pointer", "status": pointer_status, "path": str(pointer_path)},
    ]


def stable_launcher_issue(root: Path) -> str:
    """Return a preflight warning when the stable launcher is absent or stale."""
    from support.native_launcher_install import artifact_plan, installed_matches

    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    native = artifact_plan(root, launcher_path)
    expected = _launcher_script_text(native=native is not None)
    if (not launcher_path.exists() or _read_text(launcher_path) != expected
            or not _is_executable(launcher_path)
            or (native is not None and not installed_matches(native))):
        return (
            "Moru Core stable launcher is missing or stale. "
            f"Run: python3 {root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    if _read_text(pointer_path) != f"{root.resolve()}\n":
        return (
            "Moru Core root pointer is missing or stale. "
            f"Run: python3 {root / 'scripts' / 'setup-agent-hooks.py'}"
        )
    return ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _launcher_script_text(native: bool = False) -> str:
    from support.launcher_python import LAUNCHER_SCRIPT

    if native:
        from support.native_launcher_install import native_launcher_header

        return native_launcher_header() + LAUNCHER_SCRIPT.split("\n", 1)[1]
    return LAUNCHER_SCRIPT
