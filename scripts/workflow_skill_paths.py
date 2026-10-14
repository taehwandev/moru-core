"""Canonical Moru Core skill-bundle paths."""

from __future__ import annotations

from pathlib import Path


def canonical_doc_path(path: str) -> str:
    """Return the SKILL.md entrypoint for migrated flat guidance docs."""
    if path.endswith("/SKILL.md"):
        return path
    source = Path(path)
    if source.suffix != ".md":
        return path
    parts = source.parts
    if len(parts) == 2 and parts[0] == "common":
        return f"common/skills/{source.stem}/SKILL.md"
    if len(parts) == 2 and parts[0] == "workflows" and source.name != "README.md":
        return f"workflows/skills/{source.stem}/SKILL.md"
    if len(parts) == 2 and parts[0] == "product-patterns":
        return f"product-patterns/skills/{source.stem}/SKILL.md"
    if len(parts) == 3 and parts[0] == "platforms":
        return f"platforms/{parts[1]}/skills/{source.stem}/SKILL.md"
    if len(parts) == 2 and parts[0] == "docs":
        return f"docs/skills/{source.stem}/SKILL.md"
    return path


def guidance_reference_path(path: str) -> str:
    """Return the detailed reference path for a migrated flat guidance doc."""
    skill = Path(canonical_doc_path(path))
    if skill.name != "SKILL.md":
        return path
    return str(skill.parent / "references" / "current-guidance.md")
