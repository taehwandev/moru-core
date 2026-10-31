"""Self-contained Python launcher compatibility body; single alias owner."""

LAUNCHER_SCRIPT = r'''#!/usr/bin/env python3
import os
import runpy
import sys
import traceback
from pathlib import Path

STATE_DIR_NAME = ".moru"
ROOT_POINTER_NAME = "moru-root"
REQUIRED_MARKERS = ("AGENTS.md", "index.md", "scripts/workflow.py")
SCRIPT_ALIASES = {
    "workflow": "workflow.py",
    "checkout-identity": "checkout_identity.py",
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
    "loop": "agent_loop.py",
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
        print("usage: moru-hook <alias> [args]; moru-hook <alias> --help shows an alias's options")
        print("lifecycle: " + ", ".join(sorted(HOOK_ALIASES)))
        print("scripts: " + ", ".join(sorted(SCRIPT_ALIASES)))
        return 0
    if script_alias in HOOK_ALIASES:
        script_name = "agent-hook.py"
        passthrough_args.insert(0, script_alias)
    elif script_alias == "agent-finish-check" and _env(DIRECT_FINISH_CHECK_ENV) != "1":
        return _soft_fail(
            "direct agent-finish-check is a human-debugging fallback and skips the "
            "finish hook's repair-cycle checks; run 'moru-hook finish' instead, "
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
            Path.home() / "moru-core",
            Path.home() / "git" / "moru-core",
            Path.home() / "GitHub" / "moru-core",
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
        if _is_moru_root(resolved):
            return resolved
    return None

def _is_moru_root(path):
    return all((path / marker).exists() for marker in REQUIRED_MARKERS)

def _env(name):
    return os.environ.get(name) or ""

def _soft_fail(message):
    print(f"Moru Core hook skipped: {message}", file=sys.stderr)
    if _env("MORU_HOOK_SOFT_FAIL") == "1":
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
