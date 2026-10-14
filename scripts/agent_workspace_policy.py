"""Workspace policy helpers shared by Moru Core hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def is_writing_workspace(project: Path) -> bool:
    """Return true for a draft-only writing workspace documented by AGENTS.md."""
    instructions = project / "AGENTS.md"
    drafts = project / "drafts"
    if not instructions.exists() or not drafts.is_dir():
        return False
    try:
        text = instructions.read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return (
        "writing workspace instructions" in text
        or "primary workspace for blog posts" in text
        or "local_writing_workspace" in text
    )


def is_non_git_workspace(project: Path) -> bool:
    """Return true when no Git repository owns this path.

    A workspace root such as `$HOME` or `~/git` holds repositories without being
    one, so `git status` there fails for a structural reason rather than a
    fixable one. Without this, the gate demands git evidence that cannot exist
    and becomes impossible to satisfy.
    """
    try:
        current = project.resolve()
    except OSError:
        return False
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return False
    return True


def is_git_status_review_only(project: Path, git_status: dict[str, Any]) -> bool:
    if git_status.get("returncode") == 0:
        return False
    # A real repo whose status command failed is still a genuine failure; only
    # the absence of a repository makes git evidence structurally unavailable.
    return is_writing_workspace(project) or is_non_git_workspace(project)


def non_git_writing_workspace_note(project: Path) -> str:
    if is_writing_workspace(project):
        return (
            f"{project} is a documented writing workspace without Git tracking; "
            "treat git status/diff evidence as review-only for draft editing"
        )
    return (
        f"{project} is not inside a Git repository; treat git status/diff "
        "evidence as review-only because it cannot exist for this path"
    )

