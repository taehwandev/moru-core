#!/usr/bin/env python3
"""Discover the target project for an Moru Core-guided task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_project_discovery import discover_projects, format_discovery_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover a target project without editing it.")
    parser.add_argument("--request", required=True, help="Current user request text.")
    parser.add_argument("--cwd", default=str(Path.cwd()), help="Runtime current working directory.")
    parser.add_argument("--registry", help="Project registry JSON path. Defaults to ~/.tao/projects.json.")
    parser.add_argument("--search-root", action="append", default=[], help="Additional directory to scan.")
    parser.add_argument("--max-depth", type=int, default=2, help="Maximum search-root scan depth.")
    parser.add_argument("--include-default-search-roots", action="store_true", help="Also scan common home child directories such as ~/Documents and ~/Downloads.")
    parser.add_argument("--no-default-search-roots", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    result = discover_projects(
        args.request,
        Path(args.cwd),
        search_roots=[Path(item) for item in args.search_root],
        registry_path=Path(args.registry) if args.registry else None,
        max_depth=args.max_depth,
        include_default_search_roots=args.include_default_search_roots and not args.no_default_search_roots,
    )
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_discovery_text(result))
    if result.status == "selected":
        return 0
    if result.status == "ambiguous":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
