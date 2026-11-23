"""Prove which documents are already loaded in this session, for every route."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from support.global_state import project_state_dir_target
from support.native_doc_transcript import reuse_current


RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_REGISTRY_BYTES = 4 * 1024 * 1024
MAX_PREFLIGHT_BYTES = 8 * 1024 * 1024
MAX_RUNS = 100
MAX_SIBLING_WORKTREES = 8
MAX_TAKEAWAYS = 3
MAX_TAKEAWAY_CHARS = 400
# Written beside a run's preflight by `review --doc-takeaway`, for routes such
# as commit that have no source-docs gate to carry a takeaway.
DOC_TAKEAWAY_FILE = "doc-takeaway.json"


def required_doc_reuse(
    preflight_path: Path, *, require_takeaway: bool = True
) -> dict[str, list[str]]:
    """Partition required docs into proven same-session reuse and unread docs.

    This is display-only evidence. Any malformed, missing, cross-session, or
    changed record fails closed and leaves the document in ``unread``. The
    notice an agent reads requires the prior run's takeaway; commit-ready's
    automatic re-attestation of an already reviewed diff acts on no document,
    so it asks only whether the same session held them.
    """

    unread: list[str] = []
    try:
        native = reuse_current(preflight_path, project_docs=False)
        if native is None:
            current = _read(preflight_path, MAX_PREFLIGHT_BYTES)
            docs = _required_paths(current.get("route") or {})
            unread = list(docs)
            if not docs:
                return {"reused": [], "unread": unread}
            current_records = _doc_records(current)
        else:
            docs, current_records, binding = native
            unread = list(docs)
        wanted = {current_records[doc] for doc in docs if doc in current_records}
        if not wanted:
            return {"reused": [], "unread": unread}
        if native is None:
            binding = _current_binding(preflight_path, current)
        reusable_records, takeaways = _same_session_proof(
            binding, wanted, project_docs=False, require_takeaway=require_takeaway
        )

        reused = [doc for doc in docs if current_records.get(doc) in reusable_records]
        reused_set = set(reused)
        result = {
            "reused": reused,
            "unread": [doc for doc in docs if doc not in reused_set],
        }
        if reused and takeaways:
            result["takeaways"] = takeaways
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"reused": [], "unread": unread}


def project_route_doc_reuse(preflight_path: Path) -> dict[str, list[str]]:
    """Partition project-declared route docs the same way as required docs.

    Project docs live under the project root, not the rules root, so they are
    recorded beside the snapshot as ``project_route_docs`` and compared by
    path, hash and size against completed same-session runs.
    """

    unread: list[str] = []
    try:
        native = reuse_current(preflight_path, project_docs=True)
        if native is None:
            current = _read(preflight_path, MAX_PREFLIGHT_BYTES)
            current_records = _project_records(current)
        else:
            _, current_records, binding = native
        unread = list(current_records)
        if not current_records:
            return {"reused": [], "unread": unread}
        wanted = set(current_records.values())
        if native is None:
            binding = _current_binding(preflight_path, current)
        reusable, takeaways = _same_session_proof(
            binding, wanted, project_docs=True, require_takeaway=True
        )
        reused = [doc for doc, record in current_records.items() if record in reusable]
        reused_set = set(reused)
        result = {"reused": reused, "unread": [doc for doc in unread if doc not in reused_set]}
        if reused and takeaways:
            result["takeaways"] = takeaways
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"reused": [], "unread": unread}


def _current_binding(preflight_path: Path, current: dict[str, Any]):
    project = Path(current["project"]).resolve()
    run_dir = preflight_path.resolve().parent
    if (
        not RUN_ID.fullmatch(run_dir.name)
        or run_dir.parent != project_state_dir_target(project) / "runs"
        or preflight_path.resolve() != run_dir / "preflight.json"
    ):
        return None
    session = _session(current)
    return (project, run_dir.name, session) if session is not None else None


def _same_session_proof(binding, wanted, *, project_docs: bool, require_takeaway: bool):
    """Collect proof from completed same-session runs, this checkout first."""

    from support.native_doc_transcript import reuse_plan

    reusable: set[tuple[str, str, int]] = set()
    takeaways: list[str] = []
    if binding is None:
        return reusable, takeaways
    project, run_id, session = binding
    # Lazily, this checkout's newest runs first: callers stop at full coverage.
    query = list(wanted)
    for root in _repository_roots(project, include_sibling_repos=not project_docs):
        native = reuse_plan(
            root, run_id, session, query, reusable, takeaways, project_docs=project_docs,
            require_takeaway=require_takeaway, limits=(MAX_RUNS, MAX_TAKEAWAYS, MAX_TAKEAWAY_CHARS),
        )
        if native is None:
            # A declined plan returned no changes. Replay this checkout from
            # the same coverage and takeaway slots, including legacy records.
            for path, records in _completed_matches(
                root, run_id, session, wanted, project_docs=project_docs
            ):
                if _credit(records, wanted, path, takeaways, reusable) or not require_takeaway:
                    reusable.update(records)
                if wanted <= reusable:
                    break
        else:
            covered, added = native
            reusable.update(covered)
            takeaways.extend(added)
        if wanted <= reusable:
            break
    return reusable, takeaways


def _completed_matches(
    root: Path, current_run: str, session: tuple[str, str], wanted: set[tuple[str, str, int]],
    *, project_docs: bool,
):
    from support.native_doc_transcript import reuse_matches, reuse_run_ids

    runs = project_state_dir_target(root) / "runs"
    ids = reuse_run_ids(root, current_run, MAX_RUNS)
    if (ids is not None and len(ids) <= MAX_RUNS
            and all(run_id != current_run and RUN_ID.fullmatch(run_id) for run_id in ids)):
        query = list(wanted)
        while ids:
            native = reuse_matches(root, ids, session, query, project_docs=project_docs)
            if native is None:
                # Resume from the first unconsumed candidate if native cannot
                # represent a legacy record, without re-crediting a prior run.
                break
            consumed, matches = native
            if matches:
                yield runs / ids[consumed - 1] / "preflight.json", matches
            ids = ids[consumed:]
    else:
        ids = _completed_run_ids_python(root, current_run)
    for run_id in ids:
        prior_path = runs / run_id / "preflight.json"
        try:
            prior = _read(prior_path, MAX_PREFLIGHT_BYTES)
            if (
                prior.get("agent_run_id") != run_id
                or Path(prior["project"]).resolve() != root
                or _session(prior) != session
            ):
                continue
            records = _project_records(prior) if project_docs else _doc_records(prior)
            matches = wanted.intersection(records.values())
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if matches:
            yield prior_path, matches


def _completed_run_ids_python(root: Path, current_run: str):
    try:
        registry = _read(project_state_dir_target(root) / "run-registry.json", MAX_REGISTRY_BYTES)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    runs = registry.get("runs")
    if not isinstance(runs, list):
        return
    # Registry entries are appended. Bound history work, not goal length.
    for record in reversed(runs[-MAX_RUNS:]):
        if not isinstance(record, dict) or record.get("state") != "completed":
            continue
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            continue
        evidence_name = record.get("evidence_name", "preflight.json")
        if evidence_name != "preflight.json" or run_id == current_run:
            continue
        yield run_id


def _repository_roots(project: Path, *, include_sibling_repos: bool = False):
    """Yield this checkout first, then the repository's other worktrees and lazy sibling repos."""

    from support.native_doc_transcript import discover_reuse_roots

    roots = [project]
    yield project
    native = discover_reuse_roots(project, roots, MAX_SIBLING_WORKTREES, phase="worktrees")
    if native is None:
        workspace, worktree_roots = _worktree_roots_python(project)
    else:
        workspace, worktree_roots = native
    roots.extend(worktree_roots)
    yield from worktree_roots
    if (
        include_sibling_repos
        and workspace is not None
        and workspace.is_dir()
        and workspace != workspace.parent
        and workspace != Path.home()
    ):
        native = discover_reuse_roots(workspace, roots, MAX_SIBLING_WORKTREES, phase="siblings")
        if native is not None:
            yield from native[1]
        else:
            try:
                repo_candidates = [p for p in workspace.iterdir() if (p / ".git").exists()]
            except OSError:
                repo_candidates = []
            yield from _recent_registered_roots(repo_candidates, roots)


