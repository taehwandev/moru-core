#!/usr/bin/env python3
"""Agent-written, source-attributed project memory for explicit recall.

A capture is active at once and available through explicit recall. Task start
does not scan or inject these records. Memory is reference, never authority:
the current request, repository rules and source evidence prevail. Wrong records
are corrected by replacing (`capture --replaces`) or retiring them, and each
record expires on its
`--review-on` date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json
from agent_evidence_inputs import EvidenceInputs
from support.global_state import global_state_dir, user_store_write_error
from support.git_read_scope import stable_read


SCHEMA_VERSION = 1
ID_RE = re.compile(r"[0-9a-f]{16}\Z")
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]{1,40}\Z")
STORE_NAME = "project-memory"
MAX_RECALL_ITEMS = 3
MAX_RECALL_CHARS = 1200
MAX_SOURCE_FILES = 4
MAX_PREVIOUS_CHARS = 160
MAX_HISTORY_ITEMS = 20
APPLICABILITY_FIELDS = ("applies_when", "not_when")
MAX_CONDITION_CHARS = 160
BLOB_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
PATH_RE = re.compile(r"[\w.-]+(?:/[\w.-]+)+|[\w-]+\.[a-zA-Z0-9]+")
STOP_WORDS = frozenset("a an and are be before for in is it of on or the to use with src tests scripts".split())
HANGUL_RE = re.compile(r"[가-힣]")
# Longest first, so `에서는` is removed whole rather than as `는`.
KOREAN_PARTICLES = ("에서는", "으로는", "에게서", "에서", "에게", "으로", "까지", "부터", "처럼",
                    "보다", "이랑", "은", "는", "이", "가", "을", "를", "의", "에", "도", "로",
                    "와", "과", "만", "랑")
# `pending` and `approved` are the former review states; both are recallable.
RECALLABLE_STATUSES = frozenset({"active", "pending", "approved"})
STATUSES = RECALLABLE_STATUSES | {"retired"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(record: dict[str, Any]) -> str:
    content = {key: record[key] for key in ("body", "source", "scope", "review_on")}
    for key in ("source_files", "analysis", *APPLICABILITY_FIELDS):
        if key in record:
            content[key] = record[key]
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _analysis_binding(question: str, context: str) -> dict[str, str] | None:
    if not question and not context:
        return None
    values = {"question": question, "context": context}
    if any(not isinstance(value, str) or not value.strip() or len(value) > 300
           or not value.isprintable() for value in values.values()):
        raise ValueError("analysis question and context must both be one line of 1–300 characters")
    # Preserve case, identifiers and negation. Semantic similarity is not identity.
    return {key: value.strip() for key, value in values.items()}


def _valid_analysis(record: dict[str, Any]) -> bool:
    binding = record.get("analysis")
    return (isinstance(binding, dict) and set(binding) == {"question", "context", "inputs"}
            and _analysis_binding(binding["question"], binding["context"]) ==
            {key: binding[key] for key in ("question", "context")}
            and isinstance(binding["inputs"], str)
            and re.fullmatch(r"[0-9a-f]{64}", binding["inputs"]) is not None
            and bool(record.get("source_files")))


def _valid_source_path(value: Any) -> bool:
    if not isinstance(value, str) or not (1 <= len(value) <= 300) or not value.isprintable():
        return False
    path = Path(value)
    return (not path.is_absolute() and path.as_posix() == value and "\\" not in value
            and not any(part in {"..", ".git"} for part in path.parts) and value != ".")


def _valid_source_files(files: Any) -> bool:
    return (isinstance(files, list) and 1 <= len(files) <= MAX_SOURCE_FILES
            and all(isinstance(item, dict) and set(item) == {"path", "blob"}
                    and _valid_source_path(item["path"]) and isinstance(item["blob"], str)
                    and BLOB_RE.fullmatch(item["blob"]) for item in files)
            and len({item["path"] for item in files}) == len(files))


def _source_blob(project: Path, path: str, *, tracked: bool = False) -> str:
    """Hash exact worktree bytes without filters or writing a Git object."""
    if not _valid_source_path(path):
        return ""
    root = project.resolve()
    candidate = root / path
    try:
        # Reject symlinks, including parent symlinks, before reading any bytes.
        if candidate.resolve(strict=True) != candidate or not candidate.is_file():
            return ""
        if tracked:
            checked = subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(root), "ls-files", "--error-unmatch", "--", path],
                capture_output=True, check=False, timeout=2,
            )
            if checked.returncode:
                return ""
        result = subprocess.run(
            ["git", "-C", str(root), "hash-object", "--no-filters", "--", path],
            capture_output=True, text=True, check=False, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    blob = result.stdout.strip()
    return blob if result.returncode == 0 and BLOB_RE.fullmatch(blob) else ""


def _source_status(project: Path, record: dict[str, Any],
                   blobs: dict[str, str] | None = None) -> dict[str, Any]:
    """`blobs` caches one recall's hashes, so records sharing a file hash it once."""
    files = record.get("source_files", [])
    if not files:
        return {}
    blobs = {} if blobs is None else blobs
    statuses = []
    for item in files:
        if item["path"] not in blobs:
            blobs[item["path"]] = _source_blob(project, item["path"])
        blob = blobs[item["path"]]
        statuses.append("unavailable" if not blob else "unchanged" if blob == item["blob"] else "changed")
    status = "changed" if "changed" in statuses else "unavailable" if "unavailable" in statuses else "unchanged"
    result: dict[str, Any] = {"source_status": status}
    if status != "unchanged":
        result["unverified_sources"] = [item["path"] for item, state in zip(files, statuses) if state != "unchanged"]
        result["warning"] = f"Source evidence {status} — verify before use"
    return result


