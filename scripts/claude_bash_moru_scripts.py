"""Trusted Moru checkout script identity and read-only CLI argument allowlists.

owner: trusted Moru script path resolution and exact read-only CLI argument validation
allowed imports: standard library and support.stable_launcher
forbidden imports: lifecycle writers, gate decision emitters, subprocess execution
callers/tests: scripts/claude_bash_readonly.py; tests/test_claude_pretool_classifier_friction.py, tests/test_installer_is_reachable.py
verification: forged checkout dirs and unallowlisted CLI flags are rejected as mutating while trusted checkouts and exact read-only flags pass
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from support.stable_launcher import stable_root_pointer_path

STRUCTURE_CHECK_FLAGS = frozenset({"-h", "--help", "--json"})
STRUCTURE_CHECK_VALUED = frozenset({"--project", "--review-path"})
OS_STATUS_FLAGS = frozenset({"-h", "--help", "--validate", "--efficiency-trends", "--all-projects"})
OS_STATUS_VALUED = frozenset({"--project", "--workspace-root", "--month", "--spill-db", "--codex-db"})
WORKFLOW_SUBCOMMAND_GRAMMARS: dict[
    str,
    tuple[frozenset[str], frozenset[str], bool, int, int | None, dict[str, frozenset[str]]],
] = {
    "validate": (frozenset({"-h", "--help"}), frozenset(), False, 0, 0, {}),
    "list": (frozenset({"-h", "--help"}), frozenset(), False, 0, 0, {}),
    "query": (
        frozenset({"-h", "--help"}),
        frozenset({"--max", "--format", "--project", "--rules"}),
        True,
        1,
        None,
        {"--format": frozenset({"markdown", "json"})},
    ),
    "route": (
        frozenset({"-h", "--help", "--request-classified", "--advisory", "--hook-stdin"}),
        frozenset({
            "--project", "--platform", "--concern", "--request", "--continuation-scope",
            "--intent-envelope", "--approval-record", "--user-approval",
            "--runtime-session-id", "--surface-path", "--classification-evidence",
            "--rules", "--parent-evidence", "--format",
        }),
        True,
        0,
        1,
        {"--format": frozenset({"markdown", "json"})},
    ),
    "classify": (
        frozenset({"-h", "--help"}),
        frozenset({
            "--continuation-scope", "--command", "--intent-envelope",
            "--approval-record", "--user-approval", "--runtime-session-id", "--format",
        }),
        True,
        1,
        1,
        {"--format": frozenset({"markdown", "json"})},
    ),
}

_FIXED_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp")


def _temp_roots() -> list[Path]:
    """Resolved OS temp directories; no Moru checkout under these is ever trusted."""
    roots: list[Path] = []
    seen: set[Path] = set()
    candidates = [*_FIXED_TEMP_ROOTS, tempfile.gettempdir(), os.environ.get("TMPDIR", "")]
    for raw in candidates:
        if not raw:
            continue
        try:
            resolved = Path(raw).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if resolved == resolved.parent or resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _is_under_temp_root(path: Path) -> bool:
    """True when `path` is inside an OS temp root."""
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return True
    return any(resolved == root or resolved.is_relative_to(root) for root in _temp_roots())


def trusted_moru_scripts_dirs(pointer_path: Path | None = None) -> set[Path]:
    """Trust only scripts/ in this module's checkout or the installed pointer's root.

    Linked worktrees are never enumerated, and paths under temp roots are never
    trusted, so a newly created throwaway worktree in /tmp cannot execute forged
    scripts under a read-only classification.
    """
    candidates: set[Path] = {Path(__file__).resolve().parent.parent}
    pointer = pointer_path if pointer_path is not None else stable_root_pointer_path()
    try:
        if pointer.is_file():
            raw = pointer.read_text(encoding="utf-8", errors="ignore").strip()
            if raw:
                pointed = Path(raw).expanduser().resolve()
                if pointed.is_dir():
                    candidates.add(pointed)
    except (OSError, ValueError):
        pass
    trusted: set[Path] = set()
    for root in candidates:
        if _is_under_temp_root(root):
            continue
        scripts_dir = root / "scripts"
        try:
            if scripts_dir.is_dir():
                resolved_scripts = scripts_dir.resolve()
                if not _is_under_temp_root(resolved_scripts):
                    trusted.add(resolved_scripts)
        except (OSError, ValueError):
            continue
    return trusted


def is_trusted_moru_script(script: Path, name: str, *, pointer_path: Path | None = None) -> bool:
    """True only when `script` is an existing real file in a trusted non-temp Moru scripts/ dir."""
    try:
        resolved = script.resolve(strict=True)
    except (OSError, ValueError):
        return False
    if _is_under_temp_root(resolved):
        return False
    return (
        resolved.name == name
        and resolved.is_file()
        and resolved.parent in trusted_moru_scripts_dirs(pointer_path)
    )


def allowlisted_cli_args(
    arguments: list[str],
    *,
    flags: frozenset[str],
    valued: frozenset[str],
    allow_positionals: bool = False,
    min_positionals: int = 0,
    max_positionals: int | None = None,
    choices: dict[str, frozenset[str]] | None = None,
) -> bool:
    """Validate that every option and positional matches an explicit read-only CLI grammar."""
    positionals = 0
    saw_help = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        index += 1
        if token in flags:
            if token in {"-h", "--help"}:
                saw_help = True
            continue
        if token.startswith("-"):
            option, has_eq, value = token.partition("=")
            if option not in valued:
                return False
            if not has_eq:
                if index >= len(arguments):
                    return False
                value = arguments[index]
                index += 1
            if not value or value.startswith("-"):
                return False
            if choices and option in choices and value not in choices[option]:
                return False
            continue
        if not allow_positionals:
            return False
        positionals += 1
    if saw_help:
        return True
    if positionals < min_positionals:
        return False
    if max_positionals is not None and positionals > max_positionals:
        return False
    return True


def workflow_read_only_args(arguments: list[str]) -> bool:
    """Allowlist exact read-only `workflow.py` subcommands and their flags."""
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        token = arguments[index]
        if token in {"-h", "--help"}:
            return index + 1 == len(arguments)
        option, has_eq, value = token.partition("=")
        if option != "--rules":
            return False
        if has_eq:
            if not value or value.startswith("-"):
                return False
            index += 1
        else:
            if index + 1 >= len(arguments) or not arguments[index + 1] or arguments[index + 1].startswith("-"):
                return False
            index += 2
    if index >= len(arguments):
        return False
    grammar = WORKFLOW_SUBCOMMAND_GRAMMARS.get(arguments[index])
    if grammar is None:
        return False
    flags, valued, allow_pos, min_pos, max_pos, choices = grammar
    return allowlisted_cli_args(
        arguments[index + 1 :],
        flags=flags,
        valued=valued,
        allow_positionals=allow_pos,
        min_positionals=min_pos,
        max_positionals=max_pos,
        choices=choices,
    )
