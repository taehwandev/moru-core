"""Install a stable Moru Core launcher for user-level runtime hooks."""

from __future__ import annotations

import os
from pathlib import Path


LAUNCHER_NAME = "tao-hook"
STATE_DIR_NAME = ".tao"
ROOT_POINTER_NAME = "tao-root"
MORU_LAUNCHER_NAME = "moru-hook"
MORU_STATE_DIR_NAME = ".moru"
MORU_ROOT_POINTER_NAME = "moru-root"


def stable_launcher_path() -> Path:
    return Path.home() / STATE_DIR_NAME / "bin" / LAUNCHER_NAME


def stable_root_pointer_path() -> Path:
    return Path.home() / STATE_DIR_NAME / ROOT_POINTER_NAME


def moru_launcher_path() -> Path:
    return Path.home() / MORU_STATE_DIR_NAME / "bin" / MORU_LAUNCHER_NAME


def preferred_launcher_path() -> Path:
    """Use the Moru launcher after the global state migration is ready."""
    if (Path.home() / MORU_STATE_DIR_NAME / "state-ready").is_file():
        return moru_launcher_path()
    return stable_launcher_path()


def moru_root_pointer_path() -> Path:
    return Path.home() / MORU_STATE_DIR_NAME / MORU_ROOT_POINTER_NAME


