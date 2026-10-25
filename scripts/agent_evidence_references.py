"""Bounded local evidence pointers; freshness never grants action authority."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import unicodedata
from typing import Any

from agent_continuation_fields import (
    SECRET_RES, SLUG_RE, enum_value, failure, items, prose, sha256_value, slug,
)

MAX_EVIDENCE_REFS = 4
EVIDENCE_REF_STATUSES = ("unverified", "verified", "contradicted")
MAX_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
_FIELDS = ("id", "path", "sha256", "status", "summary")


def _absolute_path(value: Any, pointer: str, failures: list) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        failures.append(failure("invalid_path", pointer))
        return
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        failures.append(failure("invalid_unicode", pointer))
        return
    if (
        not value.startswith("/")
        or value != unicodedata.normalize("NFC", value)
        or "\\" in value or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/")[1:])
        or any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value)
        or any(pattern.search(value) for pattern in SECRET_RES)
    ):
        failures.append(failure("invalid_path", pointer))


def validate_evidence_refs(value: Any, pointer: str, failures: list) -> None:
    """Validate closed records without reading files or echoing rejected values."""
    seen: set[str] = set()

    def check(record: Any, current: str) -> None:
        if not isinstance(record, dict):
            failures.append(failure("invalid_type", current))
            return
        # Unknown names themselves may contain sensitive text: do not echo them.
        if any(key not in _FIELDS for key in record):
            failures.append(failure("unknown_field", current))
        for key in _FIELDS:
            if key not in record:
                failures.append(failure("missing_field", f"{current}/{key}"))
        identifier = record.get("id")
        previous_failures = len(failures)
        slug(identifier, f"{current}/id", failures, 40)
        if len(failures) == previous_failures and not SLUG_RE.fullmatch(identifier):
            failures.append(failure("invalid_slug", f"{current}/id"))
        if isinstance(identifier, str):
            if identifier in seen:
                failures.append(failure("duplicate_id", f"{current}/id"))
            seen.add(identifier)
        _absolute_path(record.get("path"), f"{current}/path", failures)
        sha256_value(record.get("sha256"), f"{current}/sha256", failures)
        enum_value(record.get("status"), EVIDENCE_REF_STATUSES, f"{current}/status", failures)
        prose(record.get("summary"), f"{current}/summary", failures, 160)

    items(value, pointer, failures, MAX_EVIDENCE_REFS, check)


def _open_file(path: str) -> int:
    """Walk only the registered absolute path, refusing every symlink component."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = os.open("/", directory_flags)
    try:
        components = path.split("/")[1:]
        for component in components[:-1]:
            next_directory = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        return os.open(
            components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
    finally:
        os.close(directory)


def _signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _freshness(record: dict) -> str:
    errors: list = []
    _absolute_path(record.get("path"), "", errors)
    sha256_value(record.get("sha256"), "", errors)
    if errors or not (
        os.name == "posix" and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd
    ):
        return "unsafe"
    descriptor = None
    try:
        descriptor = _open_file(record["path"])
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return "unsafe"
        if before.st_size > MAX_EVIDENCE_FILE_BYTES:
            return "oversized"
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, MAX_EVIDENCE_FILE_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_EVIDENCE_FILE_BYTES:
                return "oversized"
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _signature(before) != _signature(after) or total != after.st_size:
            return "changed"
        # Rewalk to detect replacement of the registered name or its parents.
        current = _open_file(record["path"])
        try:
            if _signature(os.fstat(current)) != _signature(after):
                return "changed"
        finally:
            os.close(current)
        return "match" if digest.hexdigest() == record["sha256"] else "changed"
    except OSError as error:
        if error.errno == errno.ENOENT:
            return "missing"
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            return "unsafe"
        return "unreadable"
    finally:
        if descriptor is not None:
            os.close(descriptor)


def inspect_evidence_refs(refs: list[dict], *, check_files: bool = False) -> list[dict]:
    """Add freshness to validated records; default mode performs no file I/O.

    File checks are bounded snapshots, not a guarantee that files remain intact
    afterward. A matching digest or verified claim never authorizes an action.
    """
    return [dict(record, freshness=_freshness(record) if check_files else "unchecked") for record in refs]