def _worktree_roots_python(project: Path) -> tuple[Path | None, list[Path]]:
    try:
        dot_git = project / ".git"
        if dot_git.is_file():
            gitdir = Path(dot_git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            gitdir = gitdir if gitdir.is_absolute() else (project / gitdir)
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
        elif dot_git.is_dir():
            common = dot_git.resolve()
        else:
            return None, []
        candidates = [common.parent] if common.name == ".git" else []
        for link in sorted((common / "worktrees").glob("*/gitdir")):
            candidates.append(Path(link.read_text(encoding="utf-8").strip()).parent)
    except (OSError, IndexError):
        return None, []
    workspace = common.parent.parent if common.name == ".git" else None
    return workspace, _recent_registered_roots(candidates, [project])


def _recent_registered_roots(candidates: list[Path], excluded: list[Path]) -> list[Path]:
    from support.native_doc_transcript import rank_reuse_roots

    native = rank_reuse_roots(candidates, excluded, MAX_SIBLING_WORKTREES)
    return native if native is not None else _recent_registered_roots_python(candidates, excluded)


def _recent_registered_roots_python(candidates: list[Path], excluded: list[Path]) -> list[Path]:
    ranked = []
    for candidate in candidates:
        try:
            registry = project_state_dir_target(candidate.resolve()) / "run-registry.json"
            if registry.parents[1] not in excluded and registry.is_file():
                ranked.append((registry.stat().st_mtime, registry.parents[1]))
        except OSError:
            continue
    ranked.sort(reverse=True)
    return [root for _, root in ranked[:MAX_SIBLING_WORKTREES]]


def record_doc_takeaway(evidence_path: Path, text: str) -> None:
    """Store the agent's takeaway from this run's docs beside its preflight."""

    normalized = _normalize(text)
    if not normalized:
        return
    path = evidence_path.parent / DOC_TAKEAWAY_FILE
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"takeaway": normalized}), encoding="utf-8")
    temporary.replace(path)


