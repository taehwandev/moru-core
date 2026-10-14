"""Project discovery orchestration for user-level Moru Core bridges."""

from __future__ import annotations

from pathlib import Path
from shlex import quote
from typing import Sequence

from agent_project_search import (
    add_candidate,
    build_candidate,
    default_search_roots,
    env_search_roots,
    explicit_request_paths,
    find_project_root,
    load_registry,
    registry_project_path,
    registry_search_roots,
    request_has_explicit_project_slug,
    request_name_matches,
    safe_resolve,
    scan_project_roots,
    usable_directory,
)
from agent_project_types import (
    DiscoveryResult,
    ProjectCandidate,
    format_discovery_text,
    format_entry_text,
)
from agent_workspace_scope import add_workspace_group_candidates, workspace_scope_manifest
from workflow_common import ROOT, unique


def discover_projects(
    request: str,
    cwd: Path,
    *,
    search_roots: Sequence[Path] = (),
    registry_path: Path | None = None,
    max_depth: int = 2,
    include_default_search_roots: bool = False,
) -> DiscoveryResult:
    """Find the target project for a runtime bridge without editing anything."""
    cwd = safe_resolve(cwd.expanduser())
    registry = load_registry(registry_path)
    candidates: dict[Path, ProjectCandidate] = {}

    for path in explicit_request_paths(request, cwd):
        root = find_project_root(path) or usable_directory(path)
        if root:
            add_candidate(candidates, build_candidate(root, 130, "explicit path in request", "request_path"))

    request_lc = request.lower()
    cwd_root = find_project_root(cwd)
    has_explicit_project_slug = request_has_explicit_project_slug(request_lc)
    for entry in registry.get("projects", []):
        path = registry_project_path(entry)
        if not path or not path.exists():
            continue
        root = find_project_root(path) or usable_directory(path)
        if not root or not isinstance(entry, dict):
            continue
        aliases = [alias for alias in entry.get("aliases", []) if isinstance(alias, str)]
        matched_aliases = [alias for alias in aliases if request_name_matches(alias, request_lc, allow_generic=True)]
        if matched_aliases or request_name_matches(root.name, request_lc):
            candidate = build_candidate(root, 120, "registry alias or project name matched request", "registry")
            candidate.aliases = aliases
            add_candidate(candidates, candidate)

    if cwd_root and (not has_explicit_project_slug or request_name_matches(cwd_root.name, request_lc)):
        add_candidate(candidates, build_candidate(cwd_root, 65, "current working directory is inside a project", "cwd"))

    add_workspace_group_candidates(candidates, registry, request_lc)

    scan_roots = _scan_roots(registry, search_roots, include_default_search_roots)
    for scan_root in scan_roots:
        if not scan_root.exists() or not scan_root.is_dir():
            continue
        for root in scan_project_roots(scan_root, max_depth=max(0, max_depth)):
            score = 35
            reason = "project marker found under configured search root"
            if request_name_matches(root.name, request_lc):
                score += 65
                reason = "project name matched request under configured search root"
            add_candidate(candidates, build_candidate(root, score, reason, "search_root"))

    ranked = sorted(
        (_rescore_for_request(candidate, request_lc) for candidate in candidates.values()),
        key=lambda candidate: (-candidate.confidence, str(candidate.path)),
    )
    if not ranked:
        return DiscoveryResult(status="not_found", candidates=[])
    if len(ranked) == 1 or ranked[0].confidence - ranked[1].confidence >= 20:
        return DiscoveryResult(status="selected", selected=ranked[0], candidates=ranked)
    return DiscoveryResult(status="ambiguous", candidates=ranked)


