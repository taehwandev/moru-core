#!/usr/bin/env python3
"""Measure old all-pairs upkeep versus bounded startup hints; no model/store I/O."""

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_project_memory import _digest, recall_lines
import agent_project_memory_consolidate as upkeep


def render(records, fast):
    lines = recall_lines(ROOT, "task", records=records, request="queue delivery")
    if fast:
        notice = upkeep.startup_summary_line(records, ROOT, "moru-hook", today=date.today())
    else:
        notice = upkeep.summary_line(upkeep.findings(records, 0, today=date.today(), within_days=0),
                                     ROOT, "moru-hook")
    return lines + ([notice] if notice else [])


def measure(records, samples):
    assert render(records, False) == render(records, True), "advice/notice parity failed"
    times = {"baseline": [], "candidate": []}
    for sample in range(samples):
        for fast in ((False, True) if sample % 2 == 0 else (True, False)):
            start = time.perf_counter()
            render(records, fast)
            times["candidate" if fast else "baseline"].append((time.perf_counter() - start) * 1000)
    comparisons = {"baseline": 0, "candidate": 0}
    original = upkeep._jaccard
    for fast, label in ((False, "baseline"), (True, "candidate")):
        def counted(left, right):
            comparisons[label] += 1
            return original(left, right)
        upkeep._jaccard = counted
        try:
            render(records, fast)
        finally:
            upkeep._jaccard = original
    return {"records": len(records), "pairwise_calls": comparisons,
            "milliseconds": {label: {"median": statistics.median(values),
                "p95": sorted(values)[math.ceil(len(values) * .95) - 1], "samples": values}
                for label, values in times.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 3000])
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if args.samples < 1 or any(size < 1 for size in args.sizes):
        parser.error("sizes and samples must be positive")
    results = []
    for size in args.sizes:
        records = []
        for n in range(size):
            body = "queue delivery preserves event identity" if n == 0 else f"topic{n}a topic{n}b topic{n}c"
            record = dict(schema_version=1, id=f"{n + 1:016x}", body=body, source=f"fixture{n}",
                          scope="all", status="active", review_on="2099-01-01")
            record["digest"] = _digest(record)
            records.append(record)
        results.append(measure(records, args.samples))
    print(json.dumps({"measurement": (
        "In-memory startup references and upkeep only; excludes JSON scan, lifecycle, inference "
        "and network; unchanged recall; fuzzy consolidation remains on demand"),
        "python": platform.python_version(), "platform": platform.platform(),
        "candidate_sha256": hashlib.sha256(Path(upkeep.__file__).read_bytes()).hexdigest(),
        "baseline": "unchanged findings(within_days=0) + summary_line from baseline197d3b4e",
        "samples_per_variant": args.samples, "results": results}, indent=2))


if __name__ == "__main__":
    main()