def _particle_variants(words: set[str]) -> set[str]:
    """Add each Hangul word with a trailing particle removed (`프로필을` -> `프로필`).

    The original token stays; the stem must keep at least two syllables, so a
    two-syllable word such as `아이` is never cut down to one.
    """

    variants = set()
    for word in words:
        if HANGUL_RE.search(word):
            particle = next((p for p in KOREAN_PARTICLES
                             if word.endswith(p) and len(word) - len(p) >= 2), "")
            if particle:
                variants.add(word[: -len(particle)])
    return words | variants


def _terms(text: str) -> tuple[set[str], set[str], set[str]]:
    paths = {path.casefold().removeprefix("./").rstrip(".") for path in PATH_RE.findall(text)}
    # Only a path's file stem and its two nearest directories name what it is
    # about. Leading directories (`app/src/main/java/com/<org>/<app>`) and the
    # extension are shared by most files of a repository, so counting them let
    # any record with a path outrank the record that matches the work. Even the
    # nearest directories (`src/main/kotlin`) are often shared, so they count
    # as plain words; the module weight is kept for stems and identifiers.
    stems = {Path(path).stem for path in paths}
    near = {part for path in paths for part in Path(path).parts[:-1][-2:]} | stems
    rest = PATH_RE.sub(" ", text)
    words = _particle_variants({word.casefold() for word in TOKEN_RE.findall(" ".join((rest, *near)))
                                if len(word) > 1}) - STOP_WORDS
    modules = stems | {word.casefold() for word in re.findall(r"\b[\w-]+\b", rest)
                       if "_" in word or "-" in word or re.search(r"[a-z][A-Z]", word)}
    return words, paths, modules - STOP_WORDS


def _relevance(record: dict[str, Any], query: tuple[set[str], set[str], set[str]]) -> int:
    # A known exception must be visible to the agent without making that
    # exception a positive retrieval match. Superseded bodies are not indexed.
    text = " ".join([record["body"], record["source"], record.get("applies_when", ""),
                     *(item["path"] for item in record.get("source_files", []))])
    words, paths, modules = _terms(text)
    query_words, query_paths, query_modules = query
    # Absolute query paths may name the same repository-relative evidence file.
    matches = sum(any(other == path or other.endswith("/" + path) for other in query_paths) for path in paths)
    module_matches = (modules & (query_words | query_modules)) | (query_modules & words)
    return len(words & query_words) + 12 * matches + 8 * len(module_matches)


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


def store_dir(project: Path) -> Path:
    """Use one local store across every worktree of the same Git repository."""
    root = global_state_dir() / STORE_NAME
    directory = root / repository_key(project)
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("memory directory must not be a symlink")
    return directory


def _writable_store(project: Path) -> Path:
    refusal = user_store_write_error()
    if refusal:
        raise ValueError(refusal)
    return store_dir(project)


def _record_path(project: Path, record_id: str) -> Path:
    if not ID_RE.fullmatch(record_id):
        raise ValueError("invalid memory id")
    return store_dir(project) / f"{record_id}.json"


