#!/usr/bin/env python3
"""Print the content-free Moru Core runtime status snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Moru Core runtime status")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--validate", action="store_true", help="validate the external status contract")
    parser.add_argument("--efficiency-trends", action="store_true", help="report content-free run efficiency and cohort trends")
    parser.add_argument("--all-projects", action="store_true", help="aggregate across governed projects under --workspace-root")
    parser.add_argument("--workspace-root", type=Path, default=Path.home() / "git", help="workspace root for --all-projects")
    parser.add_argument("--month", default="", help="optional YYYY-MM prefix filter for efficiency trends")
    parser.add_argument("--spill-db", type=Path, default=None, help="override Spill events.sqlite3 path")
    parser.add_argument("--codex-db", type=Path, default=None, help="override Codex state_5.sqlite path")
    args = parser.parse_args()
    from agent_observability import discover_governed_projects, efficiency_trend_snapshot, status_snapshot

    if args.efficiency_trends:
        projects = discover_governed_projects(args.workspace_root) if args.all_projects else [args.project]
        trends = efficiency_trend_snapshot(
            projects,
            spill_db=args.spill_db,
            codex_db=args.codex_db,
            month=args.month,
        )
        print(json.dumps(trends, ensure_ascii=False, sort_keys=True))
        return 0
    snapshot = status_snapshot(args.project)
    if args.validate:
        from agent_os_api import validate_status_snapshot

        failures = validate_status_snapshot(snapshot)
        print(json.dumps({"valid": not failures, "failures": failures, "snapshot": snapshot}, ensure_ascii=False, sort_keys=True))
        return 0 if not failures else 1
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
