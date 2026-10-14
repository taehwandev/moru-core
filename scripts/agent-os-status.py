#!/usr/bin/env python3
"""Print the content-free Moru Core runtime status snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_observability import status_snapshot
from agent_os_api import validate_status_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Moru Core runtime status")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--validate", action="store_true", help="validate the external status contract")
    args = parser.parse_args()
    snapshot = status_snapshot(args.project)
    if args.validate:
        failures = validate_status_snapshot(snapshot)
        print(json.dumps({"valid": not failures, "failures": failures, "snapshot": snapshot}, ensure_ascii=False, sort_keys=True))
        return 0 if not failures else 1
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
