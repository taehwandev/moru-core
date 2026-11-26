"""Workspace policy helpers shared by Moru Core hooks."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from support.bounded_git import run_git


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
    if "GIT_DIR" in os.environ or "GIT_WORK_TREE" in os.environ:
        return False
    try:
        current = project.resolve()
    except OSError:
        return False
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return False
    try:
        probe = run_git(["git", "rev-parse", "--git-dir"], cwd=current,
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        env={**os.environ, "LC_ALL": "C"})
    except OSError:
        return False
    return probe.returncode == 128 and b"not a git repository" in probe.stderr


def writing_diff_result(project: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Accept a diff only when every Git diagnostic is a Markdown hard break."""
    if result["returncode"] != 2 or result.get("stderr") or not is_writing_workspace(project):
        return result
    lines = result.get("stdout", "").removesuffix("\n").split("\n")
    if len(lines) % 2 or not all(
        re.fullmatch(r".+\.md:[0-9]+: trailing whitespace\.", header)
        and re.fullmatch(r"\+.*\S  ", addition)
        for header, addition in zip(lines[::2], lines[1::2])
    ):
        return result
    return {**result, "returncode": 0, "git_returncode": 2,
            "review_note": "Markdown hard breaks in writing workspace"}


def is_git_status_review_only(project: Path, git_status: dict[str, Any]) -> bool:
    if git_status.get("returncode") == 0:
        return False
    # A real repo whose status command failed is still a genuine failure; only
    # the absence of a repository makes git evidence structurally unavailable.
    return is_non_git_workspace(project)


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

