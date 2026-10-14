"""Codex permission-profile setup owned by Moru Core."""

from __future__ import annotations

import json
import re
from pathlib import Path


MORU_WORKSPACE_PROFILE = "moru-workspace"
# The profile name setup wrote before the Moru rename.
LEGACY_WORKSPACE_PROFILE = "tao-workspace"
_TABLE_HEADER = re.compile(r"(?m)^[ \t]*\[([^\]\n]+)\][ \t]*(?:#.*)?$")
# Where the top level ends: a `[table]` or an `[[array.of.tables]]`. A key under
# either one is nested, so the reset must never read it as the top-level selection.
_TOP_LEVEL_END = re.compile(r"(?m)^[ \t]*\[\[?[^\]\n]+\]\]?[ \t]*(?:#.*)?$")


def reset_moru_permission_default(target: Path, dry_run: bool) -> str:
    """Reset Moru selection to the built-in workspace default, preserving profiles."""
    if not target.exists():
        return "ok"
    original = target.read_text(encoding="utf-8")
    header = _TOP_LEVEL_END.search(original)
    top = original[:header.start()] if header else original
    pattern = re.compile(
        r"(?m)^[ \t]*default_permissions[ \t]*=[ \t]*"
        r"(['\"])(?:moru|tao)-workspace\1[ \t]*(?:#[^\n]*)?(?:\n|$)"
    )
    matches = list(pattern.finditer(top))
    count = _assignment_count(top, "default_permissions")
    has_profiles = any(h.group(1).strip().startswith("permissions.") for h in _TABLE_HEADER.finditer(original))
    if not matches and (count or not has_profiles):
        return "ok"
    if matches and count != 1:
        raise ValueError("Ambiguous default_permissions; configuration was not changed")
    if dry_run:
        return "would_update"
    default = 'default_permissions = ":workspace"\n'
    if matches:
        match = matches[0]
        updated = original[:match.start()] + default + original[match.end():]
    else:
        updated = default + original
    if target.read_text(encoding="utf-8") != original:
        raise ValueError("Concurrent Codex configuration change; retry after inspection")
    target.write_text(updated, encoding="utf-8")
    return "installed"


def merge_codex_worktree_roots(
    target: Path,
    roots: list[Path],
    dry_run: bool,
) -> str:
    """Add an optional Moru profile without selecting the user's permission policy."""

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    header = _TOP_LEVEL_END.search(original)
    top = original[:header.start()] if header else original
    if not _assignment_count(top, "default_permissions"):
        if any(h.group(1).strip().startswith("permissions.") for h in _TABLE_HEADER.finditer(original)):
            return "missing"
        return "ok: optional Moru profile skipped because no default_permissions is selected"
    root_strings = list(dict.fromkeys(str(root.expanduser().resolve()) for root in roots))
    # A configuration that selects the pre-rename profile keeps it, so the
    # selection never points at a profile that no longer exists.
    profile = LEGACY_WORKSPACE_PROFILE if _selects_legacy_profile(original) else MORU_WORKSPACE_PROFILE
    if _permission_ownership_conflicts(original, root_strings, profile):
        return "missing"

    updated = _rename_legacy_profile(original)
    updated = _ensure_workspace_profile(updated, profile)
    updated = _ensure_worktree_roots(updated, root_strings, profile)
    if updated == original:
        return "ok"
    if dry_run:
        return "missing"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return "installed"


def _selects_legacy_profile(text: str) -> bool:
    return bool(re.search(
        rf"(?m)^[ \t]*default_permissions[ \t]*=[ \t]*(['\"]){LEGACY_WORKSPACE_PROFILE}\1", text
    ))


