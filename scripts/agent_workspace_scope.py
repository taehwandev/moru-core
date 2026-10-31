"""Workspace group helpers for cross-repo project discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_project_search import (
    build_and_add_candidate,
    find_project_root,
    instruction_files,
    project_markers,
    safe_resolve,
    usable_directory,
)
from agent_project_types import ProjectCandidate
from agent_workspace_registry import (
    CHECKPOINT_FIELDS,
    SCOPE_MODES,
    group_aliases,
    group_members,
    group_name,
    matches_request,
    member_aliases,
    member_path,
    member_role,
    workspace_groups,
)
from workflow_common import unique


def add_workspace_group_candidates(
    candidates: dict[Path, ProjectCandidate],
    registry: dict[str, object],
    request_lc: str,
) -> None:
    """Add candidates from local workspace groups without selecting a repo alone."""
    for group in workspace_groups(registry):
        group_matched = matches_request(group_aliases(group), request_lc)
        for member in group_members(group):
            path = member_path(member)
            if not path or not path.exists():
                continue
            root = find_project_root(path) or usable_directory(path)
            if not root:
                continue
            aliases = member_aliases(member, root)
            member_matched = matches_request(aliases, request_lc)
            if not group_matched and not member_matched:
                continue

            score = 120 if member_matched else 35
            reason = (
                "workspace group member alias matched request"
                if member_matched
                else "workspace group alias matched request"
            )
            build_and_add_candidate(candidates, root, score, reason, "workspace_group",
                                    aliases=unique([*group_aliases(group), *aliases]))


def workspace_scope_manifest(
    registry: dict[str, object],
    request_lc: str,
    selected: ProjectCandidate | None,
) -> dict[str, object] | None:
    """Describe primary/secondary repo scope guidance for entry manifests."""
    group, matched_by = _select_workspace_group(registry, request_lc, selected)
    if not group:
        if not selected:
            return None
        return _single_repo_scope(selected)

    members = _member_manifests(group, selected)
    selected_member = next((member for member in members if member.get("selected")), None)
    scope_mode = "needs_target_decision"
    if selected_member and len(members) > 1:
        scope_mode = "primary_selected_checkpoint_before_expansion"
    elif selected_member:
        scope_mode = "single_repo"

    return {
        "scope_mode": scope_mode,
        "workspace_group": group_name(group),
        "matched_by": matched_by,
        "primary_repo": selected_member.get("path") if selected_member else None,
        "primary_role": selected_member.get("role") if selected_member else None,
        "primary_candidates": [member["path"] for member in members if member.get("exists")],
        "members": members,
        "available_modes": list(SCOPE_MODES),
        "scope_checkpoint": _scope_checkpoint(),
    }


def _single_repo_scope(selected: ProjectCandidate) -> dict[str, object]:
    return {
        "scope_mode": "single_repo",
        "workspace_group": None,
        "matched_by": "selected_project",
        "primary_repo": str(selected.path),
        "primary_role": None,
        "primary_candidates": [str(selected.path)],
        "members": [],
        "available_modes": list(SCOPE_MODES),
        "scope_checkpoint": _scope_checkpoint(),
    }


def _scope_checkpoint() -> dict[str, object]:
    return {
        "required_before_secondary_write": True,
        "required_when": [
            "a secondary repo becomes the source of truth for the requested behavior",
            "the agent needs to write outside the selected primary repo",
            "verification must cross repo boundaries",
            "a single session would need additional workspace roots",
        ],
        "fields": list(CHECKPOINT_FIELDS),
    }


def _select_workspace_group(
    registry: dict[str, object],
    request_lc: str,
    selected: ProjectCandidate | None,
) -> tuple[dict[str, Any] | None, str]:
    selected_path = safe_resolve(selected.path) if selected else None
    for group in workspace_groups(registry):
        if matches_request(group_aliases(group), request_lc):
            return group, "group_alias"
        if any(matches_request(member_aliases(member, member_path(member)), request_lc) for member in group_members(group)):
            return group, "member_alias"
        if selected_path and any(_member_resolves_to(member, selected_path) for member in group_members(group)):
            return group, "selected_member"
    return None, ""


def _member_manifests(group: dict[str, Any], selected: ProjectCandidate | None) -> list[dict[str, object]]:
    selected_path = safe_resolve(selected.path) if selected else None
    members: list[dict[str, object]] = []
    for index, member in enumerate(group_members(group)):
        path = member_path(member)
        if not path:
            continue
        root = find_project_root(path) or usable_directory(path) or path
        resolved = safe_resolve(root)
        members.append(
            {
                "role": member_role(member, index),
                "path": str(resolved),
                "aliases": member_aliases(member, resolved),
                "exists": resolved.exists(),
                "instruction_files": instruction_files(resolved) if resolved.exists() else [],
                "markers": project_markers(resolved) if resolved.exists() else [],
                "selected": selected_path == resolved if selected_path else False,
            }
        )
    return members


def _member_resolves_to(member: dict[str, Any], selected_path: Path) -> bool:
    path = member_path(member)
    if not path:
        return False
    root = find_project_root(path) or usable_directory(path) or path
    return safe_resolve(root) == selected_path
