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


def _reuse_history(operation, fields) -> list[str] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", operation, fields))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is list and all(type(item) is str for item in value):
        return value
    return None


def reuse_run_ids(root: Path, current: str, limit: int) -> list[str] | None:
    return _reuse_history("reuse-run-ids", {"path": str(root), "current": current, "limit": limit})


def reuse_current(path: Path, *, project_docs: bool):
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "reuse-current", {
            "path": str(path), "project_docs": project_docs,
        }))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is not list or len(value) != 3:
        return None
    names, rows, binding = value
    if (type(names) is not list or any(type(name) is not str for name in names)
            or len(set(names)) != len(names) or (project_docs and names)
            or type(rows) is not list
            or type(binding) is not list or len(binding) != 4
            or any(type(part) is not str or not part for part in binding)):
        return None
    project, run, runtime, session = binding
    root = Path(project)
    if (not root.is_absolute() or root / ".moru" / "runs" / run / "preflight.json" != path
            or len(run) != 32 or any(ch not in "0123456789abcdef" for ch in run)):
        return None
    records = {}
    for row in rows:
        if type(row) is not list or len(row) != 3:
            return None
        name, digest, size = row
        if type(name) is not str or type(digest) is not str or type(size) is not int or size < 0:
            return None
        records[name] = (name, digest, size)
    return names, records, (root, run, (runtime, session))


def reuse_matches(
    root: Path, ids: list[str], session: tuple[str, str], wanted: list[tuple[str, str, int]],
    *, project_docs: bool,
) -> tuple[int, set[tuple[str, str, int]]] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "reuse-matches", {
            "path": str(root), "ids": ids, "session": session, "wanted": wanted,
            "project_docs": project_docs,
        }))
    except (OSError, ValueError, RuntimeError):
        return None
    if value == []:
        return len(ids), set()
    if type(value) is list and len(value) == 2:
        consumed, indices = value
        if (type(consumed) is int and 1 <= consumed <= len(ids)
                and type(indices) is list and indices
                and all(type(i) is int and 0 <= i < len(wanted) for i in indices)):
            return consumed, {wanted[i] for i in indices}
    return None


def reuse_plan(root, current, session, wanted, covered, takeaways, *,
               project_docs, require_takeaway, limits):
    covered_indices = [i for i, record in enumerate(wanted) if record in covered]
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "reuse-plan", {
            "path": str(root), "current": current, "session": session, "wanted": wanted,
            "covered": covered_indices, "takeaways": takeaways, "project_docs": project_docs,
            "require_takeaway": require_takeaway, "limits": limits,
        }))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is not list or len(value) != 2:
        return None
    indices, added = value
    if (type(indices) is not list or type(added) is not list
            or any(type(i) is not int or not 0 <= i < len(wanted) for i in indices)
            or len(set(indices)) != len(indices)
            or any(wanted[i] in covered for i in indices)
            or len(added) > len(indices)
            or len(added) + len(takeaways) > limits[1]
            or any(type(text) is not str or not 0 < len(text) <= 2 * limits[2] + 3 for text in added)):
        return None
    return {wanted[i] for i in indices}, added


def rank_reuse_roots(candidates: list[Path], excluded: list[Path], limit: int) -> list[Path] | None:
    try:
        if not NativeProbe.available():
            return None
    except (OSError, ValueError, RuntimeError):
        return None
    resolved = []
    for candidate in candidates:
        try:
            # Preserve pathlib's spelling and symlink behavior on the host.
            resolved.append(str(candidate.resolve()))
        except OSError:
            continue
    value = _reuse_history("rank-reuse-roots", {
        "candidates": resolved, "excluded": [str(path) for path in excluded],
        "limit": limit,
    })
    if value is None or len(value) > limit:
        return None
    roots = [Path(path) for path in value]
    return roots if all(root.is_absolute() for root in roots) else None


def discover_reuse_roots(
    path: Path, excluded: list[Path], limit: int, *, phase: str,
) -> tuple[Path | None, list[Path]] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "discover-reuse-roots", {
            "path": str(path), "phase": phase, "excluded": [str(root) for root in excluded],
            "limit": limit,
        }))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is not list or len(value) != 2:
        return None
    workspace, roots = value
    if ((workspace is not None and (phase != "worktrees" or type(workspace) is not str))
            or type(roots) is not list or len(roots) > limit
            or any(type(root) is not str for root in roots)):
        return None
    workspace = Path(workspace) if workspace is not None else None
    candidates = [Path(root) for root in roots]
    if ((workspace is not None and not workspace.is_absolute())
            or any(not root.is_absolute() or root in excluded for root in candidates)):
        return None
    return workspace, candidates


def reuse_credit(prior: Path, takeaways: list[str], slots: int, chars: int) -> tuple[bool, str | None] | None:
    try:
        value = _value(NativeProbe.request("--doc-transcript-probe", "reuse-credit", {
            "path": str(prior), "takeaways": takeaways, "slots": slots, "chars": chars,
        }))
    except (OSError, ValueError, RuntimeError):
        return None
    if type(value) is list and len(value) == 2 and type(value[0]) is bool:
        credited, added = value
        if added is None or (credited and type(added) is str and added):
            return credited, added
    return None


def agy_redelivery(evidence: Path, transcript: Path, limit: int, inline_limit: int, total_limit: int) -> str | None:
    return _agy_delivery("agy-redelivery", {
        "evidence": str(evidence), "transcript": str(transcript), "limit": limit,
        "inline_limit": inline_limit, "total_limit": total_limit,
    })


def agy_prepared_delivery(evidence, transcript, rules, docs, plan, inline_limit, total_limit) -> str | None:
    return _agy_delivery("agy-prepared-delivery", {
        "evidence": str(evidence), "transcript": str(transcript), "rules": str(rules),
        "docs": docs, "plan": plan, "inline_limit": inline_limit, "total_limit": total_limit,
    })


def _agy_delivery(operation, payload) -> str | None:
    if not NativeProbe.available():
        return None
    result = NativeProbe.request("--doc-transcript-probe", operation, {**payload, "temporary": uuid4().hex})
    if result is None:
        return None
    value = _value(result)
    if type(value) is dict and set(value) == {"text"} and type(value["text"]) is str:
        return value["text"]
    raise OSError("native AGY document marker could not be stored or confirmed")


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