def _permission_ownership_conflicts(text: str, roots: list[str], name: str) -> bool:
    profile = _section(text, f"permissions.{name}")
    if profile:
        body = text[profile[0] : profile[1]]
        extensions = _quoted_values(body, "extends")
        if _assignment_count(body, "extends") != len(extensions):
            return True
        if len(extensions) > 1 or (extensions and extensions[0] != ":workspace"):
            return True

    roots_section = _section(text, f"permissions.{name}.workspace_roots")
    if not roots_section:
        return False
    body = text[roots_section[0] : roots_section[1]]
    for root in roots:
        values = re.findall(
            rf"(?m)^[ \t]*{re.escape(_toml_key(root))}[ \t]*=[ \t]*(true|false)[ \t]*(?:#.*)?$",
            body,
        )
        if len(values) > 1 or (values and values[0] != "true"):
            return True
    return False


def _rename_legacy_profile(text: str) -> str:
    """Carry the pre-rename profile's tables over under the Moru name.

    Only when nothing selects the old name and no Moru profile exists yet, so a
    configuration a user points at keeps resolving and nothing is duplicated.
    """
    legacy = f"permissions.{LEGACY_WORKSPACE_PROFILE}"
    if _section(text, f"permissions.{MORU_WORKSPACE_PROFILE}") or not _section(text, legacy):
        return text
    if _selects_legacy_profile(text):
        return text
    header = re.compile(rf"(?m)^([ \t]*\[){re.escape(legacy)}((?:\.[^\]\n]+)?\][ \t]*(?:#.*)?)$")
    renamed = header.sub(
        lambda match: f"{match.group(1)}permissions.{MORU_WORKSPACE_PROFILE}{match.group(2)}", text
    )
    return renamed.replace(
        'description = "Workspace access plus the shared Tao Agent OS runtime."',
        'description = "Workspace access plus the shared Moru Core runtime."',
    )


def _ensure_workspace_profile(text: str, name: str) -> str:
    updated = text
    profile = _section(updated, f"permissions.{name}")
    if not profile:
        return _append_block(
            updated,
            "\n".join(
                (
                    f"[permissions.{name}]",
                    'description = "Workspace access plus the shared Moru Core runtime."',
                    'extends = ":workspace"',
                )
            ),
        )
    if not _quoted_values(updated[profile[0] : profile[1]], "extends"):
        return _insert_section_line(updated, profile[1], 'extends = ":workspace"')
    return updated


def _ensure_worktree_roots(text: str, roots: list[str], name: str) -> str:
    roots_section = _section(text, f"permissions.{name}.workspace_roots")
    if not roots_section:
        block = [f"[permissions.{name}.workspace_roots]"]
        block += [f"{_toml_key(root)} = true" for root in roots]
        return _append_block(text, "\n".join(block))

    body = text[roots_section[0] : roots_section[1]]
    missing = [
        root
        for root in roots
        if not re.search(
            rf"(?m)^[ \t]*{re.escape(_toml_key(root))}[ \t]*=",
            body,
        )
    ]
    if not missing:
        return text
    lines = "\n".join(f"{_toml_key(root)} = true" for root in missing)
    return _insert_section_line(text, roots_section[1], lines)


def _quoted_values(text: str, key: str) -> list[str]:
    return re.findall(
        rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"([^"]+)"[ \t]*(?:#.*)?$',
        text,
    )


def _assignment_count(text: str, key: str) -> int:
    return len(
        re.findall(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=", text)
    )


def _toml_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _section(text: str, name: str) -> tuple[int, int] | None:
    headers = list(_TABLE_HEADER.finditer(text))
    for index, header in enumerate(headers):
        if header.group(1).strip() != name:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        return header.end(), end
    return None


def _append_block(text: str, block: str) -> str:
    separator = "" if not text else "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{separator}{block}\n"


def _insert_section_line(text: str, index: int, line: str) -> str:
    before = text[:index]
    after = text[index:]
    prefix = "" if not before or before.endswith("\n") else "\n"
    suffix = "" if not after or after.startswith("\n") else "\n"
    return f"{before}{prefix}{line}\n{suffix}{after}"
