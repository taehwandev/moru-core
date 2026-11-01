"""Repository identity shared by read-only cards and project memory.

Owner: repository-key lookup. Allowed: stdlib and the existing per-call Git memo.
Forbidden: memory persistence, evidence capture and lifecycle imports.
Callers/tests: project memory and work cards; test_agent_repository_key.
Verification: linked-worktree identity, Git failure/timeout and scope memo parity.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from support.git_read_scope import stable_read


def repository_key(project: Path) -> str:
    """Name one repository the same way from every one of its worktrees."""
    return stable_read(("repository-key", str(project.resolve())), lambda: _repository_key(project))


def _repository_key(project: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        identity = result.stdout.strip() if result.returncode == 0 else str(project.resolve())
    except (OSError, subprocess.TimeoutExpired):
        identity = str(project.resolve())
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