def read_record(path: Path) -> dict[str, Any] | None:
    """Return one validated record, or None for anything that fails validation."""
    if path.is_symlink():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        valid = (
            ID_RE.fullmatch(record["id"]) is not None
            and path.name == f'{record["id"]}.json'
            and record["status"] in STATUSES
            and SCOPE_RE.fullmatch(record["scope"]) is not None
            and isinstance(record["body"], str)
            and 1 <= len(record["body"]) <= 500
            and record["body"].isprintable()
            and isinstance(record["source"], str)
            and 1 <= len(record["source"]) <= 200
            and record["source"].isprintable()
            and date.fromisoformat(record["review_on"]) >= date(2000, 1, 1)
            and record["digest"] == _digest(record)
            and ID_RE.fullmatch(record.get("replaces") or "0" * 16) is not None
            and ("source_files" not in record or _valid_source_files(record["source_files"]))
            and ("analysis" not in record or _valid_analysis(record))
            and all(key not in record or (isinstance(record[key], str)
                    and 1 <= len(record[key]) <= MAX_CONDITION_CHARS
                    and record[key].isprintable()) for key in APPLICABILITY_FIELDS)
        )
    except (KeyError, TypeError, ValueError):
        return None
    return record if valid else None


def _existing(project: Path, record_id: str) -> tuple[Path, dict[str, Any]]:
    path = _record_path(project, record_id)
    record = read_record(path)
    if record is None:
        raise ValueError("memory record is missing or invalid")
    return path, record


def _retire(project: Path, record_id: str, *, replaced_by: str = "") -> dict[str, Any]:
    path, record = _existing(project, record_id)
    if record["status"] == "retired":
        return record
    record["status"] = "retired"
    record["retired_at"] = _timestamp()
    if replaced_by:
        record["replaced_by"] = replaced_by
    _writable_store(project)
    atomic_write_json(path, record)
    return record


def _capture(project: Path, *, body: str, source: str, scope: str, review_on: str,
             replaces: str = "", source_paths: tuple[str, ...] = (),
             applies_when: str = "", not_when: str = "",
             analysis_question: str = "", analysis_context: str = "") -> dict[str, Any]:
    body, source = body.strip(), source.strip()
    if not (1 <= len(body) <= 500 and body.isprintable()):
        raise ValueError("memory body must be one line of 1–500 characters")
    if not (1 <= len(source) <= 200 and source.isprintable()):
        raise ValueError("source must be one line of 1–200 characters")
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("scope must be a reusable workflow slug")
    if date.fromisoformat(review_on) <= date.today():
        raise ValueError("review date must be in the future")
    conditions = {key: value.strip() for key, value in
                  zip(APPLICABILITY_FIELDS, (applies_when, not_when)) if value.strip()}
    if any(len(value) > MAX_CONDITION_CHARS or not value.isprintable()
           for value in conditions.values()):
        raise ValueError(f"applicability conditions must be one line of 1–{MAX_CONDITION_CHARS} characters")
    if replaces:
        _existing(project, replaces)
    if len(source_paths) > MAX_SOURCE_FILES:
        raise ValueError(f"at most {MAX_SOURCE_FILES} source paths are allowed")
    source_files = []
    for path in dict.fromkeys(source_paths):
        blob = _source_blob(project, path, tracked=True)
        if not blob:
            raise ValueError("source path must name a readable tracked repository-relative file without symlinks")
        source_files.append({"path": path, "blob": blob})
    analysis = _analysis_binding(analysis_question, analysis_context)
    if analysis is not None:
        if not source_files:
            raise ValueError("analysis capture requires tracked source evidence")
        analysis["inputs"] = EvidenceInputs.capture(project.resolve(), [])
    _writable_store(project).mkdir(parents=True, exist_ok=True, mode=0o700)
    record_id = secrets.token_hex(8)
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "status": "active",
        "scope": scope,
        "body": body,
        "source": source,
        "review_on": review_on,
        "created_at": _timestamp(),
        **conditions,
    }
    if replaces:
        record["replaces"] = replaces
    if source_files:
        record["source_files"] = source_files
    if analysis is not None:
        record["analysis"] = analysis
    record["digest"] = _digest(record)
    # The new record is the commit point: recall already hides the record it
    # replaces, so an interrupted retire below never shows both.
    atomic_write_json(_record_path(project, record_id), record)
    if replaces:
        _retire(project, replaces, replaced_by=record_id)
    return record


def scan_records(project: Path) -> tuple[list[dict[str, Any]], int]:
    """Read the store once: every validated record and the count of rejected files."""
    directory = store_dir(project)
    if not directory.is_dir() or directory.is_symlink():
        return [], 0
    records, unreadable = [], 0
    for path in sorted(directory.glob("*.json")):
        record = read_record(path)
        if record is None:
            unreadable += 1
        else:
            records.append(record)
    return records, unreadable


