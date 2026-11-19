"""Read-only native transcript facts; original delivery code owns every write.

Owner: NativeDocTranscript. Allowed: stdlib/NativeProbe. Forbidden: transcript
parsing, marker/evidence writes, retries or provider calls. Callers/tests:
agent_required_doc_delivery; native source/stream/fallback and delivery tests.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from support.native_probe_transport import NativeProbe


def _integer(value):
    return type(value) is int and -(1 << 63) <= value < 1 << 63


def _value(result):
    return result["value"] if type(result) is dict and set(result) == {"value"} else None


def agy_delivery_request(*, payload=None, raw=None) -> tuple[str, list[str], str] | None:
    try:
        if raw is not None:
            if len(raw) > 128 * 1024:
                return None
            args = {"raw": raw}
        else:
            if type(payload) is not dict or any(type(key) is not str for key in payload):
                return None
            fields = {key: payload.get(key) for key in ("conversationId", "workspacePaths", "transcriptPath")}
            workspaces = fields["workspacePaths"]
            if workspaces is not None and (type(workspaces) is not list
                                           or any(type(path) is not str for path in workspaces)):
                return None
            if any(fields[key] is not None and type(fields[key]) is not str
                   for key in ("conversationId", "transcriptPath")):
                return None
            args = {"payload": fields}
        value = _value(NativeProbe.request("--doc-transcript-probe", "agy-delivery-request", args))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is list and len(value) == 3:
        conversation, workspaces, transcript = value
        if (type(conversation) is str and type(transcript) is str
                and type(workspaces) is list and all(type(path) is str for path in workspaces)):
            return conversation, workspaces, transcript
    return None


def nearest_registry_project(edited: Path) -> tuple[Path, ...] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "nearest-registry-project",
                                           {"path": str(edited)}))
    except (OSError, ValueError, RuntimeError):
        return None
    if value == []:
        return ()
    if type(value) is list and len(value) == 1 and type(value[0]) is str:
        project = Path(value[0])
        if project == edited or project in edited.parents:
            return (project,)
    return None


def read_delivery_manifest(path: Path) -> tuple[Path, list[str]] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "read-delivery-manifest",
                                           {"path": str(path)}))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is list and len(value) == 2 and type(value[0]) is str:
        docs = value[1]
        if type(docs) is list and all(type(doc) is str for doc in docs) and len(set(docs)) == len(docs):
            return Path(value[0]), docs
    return None


class NativeDocTranscript:
    @staticmethod
    def write_marker(marker: Path, delivered: list, offset: int, redeliveries: int) -> bool:
        if not NativeProbe.available():
            return False
        result = NativeProbe.request("--doc-transcript-probe", "write-marker", {
            "marker": str(marker), "delivered": delivered, "offset": offset,
            "redeliveries": redeliveries, "temporary": uuid4().hex,
        })
        if result is None:
            return False
        if result == {"value": {"stored": True}} and type(result["value"]["stored"]) is bool:
            return True
        raise OSError("native delivery marker could not be stored")

    @staticmethod
    def delivery_plan(marker: Path, transcript: Path, limit: int) -> dict | None:
        try:
            result = NativeProbe.request("--doc-transcript-probe", "delivery-plan",
                                         {"marker": str(marker), "path": str(transcript), "limit": limit})
        except (OSError, ValueError, RuntimeError):
            return None
        state = _value(result)
        if type(state) is not dict:
            return None
        if state == {"action": "skip"}:
            return state
        if type(state.get("offset")) is not int or state["offset"] < 0:
            return None
        if state.get("action") == "upgrade" and set(state) == {"action", "offset", "delivered"}:
            delivered = state["delivered"]
            if type(delivered) is list and all(type(doc) is str for doc in delivered):
                return state
        if state.get("action") == "deliver" and set(state) == {"action", "offset", "had_previous", "redeliveries"}:
            if type(state["had_previous"]) is bool and _integer(state["redeliveries"]):
                return state
        return None

    @staticmethod
    def read_docs(rules: Path, docs: list[str]) -> dict[str, str] | None:
        try:
            result = NativeProbe.request("--doc-transcript-probe", "read-docs",
                                         {"rules": str(rules), "docs": docs})
        except (OSError, ValueError, RuntimeError):
            return None
        texts = _value(result)
        if type(texts) is dict and all(name in docs and type(text) is str for name, text in texts.items()):
            return texts
        return None

    @staticmethod
    def render(texts, pending, rules, inline_limit, total_limit):
        if rules is not None and type(rules) is not type(Path()):
            return None
        try:
            if not NativeProbe.available():
                return None
            docs = [
                {"name": doc, "text": texts[doc], "path": str(rules / doc if rules else doc)}
                for doc in pending if doc in texts
            ]
            result = NativeProbe.request("--doc-transcript-probe", "render", {
                "docs": docs, "inline_limit": inline_limit, "total_limit": total_limit,
            })
        except (OSError, ValueError, RuntimeError):
            return None
        text = _value(result)
        return text if type(text) is str else None

    @staticmethod
    def agy_covered(path: Path, rules: Path, docs: list[str]) -> set[str] | None:
        try:
            result = NativeProbe.request("--doc-transcript-probe", "agy-covered",
                                         {"path": str(path), "rules": str(rules), "docs": docs})
        except (OSError, ValueError, RuntimeError):
            return None
        value = _value(result)
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
        value = _value(result)
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
