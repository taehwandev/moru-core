"""Structure rule config loading helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from support.global_state import project_state_dir_target


DEFAULT_RULE_PATH = ".agents/structure-rules.json"
DEFAULT_CHANGED_PATHS_LIMIT = 25
POSITIVE_INT_LIMIT_KEYS = frozenset({
    "max_source_file_lines", "max_file_lines", "max_added_lines", "max_function_lines",
    "max_block_lines", "max_changed_paths", "max_public_owners", "max_visible_owners",
    "new_source_file_pressure_limit",
})
ALLOWED_LIMIT_KEYS = POSITIVE_INT_LIMIT_KEYS
LIMIT_KEY_ALIASES = {"max_file_lines": "max_source_file_lines", "max_block_lines": "max_function_lines"}
# Relaxations in repo config are capped at 2x the Moru defaults so no config
# can silently disable structural gates with absurd thresholds.
LIMIT_MAX_CAPS: dict[str, int] = {
    "max_source_file_lines": 1000, "max_added_lines": 600, "max_function_lines": 240,
    "max_changed_paths": 50, "max_public_owners": 2, "max_visible_owners": 8,
    "new_source_file_pressure_limit": 40,
}
STRUCTURE_CODE_EXTENSIONS = frozenset({
    ".c", ".cc", ".cpp", ".cs", ".css", ".cjs", ".dart", ".go", ".h", ".hpp",
    ".java", ".js", ".jsx", ".kt", ".kts", ".m", ".mjs", ".mm", ".php", ".py",
    ".rb", ".rs", ".sass", ".scss", ".svelte", ".swift", ".ts", ".tsx", ".vue",
})
_LIMIT_RELAXATION_FIELDS = frozenset({"limits", "exclude_paths", "creative_paths", "exclude_blender_scripts"})
_WILDCARD_SEGMENT_RE = re.compile(r"^[*?]+(?:\.[*?]+)?$")
_WILDCARD_EXT_FILE_RE = re.compile(r"^[*?]+(\.[a-z0-9_+.-]+)$")
_BROAD_CODE_ROOT_NAMES = frozenset({"src", "lib", "app", "apps", "packages", "pkg", "scripts", "source", "sources"})
_DEFAULT_BASE_BRANCH_REFS = ("origin/develop", "origin/main", "origin/master")
_LOCAL_DEFAULT_BRANCHES = ("develop", "main", "master")


def _default_git_run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=5)
        return {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
    except (OSError, subprocess.SubprocessError):
        return {"returncode": 1, "stdout": "", "stderr": ""}


def resolve_structure_config_base_ref(project: Path) -> tuple[str, str, bool]:
    """Resolve the merge-base with the protected/default branch, falling back to HEAD."""
    if not (project / ".git").exists():
        return "HEAD", "HEAD", True
    head_res = _default_git_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], project)
    current_branch = head_res.get("stdout", "").strip() if head_res.get("returncode") == 0 else ""
    candidates: list[str] = []
    origin_head = _default_git_run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], project)
    if origin_head.get("returncode") == 0 and origin_head.get("stdout", "").strip().startswith("refs/remotes/"):
        candidates.append(origin_head["stdout"].strip()[len("refs/remotes/") :])
    candidates.extend(_DEFAULT_BASE_BRANCH_REFS)
    candidates.extend(branch for branch in _LOCAL_DEFAULT_BRANCHES if branch != current_branch)
    for candidate in dict.fromkeys(c for c in candidates if c):
        verified = _default_git_run(["git", "rev-parse", "--verify", "--quiet", candidate], project)
        if verified.get("returncode") != 0 or not verified.get("stdout", "").strip():
            continue
        merge_base = _default_git_run(["git", "merge-base", "HEAD", candidate], project)
        base_sha = merge_base.get("stdout", "").strip() if merge_base.get("returncode") == 0 else ""
        if base_sha:
            return base_sha, candidate, False
    return "HEAD", "HEAD", True


def _read_git_blob(project: Path, ref: str, rel_path: str) -> str | None:
    if not (project / ".git").exists():
        return None
    result = _default_git_run(["git", "show", f"{ref}:{rel_path}"], project)
    return result.get("stdout") if result.get("returncode") == 0 and isinstance(result.get("stdout"), str) else None


def _read_target_config_text(project: Path, rel_path: str, head_ref: str | None) -> str | None:
    if head_ref is not None:
        return _read_git_blob(project, head_ref, rel_path)
    candidate = project / rel_path
    try:
        return candidate.read_text(encoding="utf-8") if candidate.is_file() else None
    except OSError:
        return None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalized_glob_parts(pattern: str) -> list[str]:
    normalized = pattern.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return [part for part in normalized.lstrip("/").split("/") if part and part != "."]


def _is_catchall_glob(pattern: str) -> bool:
    parts = _normalized_glob_parts(pattern)
    return not parts or all(_WILDCARD_SEGMENT_RE.fullmatch(part) for part in parts)


def _code_wide_glob_reason(pattern: str) -> str | None:
    parts = _normalized_glob_parts(pattern)
    if not parts:
        return "empty or catch-all pattern"
    tail_match = _WILDCARD_EXT_FILE_RE.fullmatch(parts[-1].lower())
    if tail_match and tail_match.group(1) in STRUCTURE_CODE_EXTENSIONS:
        prefix = parts[:-1]
        if all(_WILDCARD_SEGMENT_RE.fullmatch(part) for part in prefix):
            return f"repo-wide code extension match `{tail_match.group(1)}`"
        if prefix and prefix[0].lower() in _BROAD_CODE_ROOT_NAMES and all(_WILDCARD_SEGMENT_RE.fullmatch(p) for p in prefix[1:]):
            return f"broad code root `{prefix[0]}` match"
    if parts[0].lower() in _BROAD_CODE_ROOT_NAMES and len(parts) >= 2 and all(_WILDCARD_SEGMENT_RE.fullmatch(p) for p in parts[1:]):
        return f"broad code root `{parts[0]}` catch-all"
    return None


def _is_forbidden_exclude_pattern(pattern: str) -> str | None:
    if _is_catchall_glob(pattern):
        return f"catch-all pattern `{pattern}` cannot exclude repository files"
    lowered = pattern.strip().replace("\\", "/").lower()
    for ext in STRUCTURE_CODE_EXTENSIONS:
        if lowered.endswith(ext):
            return f"pattern `{pattern}` cannot exclude code extension `{ext}`"
    wide_reason = _code_wide_glob_reason(pattern)
    return f"pattern `{pattern}` cannot exclude {wide_reason}" if wide_reason else None


def is_forbidden_creative_pattern(pattern: str) -> str | None:
    """Reject catch-all and code-wide patterns in `creative_paths`."""
    if _is_catchall_glob(pattern):
        return f"catch-all pattern `{pattern}` cannot mark repository files as creative"
    wide_reason = _code_wide_glob_reason(pattern)
    return f"code-wide pattern `{pattern}` cannot mark {wide_reason} as creative" if wide_reason else None


def _parse_limits_block(raw_limits: Any, path_label: str, failures: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    if raw_limits is None:
        return limits
    if not isinstance(raw_limits, dict):
        failures.append(f"structure rules: {path_label} field `limits` must be a JSON object")
        return limits
    for key, value in raw_limits.items():
        if key not in ALLOWED_LIMIT_KEYS:
            failures.append(f"structure rules: {path_label} unknown limits key `{key}`")
            continue
        canonical = LIMIT_KEY_ALIASES.get(key, key)
        if type(value) is not int or value <= 0:
            failures.append(f"structure rules: {path_label} field `limits.{key}` must be a positive integer")
            continue
        cap = LIMIT_MAX_CAPS[canonical]
        if value > cap:
            failures.append(f"structure rules: {path_label} field `limits.{key}` ({value}) exceeds maximum allowed cap ({cap})")
            continue
        limits.setdefault(canonical, value)
    return limits


def _check_uncommitted_overrides(project: Path, base_payload: dict[str, Any] | None, failures: list[str]) -> None:
    moru_payload = _read_json_dict(project_state_dir_target(project) / "structure-rules.json")
    if moru_payload and (_LIMIT_RELAXATION_FIELDS & moru_payload.keys()):
        failures.append(
            "structure rules: .moru/structure-rules.json cannot configure structure "
            f"limits, exclude_paths, creative_paths, or exclude_blender_scripts; commit {DEFAULT_RULE_PATH} for human review"
        )
    override = os.environ.get("MORU_STRUCTURE_RULES", "").strip()
    override_payload = _read_json_dict(Path(override).expanduser()) if override else None
    if override_payload and (_LIMIT_RELAXATION_FIELDS & override_payload.keys()) and override_payload != base_payload:
        failures.append(
            "structure rules: MORU_STRUCTURE_RULES cannot override structure limits or exclusions beyond the committed base config"
        )


def load_structure_limits_config(
    project: Path,
    *,
    base_ref: str | None = None,
    head_ref: str | None = None,
    run_command: Callable[[list[str], Path], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Load validated repo-level structure limits from the committed review base only."""
    failures: list[str] = []
    limits: dict[str, Any] = {}
    exclude_paths: list[str] = []
    creative_paths: list[str] = []
    exclude_blender_scripts = False
    config_paths: list[str] = []

    resolved_base, base_label, base_fallback = (
        resolve_structure_config_base_ref(project) if base_ref is None else (base_ref, base_ref, False)
    )
    base_text = _read_git_blob(project, resolved_base, DEFAULT_RULE_PATH)
    target_text = _read_target_config_text(project, DEFAULT_RULE_PATH, head_ref)
    if (project / ".git").exists() and base_text != target_text:
        failures.append(
            f"structure rules: {DEFAULT_RULE_PATH} changed relative to base ({base_label}) "
            "and requires human review before modifying structure limits, exclusions, or rules"
        )

    base_payload: dict[str, Any] | None = None
    if base_text is not None:
        try:
            parsed = json.loads(base_text)
        except json.JSONDecodeError as error:
            failures.append(f"structure rules: {DEFAULT_RULE_PATH} at {base_label} is not valid JSON: {error}")
            parsed = None
        if parsed is not None and not isinstance(parsed, dict):
            failures.append(f"structure rules: {DEFAULT_RULE_PATH} at {base_label} must contain a JSON object")
        elif isinstance(parsed, dict):
            base_payload = parsed
            config_paths.append(DEFAULT_RULE_PATH)

    _check_uncommitted_overrides(project, base_payload, failures)

    if base_payload is not None:
        result_bucket: dict[str, Any] = {"failures": failures}
        limits = _parse_limits_block(base_payload.get("limits"), DEFAULT_RULE_PATH, failures)
        for field, validator, dest in (
            ("exclude_paths", _is_forbidden_exclude_pattern, exclude_paths),
            ("creative_paths", is_forbidden_creative_pattern, creative_paths),
        ):
            for pattern in string_list(base_payload.get(field), DEFAULT_RULE_PATH, field, result_bucket):
                problem = validator(pattern)
                if problem:
                    failures.append(f"structure rules: {DEFAULT_RULE_PATH} {field} {problem}")
                else:
                    dest.append(pattern)
        raw_blender = base_payload.get("exclude_blender_scripts")
        if raw_blender is not None:
            if type(raw_blender) is not bool:
                failures.append(f"structure rules: {DEFAULT_RULE_PATH} field `exclude_blender_scripts` must be a boolean")
            else:
                exclude_blender_scripts = raw_blender

    return {
        "limits": limits,
        "exclude_paths": list(dict.fromkeys(exclude_paths)),
        "creative_paths": list(dict.fromkeys(creative_paths)),
        "exclude_blender_scripts": exclude_blender_scripts,
        "config_paths": config_paths,
        "config_base_ref": resolved_base,
        "config_base_label": base_label,
        "config_base_fallback": base_fallback,
        "config_present": base_text is not None or target_text is not None,
    }, failures


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