def is_disposable_root(root: Path) -> bool:
    """Whether this checkout is a task worktree, which outlives its task."""

    parts = Path(root).resolve(strict=False).parts
    return any(
        parts[index] in (STATE_DIR_NAME, MORU_STATE_DIR_NAME)
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
    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    moru_path = moru_launcher_path()
    moru_pointer_path = moru_root_pointer_path()
    blocked_pointer = next(
        (path for path in (pointer_path, moru_pointer_path)
         if downgrades_the_shared_root(root, path)),
        None,
    )
    if blocked_pointer is not None:
        blocked = {
            "status": "blocked",
            "detail": (
                f"refusing to repoint the shared root from {_read_text(blocked_pointer).strip()} "
                f"to the task worktree {Path(root).resolve(strict=False)}; run the "
                "installer from the main checkout"
            ),
        }
        return [
            {"tool": "tao", "hook": "stable_launcher", "path": str(launcher_path), **blocked},
            {"tool": "tao", "hook": "root_pointer", "path": str(pointer_path), **blocked},
            {"tool": "moru", "hook": "stable_launcher", "path": str(moru_path), **blocked},
            {"tool": "moru", "hook": "root_pointer", "path": str(moru_pointer_path), **blocked},
        ]
    root_text = f"{root.resolve()}\n"
    launcher_text = _launcher_script_text()
    moru_text = _moru_launcher_script_text()

    launcher_ok = (
        launcher_path.exists()
        and _read_text(launcher_path) == launcher_text
        and _is_executable(launcher_path)
    )
    pointer_ok = pointer_path.exists() and _read_text(pointer_path) == root_text
    moru_ok = moru_path.exists() and _read_text(moru_path) == moru_text and _is_executable(moru_path)
    moru_pointer_ok = moru_pointer_path.exists() and _read_text(moru_pointer_path) == root_text

    if dry_run:
        return [
            {
                "tool": "tao",
                "hook": "stable_launcher",
                "status": "ok" if launcher_ok else "missing",
                "path": str(launcher_path),
            },
            {
                "tool": "tao",
                "hook": "root_pointer",
                "status": "ok" if pointer_ok else "missing",
                "path": str(pointer_path),
            },
            {
                "tool": "moru", "hook": "stable_launcher",
                "status": "ok" if moru_ok else "missing", "path": str(moru_path),
            },
            {
                "tool": "moru", "hook": "root_pointer",
                "status": "ok" if moru_pointer_ok else "missing", "path": str(moru_pointer_path),
            },
        ]

    launcher_status = "ok"
    pointer_status = "ok"
    if not launcher_ok:
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        launcher_path.write_text(launcher_text)
        launcher_path.chmod(0o755)
        launcher_status = "installed"
    if not pointer_ok:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(root_text)
        pointer_status = "installed"

    moru_status = "ok"
    moru_pointer_status = "ok"
    if not moru_ok:
        moru_path.parent.mkdir(parents=True, exist_ok=True)
        moru_path.write_text(moru_text)
        moru_path.chmod(0o755)
        moru_status = "installed"
    if not moru_pointer_ok:
        moru_pointer_path.parent.mkdir(parents=True, exist_ok=True)
        moru_pointer_path.write_text(root_text)
        moru_pointer_status = "installed"

    return [
        {"tool": "tao", "hook": "stable_launcher", "status": launcher_status, "path": str(launcher_path)},
        {"tool": "tao", "hook": "root_pointer", "status": pointer_status, "path": str(pointer_path)},
        {"tool": "moru", "hook": "stable_launcher", "status": moru_status, "path": str(moru_path)},
        {"tool": "moru", "hook": "root_pointer", "status": moru_pointer_status, "path": str(moru_pointer_path)},
    ]


def stable_launcher_issue(root: Path) -> str:
    """Return a preflight warning when the stable launcher is absent or stale."""
    launcher_path = stable_launcher_path()
    pointer_path = stable_root_pointer_path()
    if not launcher_path.exists() or _read_text(launcher_path) != _launcher_script_text() or not _is_executable(launcher_path):
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


def _launcher_script_text() -> str:
    return """#!/usr/bin/env python3
import os
import runpy
import sys
import traceback
from pathlib import Path

STATE_DIR_NAME = ".tao"
ROOT_POINTER_NAME = "tao-root"
REQUIRED_MARKERS = ("AGENTS.md", "index.md", "scripts/workflow.py")
SCRIPT_ALIASES = {
    "workflow": "workflow.py",
    "agent-hook": "agent-hook.py",
    "agent-preflight": "agent-preflight.py",
    "agent-finish-check": "agent-finish-check.py",
    "execution-capsule": "agent_execution_capsule.py",
    "agent-entry": "agent-entry.py",
    "project-discover": "project-discover.py",
    "setup-agent-hooks": "setup-agent-hooks.py",
    "agent-os-status": "agent-os-status.py",
    "agent-os-watchdog": "agent-os-watchdog.py",
    "agent-os-maintenance": "agent-os-maintenance.py",
    "agent-mailbox": "agent-mailbox.py",
    "mailbox-hook": "agent_mailbox_hook.py",
    "project-memory": "agent_project_memory.py",
    "work-cards": "agent_work_cards.py",
    "workflow-dispatch": "workflow_dispatch.py",
    "workflow-dispatch-launch": "workflow_dispatch_launch.py",
    "claude-pretool-gate": "claude_pretool_gate.py",
    "claude-statusline": "claude_statusline.py",
    "claude-continuation-hook": "claude_continuation_hook.py",
    "claude-stop-gate": "claude_stop_gate.py",
    "codex-pretool-gate": "codex_pretool_gate.py",
    "codex-stop-gate": "codex_stop_gate.py",
    "operator-review": "codex_operator_review.py",
    "agy-statusline": "agy_statusline.py",
    "doctor": "agent_doctor.py",
    "next": "agent_next_action.py",
}
HOOK_ALIASES = {
    "start",
    "cancel",
    "fingerprint",
    "handoff",
    "resume",
    "checkpoint",
    "gate",
    "gate-batch",
    "verify",
    "review",
    "finish",
    "skill-feedback",
    "skill-draft",
    "skill-curate",
    "skill-review",
    "skill-maintenance",
    "repair-verify",
}
# Calling agent-finish-check.py directly skips agent-hook.py's repair-cycle
# ceremony (the structural repair receipt checks in
# main()) entirely -- it is a lower-level fallback for human debugging only,
# never the normal agent path. Require an explicit opt-in so an agent cannot
# casually use it to dodge the wrapped `finish` hook's guardrails.
DIRECT_FINISH_CHECK_ENV = "MORU_ALLOW_DIRECT_FINISH_CHECK"

def main():
    if len(sys.argv) < 2:
        return _soft_fail("missing Moru Core script alias")

    script_alias = sys.argv[1]
    passthrough_args = list(sys.argv[2:])
    if script_alias in ("--help", "-h", "help"):
        # Agents reach for --help first; an unsupported-alias error cost them a call.
        print("usage: tao-hook <alias> [args]; tao-hook <alias> --help shows an alias's options")
        print("lifecycle: " + ", ".join(sorted(HOOK_ALIASES)))
        print("scripts: " + ", ".join(sorted(SCRIPT_ALIASES)))
        return 0
    if script_alias in HOOK_ALIASES:
        script_name = "agent-hook.py"
        passthrough_args.insert(0, script_alias)
    elif script_alias == "agent-finish-check" and _env(DIRECT_FINISH_CHECK_ENV) != "1":
        return _soft_fail(
            "direct agent-finish-check is a human-debugging fallback and skips the "
            "finish hook's repair-cycle checks; run 'tao-hook finish' instead, "
            f"or set {DIRECT_FINISH_CHECK_ENV}=1 to use it directly on purpose"
        )
    else:
        script_name = SCRIPT_ALIASES.get(script_alias)
    if not script_name:
        return _soft_fail(f"unsupported Moru Core script alias: {script_alias}")

    root = _find_root()
    if root is None:
        return _soft_fail(
            "Moru Core root is not configured. Run setup-agent-hooks.py from the current Moru Core checkout."
        )

    script = root / "scripts" / script_name
    if not script.is_file():
        return _soft_fail(
            "Moru Core root pointer is stale. Run setup-agent-hooks.py from the current Moru Core checkout."
        )

    os.environ.setdefault("MORU_HOME", str(root))
    return _run_in_process(script, passthrough_args)

def _run_in_process(script, passthrough_args):
    # Every gated tool call, every prompt and every Stop pays for this launcher,
    # and spawning a second interpreter to reach the script cost 24 ms of the
    # 72 ms a PreToolUse gate took -- a third of it, before any policy ran. The
    # script is ordinary Python and this process has nothing to protect, so run
    # it here.
    #
    # The two things the child gave for free have to be restored by hand: the
    # scripts directory as sys.path[0], which is how these modules import each
    # other, and sys.argv as the script sees it.
    sys.argv = [str(script), *passthrough_args]
    scripts_directory = str(script.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)

    # A crash used to reach the caller as the child's non-zero exit, which
    # MORU_HOOK_SOFT_FAIL then absorbed. In-process it would reach the runtime as
    # a launcher traceback and a hook that brings down the tool call it gates,
    # so the same failure is converted back into the same exit code here.
    # KeyboardInterrupt is deliberately not caught: an interrupt belongs to the
    # operator, not to the hook.
    try:
        runpy.run_path(str(script), run_name="__main__")
        code = 0
    except SystemExit as requested:
        code = requested.code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            print(code, file=sys.stderr)
            code = 1
    except Exception:
        traceback.print_exc()
        code = 1

    if code and _env("MORU_HOOK_SOFT_FAIL") == "1":
        return 0
    return code

def _find_root():
    candidates: list[Path] = []
    env_root = _env("MORU_HOME").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())

    pointer_path = Path.home() / STATE_DIR_NAME / ROOT_POINTER_NAME
    try:
        pointer = pointer_path.read_text().strip()
    except OSError:
        pointer = ""
    if pointer:
        candidates.append(Path(pointer).expanduser())

    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.extend(cwd.parents)
    candidates.extend(
        [
            Path.home() / ".tao-agent-os",
            Path.home() / "tao-agent-os",
            Path.home() / "git" / "tao-agent-os",
            Path.home() / "Documents" / "KeyFlowVault" / "tao-agent-os",
            Path.home() / "GitHub" / "tao-agent-os",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_tao_root(resolved):
            return resolved
    return None

def _is_tao_root(path):
    return all((path / marker).exists() for marker in REQUIRED_MARKERS)

def _env(name):
    # Hook commands written before the rename still pass the TAO_ spelling.
    value = os.environ.get(name)
    if value is None:
        value = os.environ.get("TAO_" + name[len("MORU_"):])
    return value or ""

def _soft_fail(message):
    print(f"Moru Core hook skipped: {message}", file=sys.stderr)
    if _env("MORU_HOOK_SOFT_FAIL") == "1":
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
"""


def _moru_launcher_script_text() -> str:
    """Use the same dispatcher with a Moru entrypoint and the legacy aliases intact."""
    return (
        _launcher_script_text()
        .replace('STATE_DIR_NAME = ".tao"', 'STATE_DIR_NAME = ".moru"')
        .replace('ROOT_POINTER_NAME = "tao-root"', 'ROOT_POINTER_NAME = "moru-root"')
        .replace("tao-hook", "moru-hook")
    )
