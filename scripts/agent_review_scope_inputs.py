"""One input identity for scoped review, final attestation and local commit proof.

Owner: scoped source identity. Allowed imports: read-only Git and file hashing.
Forbidden: authority decisions, ledger writes and Git mutations. Callers:
review reuse, review attestation and publication admission; their scenario tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from agent_evidence_inputs import EvidenceInputs
from support.bounded_git import run_git


def _git(project: Path, *args: str) -> bytes:
    result = run_git(["git", *args], cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError("scoped review inputs unavailable")
    return result.stdout


def _names(output: bytes) -> list[str]:
    return sorted({os.fsdecode(name) for name in output.split(b"\0") if name})


def scoped_review_binding(project: Path, paths: list[str], *, include_index: bool = False) -> dict:
    if not paths:
        raise ValueError("scoped review requires explicit paths")
    options = ("--binary", "--no-ext-diff", "--no-textconv", "--no-renames")
    head = run_git(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=project,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if head.returncode not in (0, 1):
        raise ValueError("scoped review inputs unavailable")
    unborn = head.returncode == 1
    if unborn:
        # An unborn branch has no HEAD to diff against. Bind both the index
        # and working tree, and fail if HEAD is not a symbolic branch.
        _git(project, "symbolic-ref", "-q", "HEAD")
        changed = _names(_git(project, "diff", "--name-only", "-z", "--no-renames", "--", *paths))
        changed += _names(_git(project, "diff", "--cached", "--name-only", "-z", "--no-renames", "--", *paths))
        diff = _git(project, "diff", *options, "--", *paths)
        index_diff = _git(project, "diff", "--cached", *options, "--", *paths)
        diff = len(index_diff).to_bytes(8, "big") + index_diff + diff
    else:
        changed = _names(_git(project, "diff", "--name-only", "-z", "--no-renames", "HEAD", "--", *paths))
        diff = _git(project, "diff", *options, "HEAD", "--", *paths)
    untracked = _names(_git(project, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths))
    files = sorted(set(changed + _names(_git(
        project, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *paths))))
    branch = _git(project, "symbolic-ref", "--short", "HEAD").decode().strip() if unborn else _git(project, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    binding = {
        "branch": branch,
        "input_paths": files,
        "files_sha256": EvidenceInputs.capture(project, files) if files else hashlib.sha256(b"").hexdigest(),
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "changed_paths": sorted(set(changed + untracked)),
    }
    if branch == "HEAD":
        binding["head"] = _git(project, "rev-parse", "HEAD").decode().strip()
    if include_index:
        binding["index_sha256"] = hashlib.sha256(_git(
            project, "diff", "--cached", *options, *(() if unborn else ("HEAD",)), "--", *paths)).hexdigest()
    return binding


def scoped_review_digest(project: Path, paths: list[str], *, include_index: bool = False) -> str:
    binding = scoped_review_binding(project, paths, include_index=include_index)
    return hashlib.sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def reviewed_local_unit_matches(project: Path, paths: list[str], recorded: dict) -> bool:
    current = scoped_review_binding(project, paths, include_index=True)
    head = run_git(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=project,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if head.returncode not in (0, 1):
        raise ValueError("scoped review inputs unavailable")
    staged = _names(_git(project, "diff", "--cached", "--name-only", "-z", "--no-renames",
                         *(("HEAD",) if head.returncode == 0 else ()), "--"))
    if current == recorded:
        return bool(staged) and staged == recorded["changed_paths"]
    # After the exact reviewed unit was committed, retain its receipt for local
    # integration. No new staged unit or selected worktree edit is admitted.
    if staged or current["changed_paths"] or any(
        current.get(key) != recorded.get(key) for key in ("branch", "head")
    ):
        return False
    if EvidenceInputs.capture(project, recorded["input_paths"]) != recorded["files_sha256"]:
        return False
    parent = run_git(["git", "rev-parse", "--verify", "--quiet", "HEAD^"], cwd=project,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if parent.returncode == 1:
        return False
    if parent.returncode:
        raise ValueError("scoped review inputs unavailable")
    committed = _names(_git(project, "diff", "--name-only", "-z", "--no-renames", "HEAD^", "HEAD", "--"))
    patch = _git(project, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-renames",
                 "HEAD^", "HEAD", "--", *paths)
    return committed == recorded["changed_paths"] and hashlib.sha256(patch).hexdigest() == recorded["diff_sha256"]
