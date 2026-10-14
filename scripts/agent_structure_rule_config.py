"""Structure rule config loading helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from support.global_state import project_state_dir_target


DEFAULT_RULE_PATH = ".agents/structure-rules.json"


def load_structure_rule_configs(project: Path) -> tuple[list[dict[str, Any]], list[str]]:
    raw_paths: list[Path] = []
    override = os.environ.get("MORU_STRUCTURE_RULES", "").strip()
    if override:
        raw_paths.append(Path(override).expanduser())
    raw_paths.append(project / DEFAULT_RULE_PATH)
    raw_paths.append(project_state_dir_target(project) / "structure-rules.json")

    configs: list[dict[str, Any]] = []
    failures: list[str] = []
    seen: set[Path] = set()
    for path in raw_paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.exists():
            continue
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            failures.append(f"structure rules: {display_path(project, resolved)} is not valid JSON: {error}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"structure rules: {display_path(project, resolved)} must contain a JSON object")
            continue
        configs.append({"path": display_path(project, resolved), "payload": payload})
    return configs, failures


def string_list(value: Any, config_path: str, field: str, result: dict[str, Any]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        result["failures"].append(f"structure rules: {config_path} field `{field}` must be a list of strings")
        return []
    return [item.strip() for item in value]


def display_path(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError:
        return str(path)