def _recall(project: Path, scope: str, *, today: date | None = None,
            records: list[dict[str, Any]] | None = None, request: str = "",
            target_summary: str = "", target_paths: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not SCOPE_RE.fullmatch(scope):
        raise ValueError("invalid recall scope")
    today = today or date.today()
    if records is None:
        records = scan_records(project)[0]
    live = [record for record in records if record["status"] in RECALLABLE_STATUSES]
    # Replacement is durable even if retiring its predecessor was interrupted.
    # Retiring or replacing the successor must never resurrect invalidated advice.
    replaced = {record.get("replaces") for record in records}
    eligible = [
        record for record in live
        if record["id"] not in replaced
        and record["scope"] in {scope, "all"}
        and date.fromisoformat(record["review_on"]) > today
    ]
    context = " ".join((request, target_summary, *map(str, target_paths)))
    query = _terms(context)
    scores = {item["id"]: _relevance(item, query) for item in eligible}
    # Empty slots are preferable to unrelated advice. Context-free inspection
    # still lists every eligible record; lexical matching is not a truth check.
    if context.strip():
        eligible = [item for item in eligible if scores[item["id"]] > 0]
    # Relevance comes first; ties and context-free calls retain the old order.
    eligible.sort(key=lambda item: (-scores[item["id"]], item["scope"] != scope,
                                    item["review_on"], item["id"]))
    return eligible


def _analysis_recall(project: Path, scope: str, question: str, context: str) -> list[dict[str, Any]]:
    binding = _analysis_binding(question, context)
    if binding is None:
        raise ValueError("analysis recall requires a question and context")
    candidates = [record for record in _recall(project, scope)
                  if record["scope"] == scope and "analysis" in record
                  and all(record["analysis"].get(key) == value for key, value in binding.items())]
    if not candidates:
        return []
    try:
        inputs = EvidenceInputs.capture(project.resolve(), [])
    except (OSError, ValueError, RuntimeError):
        return []  # Unavailable inputs never mean unchanged inputs.
    result, used, blobs = [], 2, {}
    for record in candidates:
        if record["analysis"]["inputs"] != inputs or _source_status(project, record, blobs).get("source_status") != "unchanged":
            continue
        item = {key: record[key] for key in ("id", "digest", "body", "source", *APPLICABILITY_FIELDS)
                if key in record}
        item["analysis_status"] = "candidate_only"
        size = len(json.dumps(item, ensure_ascii=False)) + (2 if result else 0)
        if used + size > MAX_RECALL_CHARS:
            continue
        result.append(item)
        used += size
        if len(result) == MAX_RECALL_ITEMS:
            break
    return result


def _previously(record: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The body this record replaced, cut to one bounded line, or nothing."""
    previous = by_id.get(record.get("replaces") or "")
    if previous is None:
        return {}
    body = previous["body"]
    if len(body) > MAX_PREVIOUS_CHARS:
        body = body[: MAX_PREVIOUS_CHARS - 1] + "…"
    return {"previously": body}


def _history(project: Path, record_id: str) -> list[dict[str, Any]]:
    """The replacement chain through `record_id`, newest first; read-only.

    Any id in the chain names the whole chain. A missing or unreadable link,
    or a cycle, ends the walk instead of failing it.
    """

    _existing(project, record_id)
    by_id = {record["id"]: record for record in scan_records(project)[0]}
    # The replacement is durable before retiring its predecessor writes replaced_by.
    following = {record["replaces"]: record["id"] for record in by_id.values()
                 if record.get("replaces")}
    newest, seen = record_id, {record_id}
    while ((later := by_id[newest].get("replaced_by") or following.get(newest)) in by_id
           and later not in seen):
        newest = later
        seen.add(later)
    chain, current, seen = [], newest, set()
    while current in by_id and current not in seen and len(chain) < MAX_HISTORY_ITEMS:
        seen.add(current)
        record = by_id[current]
        chain.append({key: record[key] for key in
                      ("id", "status", "body", "source", "created_at", "retired_at", "replaces",
                       *APPLICABILITY_FIELDS)
                      if key in record})
        current = record.get("replaces") or ""
    return chain


def recall_lines(project: Path, scope: str, *,
                 records: list[dict[str, Any]] | None = None, request: str = "",
                 target_summary: str = "", target_paths: tuple[str, ...] = ()) -> list[str]:
    """Render bounded, explicitly non-authoritative context for a start result.

    `records` lets a caller that already scanned the store reuse that read.
    """
    lines = []
    size = 0
    blobs: dict[str, str] = {}
    if records is None:
        records = scan_records(project)[0]
    by_id = {record["id"]: record for record in records}
    for record in _recall(project, scope, records=records, request=request,
                          target_summary=target_summary, target_paths=target_paths):
        if len(lines) >= MAX_RECALL_ITEMS:
            break
        fields = {**{key: record[key] for key in ("id", "body", "source", "review_on")},
                  **{key: record[key] for key in APPLICABILITY_FIELDS if key in record},
                  **_previously(record, by_id)}
        # Evidence status only lengthens the payload, so a record that is
        # already too long is skipped before any of its files are hashed.
        if size + len(json.dumps(fields, ensure_ascii=False)) > MAX_RECALL_CHARS:
            continue
        payload = json.dumps({**fields, **_source_status(project, record, blobs)},
                             ensure_ascii=False)
        if size + len(payload) > MAX_RECALL_CHARS:
            # Skip the oversized record so a shorter one after it still fits.
            continue
        lines.append(f"- {payload}")
        size += len(payload)
    if not lines:
        return []
    return ["Project memory (agent-written reference; the current request, repo rules "
            "and source evidence prevail; check applicability before use; "
            "previously is superseded history, never current advice):", *lines]


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--source", required=True)
    capture_parser.add_argument("--scope", default="all")
    capture_parser.add_argument("--review-on", required=True)
    capture_parser.add_argument("--replaces", default="")
    capture_parser.add_argument("--applies-when", default="", help="verified applicability condition, at most 160 characters")
    capture_parser.add_argument("--not-when", default="", help="known exception, at most 160 characters; not used for ranking")
    capture_parser.add_argument("--source-path", action="append", default=[],
                                help="tracked repository-relative evidence file; repeat up to four times")
    capture_parser.add_argument("--analysis-question", default="")
    capture_parser.add_argument("--analysis-context", default="", help="explicit assumptions and external/toolchain inputs")
    # Former review step, kept so older instructions still run; it changes nothing.
    approve_parser = commands.add_parser("approve")
    approve_parser.add_argument("id")
    approve_parser.add_argument("--digest", default="")
    retire_parser = commands.add_parser("retire")
    retire_parser.add_argument("id")
    recall_parser = commands.add_parser("recall")
    recall_parser.add_argument("--scope", default="all")
    recall_parser.add_argument("--request", default="")
    recall_parser.add_argument("--target-summary", default="")
    recall_parser.add_argument("--target-path", action="append", default=[])
    recall_parser.add_argument("--analysis-question", default="")
    recall_parser.add_argument("--analysis-context", default="")
    # Read-only replacement chain through one record, newest first.
    history_parser = commands.add_parser("history")
    history_parser.add_argument("id")
    # Read-only review of the whole store; decisions go through capture and retire.
    consolidate_parser = commands.add_parser("consolidate")
    consolidate_parser.add_argument("--within-days", type=int, default=14)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    try:
        if args.command == "capture":
            result = _capture(project, body=sys.stdin.read(), source=args.source,
                              scope=args.scope, review_on=args.review_on,
                              replaces=args.replaces, source_paths=tuple(args.source_path),
                              applies_when=args.applies_when, not_when=args.not_when,
                              analysis_question=args.analysis_question, analysis_context=args.analysis_context)
        elif args.command == "approve":
            result = _existing(project, args.id)[1]
        elif args.command == "retire":
            result = _retire(project, args.id)
        elif args.command == "history":
            result = _history(project, args.id)
        elif args.command == "consolidate":
            # Imported here: the rules module imports this one.
            from agent_project_memory_consolidate import consolidate

            result = consolidate(project, within_days=args.within_days)
        elif args.analysis_question or args.analysis_context:
            if args.request or args.target_summary or args.target_path:
                raise ValueError("analysis lookup cannot be mixed with lexical recall options")
            result = _analysis_recall(project, args.scope, args.analysis_question, args.analysis_context)
        else:
            blobs: dict[str, str] = {}
            records = scan_records(project)[0]
            by_id = {record["id"]: record for record in records}
            result = [{**record, **_previously(record, by_id), **_source_status(project, record, blobs)}
                      for record in _recall(project, args.scope, records=records, request=args.request,
                                            target_summary=args.target_summary,
                                            target_paths=tuple(args.target_path))]
    except (OSError, ValueError) as error:
        parser.exit(2, f"project memory: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
