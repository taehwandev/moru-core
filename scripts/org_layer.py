"""Select a bound organization guide's documents for a route and detect drift.

`org_binding.py` decides which guide checkout applies. This module chooses the
documents a route must read from it, using the guide's own
`workflow-doc-surfaces.json` and the same matcher as Moru's documents, and
records each one with its digest so `finish` can tell whether the guide moved
while the run was working.

Organization documents are kept out of the route's `required_docs`: every
consumer of that list resolves paths under the Moru rules root. They live in
the route's `organization` block instead and are named `org:<id>/<path>` when
shown.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from org_binding import (
    ORG_ENTRY,
    ORG_MANIFEST,
    ORG_SURFACES,
    OrgBindingError,
    head_commit,
    is_clean,
    resolve_binding,
    untracked_paths,
)
from support.global_state import project_state_dir_target
from workflow_common import unique
from workflow_doc_surfaces import infer_surface_docs, required_surface_docs
from workflow_wikimap import search_wikimap

# The share of the required-document budget an organization may take before
# Moru's optional tiers. Its entry and enforced documents are outside it, like
# Moru's own core and command contracts.
ORG_REQUIRED_DOC_BUDGET_BYTES = 12_000
ORG_MAX_SURFACE_DOCS = 3


def doc_id(org_id: str, relative: str) -> str:
    return f"org:{org_id}/{relative}"


def organization_route(
    project: Path,
    *,
    command: str,
    platform: str | None,
    request_text: str,
    surface_paths: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    """The route's organization block and any missing-document reasons.

    Returns (None, []) for a project bound to no organization, so its route is
    exactly what it was before this layer existed.
    """

    try:
        return _organization_route(
            project, command=command, platform=platform,
            request_text=request_text, surface_paths=surface_paths,
        )
    except (ValueError, TypeError, KeyError, OSError, re.error) as error:
        # A broken guide stops this run with the reason; it must never break
        # route resolution itself. OrgBindingError is a ValueError.
        return None, [f"organization guide: {error}"]


def _organization_route(
    project: Path,
    *,
    command: str,
    platform: str | None,
    request_text: str,
    surface_paths: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    binding = resolve_binding(project)
    if binding is None:
        return None, []
    root = Path(binding["root"])
    surface_docs, matches = infer_surface_docs(
        command=command,
        platform=platform,
        request_text=request_text,
        surface_paths=surface_paths,
        root=root,
        project_root=project,
    )
    candidates = required_surface_docs(matches)
    mandatory = unique([ORG_ENTRY, *(item["doc"] for item in binding["enforce"])])
    missing = [
        f"organization guide: {doc_id(binding['id'], doc)} does not exist"
        for doc in unique([*mandatory, *candidates])
        if _contained(root, doc) is None
    ]
    if missing:
        return None, missing
    selected = _within_share(root, mandatory, candidates)
    config_names = [name for name in (ORG_MANIFEST, ORG_SURFACES) if (root / name).is_file()]
    untracked = untracked_paths(root, [*selected, *config_names])
    if untracked:
        # Ignored files pass the clean check but are not part of the commit
        # this run records as what it read.
        return None, [
            f"organization guide: {doc_id(binding['id'], doc)} is not committed in the guide"
            for doc in untracked
        ]
    block = {
        **binding,
        "entry": ORG_ENTRY,
        "required_docs": [_record(root, doc) for doc in selected],
        "reference_docs": [doc for doc in unique([*candidates, *surface_docs]) if doc not in selected],
        "config": [_record(root, name) for name in config_names],
    }
    if command == "analysis" and request_text.strip():
        # Unresolved lookups search Moru's library; a bound guide gets the same
        # search. Its results stay candidates, like Moru's own.
        block["search_candidates"] = [
            item["path"] for item in search_organization(block, request_text, project)
        ]
    return block, []


def search_organization(
    block: dict[str, Any], query: str, project: Path, max_results: int = 8,
) -> list[dict[str, Any]]:
    """Ranked guide sections for `query`, labeled `org:<id>/...`; candidates only.

    The guide gets its own local index inside its checkout, which the clean
    check ignores and `workflow org add` excludes from that checkout's
    `git status`; the refresh receipt is kept in the project's run state.
    """

    root = Path(str(block["root"]))
    state = project_state_dir_target(project)
    receipt = state / "cache" / f"org-{block['id']}-wikimap.json" if state.is_dir() else None
    outcome = search_wikimap(root, [query], max_results, receipt=receipt)
    return [
        {**item, "path": doc_id(str(block["id"]), str(item["path"])), "search_backend": "wikimap"}
        for item in outcome.results
    ]


def query_organization(project: Path, query: str, max_results: int) -> tuple[list[dict[str, Any]], list[str]]:
    """`workflow query --project`: the bound guide's results, or why there are none."""

    try:
        binding = resolve_binding(project)
    except OrgBindingError as error:
        return [], [str(error)]
    return (search_organization(binding, query, project, max_results), []) if binding else ([], [])