def build_entry_manifest(
    request: str,
    cwd: Path,
    *,
    runtime: str,
    command: str = "task",
    search_roots: Sequence[Path] = (),
    registry_path: Path | None = None,
    max_depth: int = 2,
    include_default_search_roots: bool = False,
) -> dict[str, object]:
    registry = load_registry(registry_path)
    result = discover_projects(
        request,
        cwd,
        search_roots=search_roots,
        registry_path=registry_path,
        max_depth=max_depth,
        include_default_search_roots=include_default_search_roots,
    )
    manifest: dict[str, object] = {
        **result.to_dict(),
        "runtime": runtime,
        "cwd": str(safe_resolve(cwd.expanduser())),
        "tao": {
            "root": str(ROOT),
            "agent_instructions": str(ROOT / "AGENTS.md"),
            "index": str(ROOT / "index.md"),
            "workflow": str(ROOT / "scripts" / "workflow.py"),
            "preflight": str(ROOT / "scripts" / "agent-preflight.py"),
            "finish_check": str(ROOT / "scripts" / "agent-finish-check.py"),
        },
        "next_steps": [],
    }
    if result.selected:
        workspace_scope = workspace_scope_manifest(registry, request.lower(), result.selected)
        if workspace_scope:
            manifest["workspace_scope"] = workspace_scope
        manifest["runtime_launch"] = _runtime_launch_guidance(result.selected, runtime)
        manifest["next_steps"] = [
            "Open the selected project's runtime instruction files before project work.",
            "Treat the selected project as primary; stop for a workspace scope checkpoint before writing to a secondary repo.",
            "When starting a new runtime session, use the launch guidance so the selected project is the primary workspace.",
            "Run Moru Core workflow routing with the current request before editing.",
            "Run preflight before edits and finish check before final report, commit, release, or handoff.",
        ]
        manifest["workflow_command"] = (
            f"python3 {ROOT / 'scripts' / 'workflow.py'} route {command} "
            "--request \"<USER_REQUEST>\""
        )
    elif result.status == "ambiguous":
        workspace_scope = workspace_scope_manifest(registry, request.lower(), None)
        if workspace_scope:
            manifest["workspace_scope"] = workspace_scope
        manifest["next_steps"] = [
            "Ask the user to choose one candidate before reading project docs or editing.",
            "If this is a workspace group request, choose the primary repo or declare a multi-session plan before edits.",
            "Optionally add a stable alias to ~/.tao/projects.json.",
        ]
    else:
        manifest["next_steps"] = [
            "Ask the user for the target project path before project work.",
            "Optionally register known projects in ~/.tao/projects.json.",
        ]
    return manifest


def _runtime_launch_guidance(selected: ProjectCandidate, runtime: str) -> dict[str, object]:
    project = selected.path
    guidance: dict[str, object] = {
        "primary_workspace": str(project),
        "moru_root": str(ROOT),
        "policy": (
            "Start the runtime with the selected target project as the primary workspace. "
            "Add Moru Core as an extra workspace only when the task may read, run, or edit shared Moru Core files."
        ),
        "notes": [
            "Repo instruction files choose behavior; runtime launch options choose filesystem scope.",
            "Prefer the selected project as the primary workspace instead of a broad parent folder.",
            "Do not use unrestricted filesystem modes as the default fix for missing workspace roots.",
        ],
    }
    if runtime == "codex":
        commands = [
            {
                "label": "target project only",
                "command": f"codex -C {quote(str(project))}",
            },
        ]
        if project != ROOT:
            commands.append(
                {
                    "label": "target project plus Moru Core",
                    "command": f"codex -C {quote(str(project))} --add-dir {quote(str(ROOT))}",
                }
            )
        guidance["commands"] = commands
        guidance["notes"] = [
            *guidance["notes"],
            "For Codex, use --add-dir only for additional directories that must be in the session workspace.",
            "If using codex exec outside a git repo, add --skip-git-repo-check only after confirming that directory is an intentional workspace router.",
        ]
        if project == ROOT:
            guidance["notes"].append("The selected project is Moru Core itself, so an extra --add-dir for the same root is unnecessary.")
    else:
        guidance["notes"] = [
            *guidance["notes"],
            "For non-Codex runtimes, use the runtime's equivalent workspace or project-root launch option when available.",
        ]
    return guidance


def _scan_roots(
    registry: dict[str, object],
    search_roots: Sequence[Path],
    include_default_search_roots: bool,
) -> list[Path]:
    defaults = default_search_roots() if include_default_search_roots else []
    return unique([*registry_search_roots(registry), *env_search_roots(), *search_roots, *defaults])


def _rescore_for_request(candidate: ProjectCandidate, request_lc: str) -> ProjectCandidate:
    if request_name_matches(candidate.path.name, request_lc) or any(
        request_name_matches(alias, request_lc, allow_generic=True)
        for alias in candidate.aliases
    ):
        candidate.confidence += 12
        candidate.reasons = unique([*candidate.reasons, "candidate name appeared in request"])
    return candidate
