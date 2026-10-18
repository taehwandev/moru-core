"""Stable, bounded input identities for one explicit loop-owned file scope.

Owner: loop input capture. Allowed imports: standard library and bounded Git.
Forbidden: authority, lifecycle/ledger writes, source/Git mutations and checks.
Callers/tests: LoopRun and loop checker; test_agent_loop_inputs.
Verification: the focused input scope, drift and restoration scenarios.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from support.bounded_git import stream_stall_guard


_MAX_FILES = 5_000
_MAX_BYTES = 256 * 1024 * 1024
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_GIT_BYTES = 16 * 1024 * 1024
_FIELDS = {"head", "index", "outside", "owned", "verifiers"}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def _git(project: Path, *args: str) -> bytes:
    command = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args)
    with subprocess.Popen(
        ["git", *command], cwd=project, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ) as process:
        try:
            with stream_stall_guard(process, command, timeout=10):
                assert process.stdout is not None
                chunks, size = [], 0
                while chunk := process.stdout.read(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_GIT_BYTES:
                        raise ValueError("loop Git input exceeds output limit")
                    chunks.append(chunk)
                if process.wait() != 0:
                    raise ValueError("loop Git inputs unavailable")
                return b"".join(chunks)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise


def _paths(values: list[str], label: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError(f"{label} must contain 1..64 explicit files")
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError(f"{label} requires bounded relative file paths")
        path = PurePosixPath(value)
        if (str(path) != value or path.is_absolute() or ".." in path.parts
                or not path.parts or {".git", ".moru"}.intersection(path.parts)
                or any(character in value for character in "*?[]\\\0")):
            raise ValueError(f"{label} requires normalized literal project paths")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} contains duplicate paths")
    return tuple(sorted(values))


@contextmanager
def _parent(project: Path, relative: str):
    """Walk with directory descriptors so a replaced parent cannot escape root."""
    descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(relative).parts[:-1]:
            try:
                nested = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                yield None
                return
            except OSError as error:
                raise ValueError("loop input parent must be a real directory") from error
            os.close(descriptor)
            descriptor = nested
        yield descriptor
    finally:
        os.close(descriptor)


def _metadata(descriptor: int | None, name: str):
    if descriptor is None:
        return None
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(project: Path, relative: str, budget: dict, *, required: bool = False,
              allow_symlink: bool = False, validate_only: bool = False) -> dict:
    with _parent(project, relative) as parent:
        name = PurePosixPath(relative).name
        before = _metadata(parent, name)
        if before is None:
            if required:
                raise ValueError("loop verifier file is missing")
            return {"missing": True}
        if stat.S_ISLNK(before.st_mode) and allow_symlink:
            return {"symlink": os.readlink(name, dir_fd=parent)}
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("loop inputs must be regular files without symlinks")
        if validate_only:
            return {}
        budget["files"] += 1
        if budget["files"] > _MAX_FILES or before.st_size > _MAX_FILE_BYTES:
            raise ValueError("loop file input exceeds capture limit")
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent,
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                raise ValueError("loop input changed during capture")
            digest, size = hashlib.sha256(), 0
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                budget["bytes"] += len(chunk)
                if size > _MAX_FILE_BYTES or budget["bytes"] > _MAX_BYTES:
                    raise ValueError("loop file input exceeds capture byte limit")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        current = _metadata(parent, name)
        if current is None or any(
            getattr(before, field) != getattr(result, field)
            for result in (opened, after, current) for field in stable
        ):
            raise ValueError("loop input changed during capture")
        return {"mode": stat.S_IMODE(before.st_mode), "sha256": digest.hexdigest()}


class LoopInputs:
    """Freeze exact input scopes without retaining contents or mutable metadata."""

    def __init__(self, project: Path, owned: list[str], verifiers: list[str]):
        if project.is_symlink():
            raise ValueError("loop project must not be a symlink")
        self.project = project.resolve(strict=True)
        self.owned = _paths(owned, "owned")
        self.verifiers = _paths(verifiers, "verifiers")
        if set(self.owned).intersection(self.verifiers):
            raise ValueError("owned and verifier files must be disjoint")
        root = os.fsdecode(_git(self.project, "rev-parse", "--show-toplevel")).rstrip("\n")
        if Path(root).resolve() != self.project:
            raise ValueError("loop project must be the Git worktree root")
        for relative in self.owned + self.verifiers:
            _identity(self.project, relative, {}, required=relative in self.verifiers,
                      validate_only=True)

    def capture(self) -> dict:
        """Require two equal content scans; a racing input never becomes evidence."""
        try:
            first = self._capture()
            if first != self._capture():
                raise ValueError("loop inputs changed during capture")
            return first
        except OSError as error:
            raise ValueError("loop inputs unavailable or changed during capture") from error

    def _capture(self) -> dict:
        budget = {"files": 0, "bytes": 0}
        head = _git(self.project, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
        index = hashlib.sha256(_git(self.project, "ls-files", "--stage", "-v", "-z")).hexdigest()
        names = {os.fsdecode(name) for name in _git(
            self.project, "ls-files", "--cached", "--others", "--exclude-standard", "-z",
        ).split(b"\0") if name}
        if len(names) > _MAX_FILES:
            raise ValueError("loop input exceeds file count limit")
        owned = {name: _identity(self.project, name, budget) for name in self.owned}
        verifiers = {name: _identity(self.project, name, budget, required=True)
                     for name in self.verifiers}
        outside = {name: _identity(self.project, name, budget, allow_symlink=True)
                   for name in sorted(names - set(self.owned))}
        return {"head": head, "index": index, "outside": _digest(outside),
                "owned": owned, "verifiers": verifiers}

    @staticmethod
    def assert_scope(current: dict, accepted: dict) -> None:
        if (not isinstance(current, dict) or not isinstance(accepted, dict)
                or set(current) != _FIELDS or set(accepted) != _FIELDS
                or not isinstance(current["owned"], dict)
                or not isinstance(accepted["owned"], dict)
                or set(current["owned"]) != set(accepted["owned"])):
            raise ValueError("invalid loop input snapshot")
        for field in ("head", "index", "outside", "verifiers"):
            if current[field] != accepted[field]:
                raise ValueError(f"loop {field} inputs drifted outside owned scope")

    @staticmethod
    def assert_restored(current: dict, accepted: dict) -> None:
        LoopInputs.assert_scope(current, accepted)
        if current != accepted:
            raise ValueError("restore rejected owned files to the accepted checkpoint")
