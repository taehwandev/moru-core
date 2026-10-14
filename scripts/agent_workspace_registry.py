"""Registry parsing helpers for Moru Core workspace groups."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent_project_search import request_name_matches
from workflow_common import unique


SCOPE_MODES = (
    "single_repo",
    "primary_led_secondary_read",
    "primary_led_secondary_write",
    "multi_session",
)
CHECKPOINT_FIELDS = (
    "starting_primary",
    "new_source_of_truth",
    "secondary_repo",
    "mode",
    "write_scope",
    "verification",
    "session_model",
)


def workspace_groups(registry: dict[str, object]) -> list[dict[str, Any]]:
    raw_groups = registry.get("workspace_groups", [])
    if not isinstance(raw_groups, list):
        return []
    return [
        group
        for group in raw_groups
        if isinstance(group, dict) and group.get("disabled") is not True
    ]


def group_members(group: dict[str, Any]) -> list[dict[str, Any]]:
    raw_members = group.get("members", [])
    if not isinstance(raw_members, list):
        return []
    return [
        member
        for member in raw_members
        if isinstance(member, dict) and member.get("disabled") is not True
    ]


def group_name(group: dict[str, Any]) -> str:
    name = group.get("name") or group.get("id") or "workspace"
    return str(name)


def group_aliases(group: dict[str, Any]) -> list[str]:
    raw_aliases = group.get("aliases", [])
    aliases = _string_list(raw_aliases)
    return unique([group_name(group), *aliases])


def member_aliases(member: dict[str, Any], root: Path | None) -> list[str]:
    raw_aliases = member.get("aliases", [])
    role = member.get("role") or member.get("name")
    names = [str(role)] if isinstance(role, str) and role else []
    if root:
        names.append(root.name)
    return unique([*names, *_string_list(raw_aliases)])


def member_role(member: dict[str, Any], index: int) -> str:
    role = member.get("role") or member.get("name")
    if isinstance(role, str) and role:
        return role
    return f"member_{index + 1}"


def member_path(member: dict[str, Any]) -> Path | None:
    raw = member.get("root") or member.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    return Path(os.path.expandvars(raw)).expanduser()


def matches_request(aliases: list[str], request_lc: str) -> bool:
    return any(request_name_matches(alias, request_lc, allow_generic=True) for alias in aliases)


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str)]
