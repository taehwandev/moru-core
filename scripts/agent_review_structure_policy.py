"""Repo-configured structural path exclusion, creative opt-in, and limit resolution.

owner: structure review path exclusion and repo limit policy resolution
allowed imports: standard library, agent_structure_imports, agent_structure_rule_config
forbidden imports: lifecycle writers, git mutations, review hook emitters
callers/tests: scripts/agent_review_structure.py, scripts/agent_review_hook.py; tests/test_agent_structure_limits_config.py
verification: code extensions are never excluded by exclude_paths and opt-in policies apply only from committed review base
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_structure_imports import matches_any
from agent_structure_rule_config import (
    DEFAULT_CHANGED_PATHS_LIMIT,
    DEFAULT_RULE_PATH,
    STRUCTURE_CODE_EXTENSIONS,
    is_forbidden_creative_pattern,
    load_structure_limits_config,
)

CommandRunner = Callable[[list[str], Path], dict[str, Any]]

REVIEW_ASSET_BINARY_EXTENSIONS = frozenset({
    ".3ds", ".abc", ".avi", ".basis", ".bin", ".blend", ".blend1", ".bmp",
    ".class", ".dae", ".db", ".dds", ".dll", ".dylib", ".eot", ".exr",
    ".fbx", ".flac", ".gif", ".glb", ".gltf", ".gz", ".hdr", ".icns",
    ".ico", ".jar", ".jpeg", ".jpg", ".ktx", ".ktx2", ".m4a", ".mkv",
    ".mov", ".mp3", ".mp4", ".mtl", ".o", ".obj", ".ogg", ".otf", ".pdf",
    ".ply", ".png", ".pyc", ".pyo", ".so", ".sqlite", ".sqlite3", ".stl",
    ".svg", ".tar", ".tga", ".tif", ".tiff", ".ttf", ".usd", ".usda",
    ".usdc", ".usdz", ".wasm", ".wav", ".webm", ".webp", ".woff", ".woff2",
    ".xz", ".zip", ".7z",
})


def is_excluded_asset_or_build_script(
    path: Path | str,
    exclude_patterns: list[str] | tuple[str, ...] = (),
    *,
    exclude_blender_scripts: bool = False,
) -> bool:
    """Exclude binary/3D assets, repo-opted-in Blender scripts, and non-code repo excludes.

    `exclude_paths` never excludes code extensions in STRUCTURE_CODE_EXTENSIONS.
    Blender script exclusion (`tools/blender/**`, `scripts/blender/**`, `blender/**`)
    applies only when the repo's committed base config opts in via `exclude_blender_scripts`.
    """
    candidate = path if isinstance(path, Path) else Path(path)
    suffix = candidate.suffix.lower()
    if suffix in REVIEW_ASSET_BINARY_EXTENSIONS:
        return True
    if exclude_blender_scripts:
        lower_parts = tuple(part.lower() for part in candidate.parts)
        if (
            lower_parts[:2] in {("tools", "blender"), ("scripts", "blender")}
            or lower_parts[:1] == ("blender",)
        ):
            return True
    if suffix in STRUCTURE_CODE_EXTENSIONS:
        return False
    if exclude_patterns and matches_any(candidate.as_posix(), list(exclude_patterns)):
        return True
    return False


def is_creative_source_path(
    path: Path | str,
    creative_patterns: list[str] | tuple[str, ...] = (),
) -> bool:
    """Whether a new oversized file/function in `path` warns via explicit repo `creative_paths`."""
    safe_patterns = [
        pattern for pattern in creative_patterns if is_forbidden_creative_pattern(pattern) is None
    ]
    if not safe_patterns:
        return False
    candidate = path if isinstance(path, Path) else Path(path)
    return matches_any(candidate.as_posix(), safe_patterns)


def _relaxed_config_keys(
    cfg: dict[str, Any],
    *,
    eff_file: int,
    eff_block: int,
    eff_added: int,
    public_owner_limit: int,
    visible_owner_limit: int,
    new_file_pressure_limit: int,
    default_file_lines: int,
    default_block_lines: int,
    default_added_lines: int,
    default_public_owners: int,
    default_visible_owners: int,
    default_new_file_pressure: int,
) -> list[str]:
    relaxed: list[str] = []
    limits = cfg["limits"]
    checks = (
        ("limits.max_source_file_lines", eff_file, default_file_lines),
        ("limits.max_function_lines", eff_block, default_block_lines),
        ("limits.max_added_lines", eff_added, default_added_lines),
        ("limits.max_public_owners", public_owner_limit, default_public_owners),
        ("limits.max_visible_owners", visible_owner_limit, default_visible_owners),
        (
            "limits.new_source_file_pressure_limit",
            new_file_pressure_limit,
            default_new_file_pressure,
        ),
    )
    for label, current, default in checks:
        if current != default:
            relaxed.append(f"{label}={current} (default {default})")
    if "max_changed_paths" in limits and limits["max_changed_paths"] != DEFAULT_CHANGED_PATHS_LIMIT:
        relaxed.append(
            f"limits.max_changed_paths={limits['max_changed_paths']} "
            f"(default {DEFAULT_CHANGED_PATHS_LIMIT})"
        )
    if cfg["exclude_paths"]:
        relaxed.append(f"exclude_paths={','.join(cfg['exclude_paths'])}")
    if cfg["creative_paths"]:
        relaxed.append(f"creative_paths={','.join(cfg['creative_paths'])}")
    if cfg.get("exclude_blender_scripts"):
        relaxed.append("exclude_blender_scripts=true")
    return relaxed


def resolve_repo_structure_policy(
    project: Path,
    max_file_lines: int,
    max_block_lines: int,
    max_added_lines: int,
    *,
    default_file_lines: int,
    default_block_lines: int,
    default_added_lines: int,
    default_public_owners: int,
    default_visible_owners: int,
    default_new_file_pressure: int,
    run_command: CommandRunner,
    review_commits: tuple[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    base_ref = review_commits[0] if review_commits is not None else None
    head_ref = review_commits[1] if review_commits is not None else None
    cfg, failures = load_structure_limits_config(
        project,
        base_ref=base_ref,
        head_ref=head_ref,
        run_command=run_command,
    )
    limits = cfg["limits"]
    eff_file = (
        limits["max_source_file_lines"]
        if "max_source_file_lines" in limits and max_file_lines == default_file_lines
        else max_file_lines
    )
    eff_block = (
        limits["max_function_lines"]
        if "max_function_lines" in limits and max_block_lines == default_block_lines
        else max_block_lines
    )
    eff_added = (
        limits["max_added_lines"]
        if "max_added_lines" in limits and max_added_lines == default_added_lines
        else max_added_lines
    )
    public_owner_limit = limits.get("max_public_owners", default_public_owners)
    visible_owner_limit = limits.get("max_visible_owners", default_visible_owners)
    new_file_pressure_limit = limits.get(
        "new_source_file_pressure_limit", default_new_file_pressure
    )
    relaxed_keys = _relaxed_config_keys(
        cfg,
        eff_file=eff_file,
        eff_block=eff_block,
        eff_added=eff_added,
        public_owner_limit=public_owner_limit,
        visible_owner_limit=visible_owner_limit,
        new_file_pressure_limit=new_file_pressure_limit,
        default_file_lines=default_file_lines,
        default_block_lines=default_block_lines,
        default_added_lines=default_added_lines,
        default_public_owners=default_public_owners,
        default_visible_owners=default_visible_owners,
        default_new_file_pressure=default_new_file_pressure,
    )
    warnings: list[str] = []
    if cfg.get("config_base_fallback") and cfg.get("config_present"):
        warnings.append(
            f"structure rules: no protected/default branch merge-base found; loaded "
            f"{DEFAULT_RULE_PATH} from HEAD fallback"
        )
    if relaxed_keys:
        warnings.append(
            "structure rules: effective config differs from Moru defaults ("
            + "; ".join(relaxed_keys)
            + "); structure-review-evidence is required"
        )
    policy = {
        "max_file_lines": eff_file,
        "max_block_lines": eff_block,
        "max_added_lines": eff_added,
        "public_owner_limit": public_owner_limit,
        "visible_owner_limit": visible_owner_limit,
        "new_file_pressure_limit": new_file_pressure_limit,
        "exclude_paths": cfg["exclude_paths"],
        "creative_paths": cfg["creative_paths"],
        "exclude_blender_scripts": bool(cfg.get("exclude_blender_scripts", False)),
        "repo_configured_limits": dict(limits),
        "relaxed_keys": relaxed_keys,
        "config_base_ref": cfg.get("config_base_ref", "HEAD"),
        "config_base_label": cfg.get("config_base_label", "HEAD"),
        "config_base_fallback": bool(cfg.get("config_base_fallback", False)),
        "warnings": warnings,
    }
    return policy, failures
