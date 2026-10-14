#!/usr/bin/env python3
"""Build a startup manifest for Moru Core-aware agent runtimes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_project_discovery import build_entry_manifest, format_entry_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve project entry context for a runtime bridge.")
    parser.add_argument("--request", required=True, help="Current user request text.")
    parser.add_argument("--cwd", default=str(Path.cwd()), help="Runtime current working directory.")
    parser.add_argument(
        "--runtime",
        choices=("codex", "claude", "antigravity", "generic"),
        default="generic",
        help="Runtime requesting the entry manifest.",
    )
    parser.add_argument("--command", default="task", help="Moru Core workflow command hint.")
    parser.add_argument("--registry", help="Project registry JSON path. Defaults to ~/.tao/projects.json.")
    parser.add_argument("--search-root", action="append", default=[], help="Additional directory to scan.")
    parser.add_argument("--max-depth", type=int, default=2, help="Maximum search-root scan depth.")
    parser.add_argument("--include-default-search-roots", action="store_true", help="Also scan common home child directories such as ~/Documents and ~/Downloads.")
    parser.add_argument("--no-default-search-roots", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_entry_manifest(
        args.request,
        Path(args.cwd),
        runtime=args.runtime,
        command=args.command,
        search_roots=[Path(item) for item in args.search_root],
        registry_path=Path(args.registry) if args.registry else None,
        max_depth=args.max_depth,
        include_default_search_roots=args.include_default_search_roots and not args.no_default_search_roots,
    )
    if args.format == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(format_entry_text(manifest))
    if manifest["status"] == "selected":
        return 0
    if manifest["status"] == "ambiguous":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
