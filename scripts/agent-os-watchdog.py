#!/usr/bin/env python3
"""Bounded watchdog for stale Moru Core runs and tasks.

The default is one pass so callers can schedule it from launchd/cron. A bounded
multi-pass mode is available for an operator process; this script never creates
an unbounded background daemon by itself.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent_os_maintenance import run_maintenance


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Moru Core stale-state watchdog")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--stale-after-seconds", type=int, default=3600)
    parser.add_argument("--retention-seconds", type=int, default=30 * 24 * 60 * 60)
    parser.add_argument("--max-records", type=int, default=100)
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--max-cycles", type=int, default=1)
    args = parser.parse_args()
    if args.max_cycles < 1 or args.interval_seconds < 0:
        parser.error("max-cycles must be positive and interval-seconds cannot be negative")
    results = []
    for index in range(args.max_cycles):
        results.append(run_maintenance(
            args.project,
            stale_after_seconds=args.stale_after_seconds,
            retention_seconds=args.retention_seconds,
            max_records=args.max_records,
        ))
        if index + 1 < args.max_cycles:
            time.sleep(args.interval_seconds)
    print(json.dumps({"cycles": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
