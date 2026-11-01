#!/usr/bin/env python3
"""Paired before/after inspection callbacks with native and Python evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import statistics
import tempfile
import time

from benchmark_native_sha import capture, validate
from benchmark_project_discovery import digest, summary
from discovery_process_measure import run_measured
from native_pretool_support import PROJECT
from read_inspection_support import cache_hashes, case_environment, comparable, fixtures, prepare_cache, state_hashes


def measure(reference, output, count, budget, prepare_bytecode=False):
    if platform.system() != "Darwin":
        raise RuntimeError("BSD time RSS measurement requires macOS")
    reference = reference.resolve()
    roots = {"reference": reference, "candidate": reference.parent / "candidate"}
    if roots["candidate"].exists():
        raise RuntimeError("preserve the candidate snapshot; select a new experiment directory")
    capture(roots["candidate"])
    identities = {v: validate(root) for v, root in roots.items()}
    utilities = ("tests/benchmark_read_inspection.py", "tests/read_inspection_support.py",
                 "tests/benchmark_native_sha.py", "tests/discovery_process_measure.py",
                 "tests/runtime_snapshot_normalize.py", "tests/native_launcher_support.py",
                 "tests/native_pretool_support.py", "tests/benchmark_project_discovery.py")
    report = {"status": "running", "platform": platform.platform(), "samples_per_variant": count,
        "method": "balanced serial generated entrypoints, warm filesystem, bytecode writes disabled, build/setup excluded, unreserved host",
        "bytecode_prepared": prepare_bytecode,
        "variants": identities, "utility_sha256": {p: digest(PROJECT / p) for p in utilities},
        "cases": {}, "budget_seconds": budget}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="read-inspection-") as tmp:
            base = Path(tmp).resolve()
            project, entries, envs, cases = fixtures(base, roots)
            if prepare_bytecode:
                report["cache_hits"] = prepare_cache(base, entries, envs, cases, project)
            bytecode = cache_hashes(base)
            report["bytecode_sha256"] = bytecode
            before = state_hashes(base, project)
            started = time.monotonic()
            deadline = started + budget
            rng = random.Random(71042)
            for name, args, data in cases:
                rows = {v: [] for v in roots}
                report["cases"][name] = {"complete": False, "samples": rows}
                orders = [["reference", "candidate"], ["candidate", "reference"]] * (count // 2)
                rng.shuffle(orders)
                expected = None
                for warm, order in [(True, list(roots)), *[(False, order) for order in orders]]:
                    for variant in order:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            raise TimeoutError("inspection timing budget exhausted")
                        metrics_file = base / "metrics.txt"
                        done, metrics = run_measured(["/usr/bin/time", "-l", "-o", str(metrics_file),
                            str(entries[variant]), *args], cwd=project,
                            env=case_environment(base, envs[variant], name, variant),
                            input_bytes=data, timeout=min(10, left))
                        value = comparable(done, name)
                        expected = value if expected is None else expected
                        if value != expected:
                            raise RuntimeError("before/after output differs")
                        rss = re.findall(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$", metrics_file.read_text())
                        if len(rss) != 1:
                            raise RuntimeError("invalid BSD time RSS output")
                        metrics["peak_rss_bytes"] = int(rss[0])
                        if not warm:
                            rows[variant].append(metrics)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                fields = {v: {key: ({"median_bytes": statistics.median(r[key] for r in values),
                    "p95_bytes": sorted(r[key] for r in values)[(95 * len(values) + 99) // 100 - 1]}
                    if key == "peak_rss_bytes" else summary([r[key] for r in values]))
                    for key in values[0]} for v, values in rows.items()}
                report["cases"][name].update(complete=True, summary=fields,
                    output_sha256=hashlib.sha256(expected).hexdigest())
                print(json.dumps({name: {v: {k: {n: value for n, value in item.items() if not n.startswith("samples_")}
                    for k, item in f.items() if k in ("wall_ms", "cpu_ms", "peak_rss_bytes")}
                    for v, f in fields.items()}}), flush=True)
            after = state_hashes(base, project)
            if before != after:
                raise RuntimeError("fixture state changed during read measurement")
            if cache_hashes(base) != bytecode:
                raise RuntimeError("bytecode changed during measurement")
            report.update(state_sha256=before, state_unchanged=True,
                          elapsed_seconds=time.monotonic() - started, status="complete")
        for variant, root in roots.items():
            if validate(root) != identities[variant]:
                raise RuntimeError("source or binary changed during measurement")
    except Exception as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--budget-seconds", type=float, default=90)
    parser.add_argument("--prepare-bytecode", action="store_true")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("use an even sample count >=24")
    measure(args.reference, args.output, args.samples, args.budget_seconds, args.prepare_bytecode)