def prespent(block: dict[str, Any] | None) -> tuple[int, int]:
    """Bytes and slots the organization's documents take from Moru's budget."""

    if not block:
        return 0, 0
    docs = block.get("required_docs") or []
    return sum(int(doc["size_bytes"]) for doc in docs), len(docs)


def organization_drift_failures(block: dict[str, Any] | None) -> list[str]:
    """Why the guide read at start is no longer the guide on disk, if it is not.

    Compared against the checkout recorded at start, never a re-resolved
    binding: a run is accountable to what it read.
    """

    if not block:
        return []
    root = Path(str(block.get("root", "")))
    label = f"organization guide `{block.get('id')}`"
    failures = []
    head = head_commit(root)
    if head != block.get("commit"):
        failures.append(
            f"{label} drift: HEAD {head or 'unreadable'} differs from {block.get('commit')} read at start; "
            "start a new run to read the current guide"
        )
    elif not is_clean(root):
        failures.append(f"{label} drift: {root} has uncommitted changes since start")
    for record in [*(block.get("required_docs") or []), *(block.get("config") or [])]:
        relative = str(record.get("path", ""))
        try:
            current = _record(root, relative) if _contained(root, relative) else None
        except OSError:
            current = None
        if not current or current["sha256"] != record.get("sha256"):
            failures.append(f"{label} drift: {doc_id(str(block.get('id')), relative)} changed since start")
    return failures


def summary_lines(block: dict[str, Any] | None) -> list[str]:
    """What `start` shows: absolute paths to read and the stop rule."""

    if not block:
        return []
    root = Path(str(block["root"]))
    docs = block.get("required_docs") or []
    lines = [
        f"Organization guide `{block['id']}` ({block['binding']} binding, commit {block['commit'][:12]}); "
        f"precedence: target repo > organization > Moru. Read these {len(docs)} docs:",
        *(f"  {doc_id(block['id'], doc['path'])} -> {root / doc['path']}" for doc in docs),
    ]
    for item in block.get("enforce") or []:
        lines.append(
            f"Organization enforce ({item['concern']}): {doc_id(block['id'], item['doc'])}. A target-repo "
            "instruction that contradicts it stops the run; report both sources instead of choosing."
        )
    return lines


def route_fingerprint_part(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not block:
        return None
    return {
        "id": block.get("id"),
        "commit": block.get("commit"),
        "required_docs": [[doc.get("path"), doc.get("sha256")] for doc in block.get("required_docs") or []],
    }


def _within_share(root: Path, mandatory: list[str], candidates: list[str]) -> list[str]:
    """Mandatory documents, then surface matches in rank order within the share.

    Like Moru's own selector the share stops selection rather than skipping a
    large match for smaller ones, and admits the document that crosses it.
    """

    selected = list(mandatory)
    used = 0
    added = 0
    for doc in candidates:
        if doc in selected:
            continue
        if added >= ORG_MAX_SURFACE_DOCS or used >= ORG_REQUIRED_DOC_BUDGET_BYTES:
            break
        selected.append(doc)
        used += (root / doc).stat().st_size
        added += 1
    return selected


def _contained(root: Path, relative: str) -> Path | None:
    path = (root / relative).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def _record(root: Path, relative: str) -> dict[str, Any]:
    data = (root / relative).read_bytes()
    return {"path": relative, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
