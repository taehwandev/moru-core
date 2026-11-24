"""Recognize unchanged parent files during an in-progress merge structure review.

Owner: parent/index equality for structural baseline classification only.
Allowed imports: pathlib, typing, the native probe and the caller's read-only command runner.
Forbidden imports: lifecycle/admission writes, Git mutations and policy overrides.
Callers/tests: agent_review_structure; test_agent_review_merge_baseline.
Verification: real Git merge, edited/conflicted/index/working-tree counterexamples.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from support.native_probe_transport import NativeProbe

def inherited_merge_paths(
    project: Path,
    paths: list[Path],
    run_command: Callable[[list[str], Path], dict[str, Any]],
) -> dict[str, str]:
    """Keep actual edits checked; uncertain Git state retains ordinary checks."""
    if not paths:
        return {}
    merge = run_command(["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"], project)
    parent = merge.get("stdout", "").strip()
    if merge["returncode"] or len(parent) not in (40, 64) or any(
        char not in "0123456789abcdef" for char in parent
    ):
        return {}
    quiet = run_command(["git", "diff", "--quiet"], project)
    unresolved = run_command(["git", "ls-files", "-u", "-z"], project)
    if quiet["returncode"] or unresolved["returncode"] or unresolved["stdout"]:
        return {}
    selected = {str(path) for path in paths}
    ordered = sorted(selected)
    refs = []
    for ref in ("HEAD", parent):
        changed = run_command(
            ["git", "diff", "--cached", "--name-only", "--no-renames", "-z", ref, "--"],
            project,
        )
        existing = run_command(
            ["git", "ls-tree", "-r", "--name-only", "-z", ref, "--", *ordered],
            project,
        )
        if changed["returncode"] or existing["returncode"]:
            return {}
        refs.append((changed["stdout"], existing["stdout"]))
    native = NativeProbe.request("--completion-probe", "structure-merge-baseline", {
        "parent": parent, "selected": ordered, "refs": refs,
    })
    inherited = native.get("inherited") if native is not None else None
    if isinstance(inherited, dict) and all(
        path in selected and ref in ("HEAD", parent) for path, ref in inherited.items()
    ):
        return inherited
    return _python_inherited_paths(selected, parent, refs)


def _python_inherited_paths(
    selected: set[str], parent: str, refs: list[tuple[str, str]],
) -> dict[str, str]:
    inherited: dict[str, str] = {}
    for ref, (changed, existing) in zip(("HEAD", parent), refs):
        same = set(existing.split("\0")) - set(changed.split("\0"))
        inherited.update({path: ref for path in selected & same})
    return inherited
