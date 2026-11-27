from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from figma_manifest import _probe_manifest, build_manifest
from figma_markdown import render_markdown
from figma_util import write_json
from figma_summary_validate import validate_summary


class FigmaBundleOutput:
    """Persist portable bundle output and report its local artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_directories(self) -> tuple[Path, Path, Path]:
        directories = self.root / "raw", self.root / "frames", self.root / "summary"
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        return directories

    def portable_paths(self, paths: dict[str, str]) -> dict[str, str]:
        root = self.root.resolve()
        result: dict[str, str] = {}
        for node_id, raw_path in paths.items():
            try:
                result[node_id] = Path(raw_path).resolve().relative_to(root).as_posix()
            except ValueError as error:
                raise RuntimeError(
                    f"Generated file escaped the bundle root for node {node_id}."
                ) from error
        return result

    def persist(
        self,
        summary: dict[str, Any],
        warnings: list[str],
        args: Any,
    ) -> list[str]:
        prepared = None
        if type(warnings) is list and all(type(warning) is str for warning in warnings):
            prepared = _probe_manifest(summary, args, prepare=True, warnings=warnings)
        problems = validate_summary(summary) if prepared is None else prepared["problems"]
        summary["warnings"] = warnings + [f"schema: {problem}" for problem in problems]
        summary_dir = self.root / "summary"
        native_json = prepared is not None and "summary_json" in prepared
        if native_json:
            (summary_dir / "design-summary.json").write_text(prepared["summary_json"], encoding="utf-8")
        else:
            write_json(summary_dir / "design-summary.json", summary)
        sections = {name: prepared[f"markdown_{name}"] for name in ("overview", "tokens", "candidates", "layout")
                    if prepared is not None and f"markdown_{name}" in prepared}
        markdown = render_markdown(summary, **sections)
        (summary_dir / "design-handoff.md").write_text(markdown, encoding="utf-8")
        if native_json:
            (self.root / "manifest.json").write_text(prepared["manifest_json"], encoding="utf-8")
        else:
            manifest = build_manifest(summary, args) if prepared is None else prepared["manifest"]
            write_json(self.root / "manifest.json", manifest)
        return problems

    def report(
        self,
        image_paths: dict[str, str],
        asset_paths: dict[str, str],
        warnings: list[str],
        problems: list[str],
    ) -> None:
        if problems:
            print(f"WARNING: design-summary.json failed {len(problems)} schema check(s).", file=sys.stderr)
        summary_dir = self.root / "summary"
        print(f"Created Figma handoff bundle: {self.root}")
        print(f"- {summary_dir / 'design-handoff.md'}")
        print(f"- {summary_dir / 'design-summary.json'}")
        if image_paths:
            print(f"- {self.root / 'frames'} ({len(image_paths)} rendered frame files)")
        if asset_paths:
            print(f"- {self.root / 'assets'} ({len(asset_paths)} rendered asset files)")
        if warnings:
            print(f"Warnings: {len(warnings)}. See design-handoff.md.")
