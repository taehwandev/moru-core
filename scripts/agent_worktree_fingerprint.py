"""Bounded Git worktree fingerprints for execution-capsule bindings."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from agent_worktree_scan import (
    UntrackedBudget,
    WorktreeFingerprintLimitExceeded,
    hash_component,
    hash_file_component,
    hash_git_component,
    visit_git_null_records,
)
from support.bounded_git import run_git
from support.native_probe_transport import NativeProbe


MAX_UNTRACKED_FILES = 5_000
MAX_STAGED_INITIAL_FILES = 10_000
MAX_UNTRACKED_BYTES = 256 * 1024 * 1024
MAX_CAPTURE_ATTEMPTS = 2


class WorktreeSnapshot(NamedTuple):
    """Two digests that always travel together, and never separately change.

    A frozen dataclass said the same thing, but `dataclasses` pulls `inspect`,
    and this module sits under the run registry that the pre-tool gate loads
    on every single tool call -- about 3 ms of import for two immutable
    strings. `typing` is already imported here, so this costs nothing new.
    """

    fingerprint: str
    signature: str


def git_output(path: Path, *args: str) -> str:
    completed = run_git(
        ["git", *args],
        cwd=path,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        if args == ("rev-parse", "--verify", "HEAD") and _unborn_head(path):
            return "unborn\n"
        raise RuntimeError(
            f"cannot capture git state for execution capsule: git {args[0]} failed"
        )
    return completed.stdout.decode("utf-8")


def _unborn_head(path: Path) -> bool:
    """Accept only a symbolic HEAD whose branch ref does not exist yet."""
    symbolic = run_git(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=path, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if symbolic.returncode != 0:
        return False
    reference = symbolic.stdout.decode("utf-8").strip()
    if not reference.startswith("refs/heads/"):
        return False
    exists = run_git(
        ["git", "show-ref", "--verify", "--quiet", reference], cwd=path,
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return exists.returncode == 1


def _normalize_pathspecs(paths: Sequence[str] | None) -> tuple[str, ...] | None:
    if not paths:
        return None
    normalized = tuple(item for item in (str(p).strip() for p in paths) if item)
    return normalized or None


def _path_in_scope(relative_bytes: bytes, scoped: tuple[str, ...]) -> bool:
    """Whether a worktree-relative path falls inside one of the pathspec entries."""
    rel = os.fsdecode(relative_bytes).replace("\\", "/").lstrip("./")
    for raw in scoped:
        norm = raw.replace("\\", "/").strip().lstrip("./").rstrip("/")
        if not norm or norm == ".":
            return True
        if rel == norm or rel.startswith(norm + "/"):
            return True
    return False


def capture_worktree_state(
    path: Path,
    *,
    paths: Sequence[str] | None = None,
) -> WorktreeSnapshot:
    """Capture the authoritative fingerprint and its cheap invalidation signature."""

    scoped = _normalize_pathspecs(paths)
    for _attempt in range(MAX_CAPTURE_ATTEMPTS):
        snapshot = _capture_worktree_state_once(path, paths=scoped)
        if snapshot.signature == worktree_signature(path, paths=scoped):
            return snapshot
    raise RuntimeError("worktree changed during execution-capsule fingerprint capture")


def _capture_worktree_state_once(
    path: Path,
    *,
    paths: Sequence[str] | None = None,
) -> WorktreeSnapshot:
    """Capture one bounded snapshot; the public wrapper verifies its stability."""

    scoped = _normalize_pathspecs(paths)
    native = _native_worktree(path, strong=True, paths=scoped)
    if native is not None and _sha256(native.get("fingerprint")) and _sha256(native.get("signature")):
        return WorktreeSnapshot(native["fingerprint"], native["signature"])
    fingerprint = hashlib.sha256()
    signature = hashlib.sha256()
    budget = _new_budget()
    _capture_status(path, fingerprint, signature, budget, paths=scoped)
    # Initial additions are content-hashed above. With no commit, diff against
    # the index for partial staging instead of asking Git for nonexistent HEAD.
    # Always diff the full worktree so out-of-scope tracked edits still invalidate
    # pathspec review freshness; `paths` scopes only the untracked size budget.
    base = () if git_output(path, "rev-parse", "--verify", "HEAD").strip() == "unborn" else ("HEAD",)
    hash_git_component(
        fingerprint,
        b"working-tree",
        path,
        "diff",
        *base,
        "--binary",
        "--no-renames",
        "--diff-filter=a",
        "--no-ext-diff",
        "--no-textconv",
    )
    return WorktreeSnapshot(
        fingerprint=fingerprint.hexdigest(),
        signature=signature.hexdigest(),
    )


def worktree_fingerprint(path: Path, *, paths: Sequence[str] | None = None) -> str:
    """Hash tracked and untracked state without persisting paths or contents."""

    return capture_worktree_state(path, paths=paths).fingerprint


def worktree_fingerprint_excluding_path(path: Path, excluded_relative: str) -> str:
    """Compute worktree_fingerprint as if excluded_relative were untouched at HEAD."""

    if type(excluded_relative) is str:
        native = _native_worktree(path, strong=True, excluded=excluded_relative)
        if native is not None and _sha256(native.get("fingerprint")):
            return native["fingerprint"]
    fingerprint = hashlib.sha256()
    signature = hashlib.sha256()
    budget = _new_budget()
    _capture_status(
        path,
        fingerprint,
        signature,
        budget,
        excluded_path=os.fsencode(excluded_relative),
    )
    base = () if git_output(path, "rev-parse", "--verify", "HEAD").strip() == "unborn" else ("HEAD",)
    hash_git_component(
        fingerprint,
        b"working-tree",
        path,
        "diff",
        *base,
        "--binary",
        "--no-renames",
        "--diff-filter=a",
        "--no-ext-diff",
        "--no-textconv",
        "--",
        ".",
        f":(exclude){excluded_relative}",
    )
    return fingerprint.hexdigest()


def worktree_signature(path: Path, *, paths: Sequence[str] | None = None) -> str:
    """Return a content-free invalidation filter for a prior strong fingerprint.

    The signature is never an identity proof on its own. Callers may reuse a
    previously captured strong fingerprint only while this signature and HEAD
    both match that prior record.
    """

    scoped = _normalize_pathspecs(paths)
    native = _native_worktree(path, paths=scoped)
    observed = native.get("signature") if native is not None else None
    if _sha256(observed):
        return observed
    signature = hashlib.sha256()
    _capture_status(
        path,
        fingerprint=None,
        signature=signature,
        budget=_new_budget(),
        paths=scoped,
    )
    return signature.hexdigest()


def _native_worktree(
    path: Path,
    *,
    strong: bool = False,
    excluded: str | None = None,
    paths: Sequence[str] | None = None,
) -> dict | None:
    payload: dict[str, Any] = {
        "path": str(path.absolute()),
        "max_files": MAX_UNTRACKED_FILES,
        "max_bytes": MAX_UNTRACKED_BYTES,
        "strong": strong,
        "excluded": excluded,
    }
    if paths:
        payload["paths"] = list(paths)
    result = NativeProbe.request("--completion-probe", "capsule-worktree-signature", payload)
    if paths and (result is None or result.get("scoped") is not True):
        return None
    return result


def _sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _capture_status(
    path: Path,
    fingerprint: Any | None,
    signature: Any,
    budget: UntrackedBudget,
    *,
    excluded_path: bytes | None = None,
    paths: Sequence[str] | None = None,
) -> None:
    expecting_original_path = False
    original_path_is_deleted = False
    entries: list[tuple[bytes, bytes, bool, bytes]] = []

    def visit(record: bytes) -> None:
        nonlocal expecting_original_path, original_path_is_deleted
        if expecting_original_path:
            expecting_original_path = False
            if original_path_is_deleted:
                entries.append((b"1", record, False, b""))
            original_path_is_deleted = False
            return

        kind, relative_bytes, renamed = _status_path(record)
        expecting_original_path = renamed
        original_path_is_deleted = renamed and _rename_removes_original(record)
        if relative_bytes is None or (excluded_path is not None and relative_bytes == excluded_path):
            return
        if kind in {b"1", b"2"} and _dirty_submodule(record):
            raise RuntimeError(
                "dirty submodule state cannot be bound to an execution capsule"
            )
        xy = _status_xy(record)
        added_like = kind == b"?" or kind == b"2" or b"A" in xy
        entries.append((kind, relative_bytes, added_like, record))

    # Always scan the whole worktree so out-of-scope tracked and untracked edits
    # stay bound to the freshness signature and fingerprint; `paths` scopes only
    # the untracked file/byte budget so large out-of-scope renders do not block.
    visit_git_null_records(
        path,
        ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
        visit,
    )

    scoped = _normalize_pathspecs(paths)
    if (
        len(entries) > budget.max_files
        and all(_status_xy(record) == b"A." for _, _, _, record in entries)
        and _unborn_head(path)
    ):
        budget.max_files = MAX_STAGED_INITIAL_FILES

    for relative_bytes in sorted(
        {relative for _kind, relative, _added, _record in entries}
    ):
        hash_component(signature, b"status-path", relative_bytes)
        if fingerprint is not None:
            hash_component(fingerprint, b"status-path", relative_bytes)

    for kind, relative_bytes, added_like, record in sorted(
        entries,
        key=lambda entry: entry[1],
    ):
        xy = _status_xy(record)
        if len(xy) == 2 and xy[0:1] != b"." and xy[1:2] != b".":
            hash_component(signature, b"partial-status", record)
            if fingerprint is not None:
                hash_component(fingerprint, b"partial-status", record)
        candidate = path / Path(os.fsdecode(relative_bytes))
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            hash_component(signature, b"worktree-raced", relative_bytes)
            if fingerprint is not None:
                hash_component(fingerprint, b"worktree-raced", relative_bytes)
            continue
        _hash_metadata(signature, relative_bytes, metadata)
        if not added_like:
            continue
        if scoped is not None and kind == b"?" and not _path_in_scope(relative_bytes, scoped):
            if fingerprint is not None:
                _hash_metadata(fingerprint, relative_bytes, metadata)
            continue

        budget.add_file(metadata.st_size)
        if fingerprint is None:
            continue
        hash_component(fingerprint, b"added-path", relative_bytes)
        hash_component(
            fingerprint,
            b"added-mode",
            str(stat.S_IMODE(metadata.st_mode)).encode("ascii"),
        )
        if stat.S_ISLNK(metadata.st_mode):
            try:
                payload = os.fsencode(os.readlink(candidate))
            except FileNotFoundError:
                hash_component(fingerprint, b"added-raced", relative_bytes)
                continue
            budget.add_read_bytes(len(payload))
            hash_component(fingerprint, b"added-content", payload)
        elif stat.S_ISREG(metadata.st_mode):
            try:
                hash_file_component(
                    fingerprint,
                    b"added-content",
                    candidate,
                    budget,
                )
            except FileNotFoundError:
                hash_component(fingerprint, b"added-raced", relative_bytes)
        else:
            hash_component(
                fingerprint,
                b"added-content",
                str(metadata.st_mode).encode("ascii"),
            )


def _status_path(record: bytes) -> tuple[bytes, bytes | None, bool]:
    """Extract a porcelain-v2 path without decoding or retaining it."""

    kind = record[:1]
    if kind == b"?":
        return kind, record[2:], False
    if kind == b"1":
        fields = record.split(b" ", 8)
        return kind, fields[8] if len(fields) == 9 else None, False
    if kind == b"2":
        fields = record.split(b" ", 9)
        return kind, fields[9] if len(fields) == 10 else None, True
    if kind == b"u":
        fields = record.split(b" ", 10)
        return kind, fields[10] if len(fields) == 11 else None, False
    return kind, None, False


def _status_xy(record: bytes) -> bytes:
    """Return the porcelain-v2 XY field without retaining the full record."""

    kind = record[:1]
    if kind in {b"1", b"2", b"u"}:
        fields = record.split(b" ", 2)
        return fields[1] if len(fields) >= 2 else b""
    return b""


def _rename_removes_original(record: bytes) -> bool:
    """Return whether a porcelain-v2 kind-2 record represents a rename."""

    if record[:1] != b"2":
        return False
    fields = record.split(b" ", 9)
    return len(fields) == 10 and fields[8].startswith(b"R")


def _dirty_submodule(record: bytes) -> bool:
    fields = record.split(b" ", 3)
    return len(fields) >= 3 and fields[2].startswith(b"S") and fields[2] != b"S..."


def _new_budget() -> UntrackedBudget:
    return UntrackedBudget(MAX_UNTRACKED_FILES, MAX_UNTRACKED_BYTES)


def _hash_metadata(digest: Any, relative_bytes: bytes, metadata: os.stat_result) -> None:
    hash_component(digest, b"worktree-path", relative_bytes)
    values = (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_dev,
        metadata.st_ino,
    )
    hash_component(
        digest,
        b"worktree-metadata",
        b"\0".join(str(value).encode("ascii") for value in values),
    )
