"""Read-only native transcript facts; original delivery code owns every write.

Owner: NativeDocTranscript. Allowed: stdlib/NativeProbe. Forbidden: transcript
parsing, marker/evidence writes, retries or provider calls. Callers/tests:
agent_required_doc_delivery; native source/stream/fallback and delivery tests.
"""
from __future__ import annotations

from pathlib import Path

from support.native_probe_transport import NativeProbe


def _integer(value):
    return type(value) is int and -(1 << 63) <= value < 1 << 63


class NativeDocTranscript:
    @staticmethod
    def agy_covered(path: Path, rules: Path, docs: list[str]) -> set[str] | None:
        try:
            result = NativeProbe.request("--doc-transcript-probe", "agy-covered",
                                         {"path": str(path), "rules": str(rules), "docs": docs})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != {"value"}:
            return None
        value = result["value"]
        if type(value) is not list or any(type(doc) is not str or doc not in docs for doc in value):
            return None
        return set(value)

    @staticmethod
    def _query(operation, path, fields, expected):
        if type(path) is not type(Path()):
            return None
        try:
            result = NativeProbe.request("--doc-transcript-probe", operation,
                                         {"path": str(path), **fields})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != {"value"}:
            return None
        value = result["value"]
        if type(value) is not expected:
            return None
        return value if expected is bool or 0 <= value < 1 << 63 else None

    @staticmethod
    def compacted(path):
        return NativeDocTranscript._query("compacted", path, {}, bool)

    @staticmethod
    def aligned(path, fallback):
        if not _integer(fallback):
            return None
        return NativeDocTranscript._query("aligned", path, {"fallback": fallback}, int)

    @staticmethod
    def due(state, path, limit):
        if type(state) is not dict or not _integer(limit):
            return None
        offset, count = state.get("transcript_bytes"), state.get("redeliveries", 0)
        if not _integer(offset) or not _integer(count):
            return None
        return NativeDocTranscript._query("due", path,
            {"offset": offset, "redeliveries": count, "limit": limit}, bool)