def _credit(
    prior_records: set[tuple[str, str, int]],
    wanted: set[tuple[str, str, int]],
    prior_path: Path,
    takeaways: list[str],
    covered: set[tuple[str, str, int]] | None = None,
) -> bool:
    """Whether a prior run may prove these docs were read, keeping its takeaways.

    A completed run that listed a document proves only that the document was
    required, not that it was read, and a reuse notice with nothing to replay
    after a context compaction told the agent to trust a reading it no longer
    had. So a run counts only when it recorded what it took from its docs; one
    that recorded nothing leaves them unread. The takeaways are keyed by the
    documents a run read, not by its route, so a commit run reusing a document
    replays what an earlier run of any route recorded.
    """

    if not prior_records & wanted:
        return False
    if covered is not None and not (prior_records & wanted) - covered:
        # Nothing new to prove: spending a display slot here is what left a
        # later run's documents unread once the cap filled.
        return False
    from support.native_doc_transcript import reuse_credit

    native = reuse_credit(prior_path, takeaways, MAX_TAKEAWAYS, MAX_TAKEAWAY_CHARS)
    if native is None:
        return _credit_takeaway_python(prior_path, takeaways)
    credited, added = native
    if added is not None:
        takeaways.append(added)
    return credited


def _credit_takeaway_python(prior_path: Path, takeaways: list[str]) -> bool:
    parts = list(dict.fromkeys(
        text for text in (_source_docs_takeaway(prior_path), _review_takeaway(prior_path)) if text
    ))
    if not parts:
        return False
    # One slot per run: its source-docs and review takeaways are merged.
    merged = " | ".join(parts)
    if merged in takeaways or any(merged in text for text in takeaways):
        return True
    if len(takeaways) >= MAX_TAKEAWAYS:
        # Only a run whose takeaway the notice actually shows is credited. Past
        # the display cap a run's documents would otherwise leave the unread
        # list with nothing replayed for them -- the gap the takeaway rule closes.
        return False
    takeaways.append(merged)
    return True


def _source_docs_takeaway(prior_path: Path) -> str:
    try:
        ledger = _read(prior_path.parent / "gate-evidence.json", MAX_PREFLIGHT_BYTES)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ""
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get("gate") != "source docs":
            continue
        if entry.get("status") != "SUCCESS":
            return ""
        return _normalize((entry.get("fields") or {}).get("takeaway"))
    return ""


def _review_takeaway(prior_path: Path) -> str:
    try:
        record = _read(prior_path.parent / DOC_TAKEAWAY_FILE, MAX_TAKEAWAY_CHARS * 8)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    return _normalize(record.get("takeaway"))


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_TAKEAWAY_CHARS]


def _read(path: Path, limit: int) -> dict[str, Any]:
    if path.stat().st_size > limit:
        raise ValueError("oversized lifecycle evidence")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid lifecycle evidence")
    return value


def _required_paths(route: dict[str, Any]) -> list[str]:
    docs = route.get("required_docs") or []
    if not isinstance(docs, list) or any(not isinstance(doc, str) for doc in docs):
        raise ValueError("invalid required document manifest")
    return list(dict.fromkeys(docs))


def _session(preflight: dict[str, Any]) -> tuple[str, str] | None:
    session = preflight.get("runtime_session") or {}
    if not isinstance(session, dict):
        return None
    runtime, session_id = session.get("runtime"), session.get("session_id")
    if not isinstance(runtime, str) or not isinstance(session_id, str):
        return None
    if not runtime or not session_id:
        return None
    return runtime, session_id


def _doc_records(preflight: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    return _records((preflight.get("execution_snapshot") or {}).get("required_docs") or [])


def _project_records(preflight: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    return _records(preflight.get("project_route_docs") or [])


def _records(records: Any) -> dict[str, tuple[str, str, int]]:
    if not isinstance(records, list):
        raise ValueError("invalid required document snapshot")
    result: dict[str, tuple[str, str, int]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid required document record")
        path = record.get("path")
        sha256 = record.get("sha256")
        size = record.get("size_bytes")
        if (
            not isinstance(path, str)
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise ValueError("invalid required document record")
        result[path] = (path, sha256, size)
    return result
