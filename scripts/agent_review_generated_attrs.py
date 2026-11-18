"""Recognize paths a project marks as generated with the standard `linguist-generated` attribute.

Archived model output and other generated files are kept byte-for-byte, so the
human-authored size gates cannot apply to them. Only an explicit attribute in a
committed `.gitattributes` exempts a path; nothing is inferred from names.
"""
from __future__ import annotations

import fnmatch
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=64)
def _declares_generated(project: Path) -> bool:
    attributes = project / ".gitattributes"
    try:
        return "linguist-generated" in attributes.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


@lru_cache(maxsize=4096)
def linguist_generated_path(project: Path, path: Path) -> bool:
    if not _declares_generated(project):
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "check-attr", "linguist-generated", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0:
        return result.stdout.rsplit(":", 1)[-1].strip() in {"set", "true"}
    # Commit-range reviews may read an exported snapshot without .git.
    return _matches_attributes_file(project, path)


def _matches_attributes_file(project: Path, path: Path) -> bool:
    try:
        lines = (project / ".gitattributes").read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    target = path.as_posix()
    marked = False
    for line in lines:
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        pattern, attrs = fields[0], fields[1:]
        if "linguist-generated" in attrs or "linguist-generated=true" in attrs:
            setting = True
        elif "-linguist-generated" in attrs or "linguist-generated=false" in attrs:
            setting = False
        else:
            continue
        candidate = target if "/" in pattern.rstrip("/") else path.name
        if fnmatch.fnmatchcase(candidate, pattern.lstrip("/")):
            marked = setting  # later lines win, as in git
    return marked
