#!/usr/bin/env python3
"""Frozen original/new generated status entrypoints with real Python-cache proof."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import statistics
import subprocess
import tempfile
import time

from benchmark_native_sha import capture, validate
from benchmark_project_discovery import digest, summary
from discovery_process_measure import run_measured
from native_pretool_support import PROJECT, encode, request
from native_runtime_status_support import install_snapshot, prepared, state_hashes
from read_inspection_support import cache_hashes, prepare_cache
from runtime_snapshot_normalize import normalize_output


def normalized(done, name):
    if done.returncode or done.stderr:
        raise RuntimeError(f"status callback failed: {name}: {done.returncode}, {done.stderr!r}")
    if name == "native_cat_control":
        if done.stdout:
            raise RuntimeError("quiet pretool emitted output")
        return done.stdout
    return normalize_output(done.stdout, "validated_status" if name.startswith("validated") else "status")


def fixtures(base, roots, selected=None):
    _entry, small = prepared(base, roots["reference"])
    (small / "notes.txt").write_text("TODO synthetic\n")
    large = base / "large-project"
    (large / ".moru").mkdir(parents=True)
    for name, value in {
        "run-registry.json": {"runs": [{"state": "running" if n % 2 else "completed"} for n in range(100)]},
        "scheduler.json": {"tasks": [{"state": ("queued", "running", "completed", "failed")[n % 4]} for n in range(200)]},
        "events.json": {"events": [{"event_type": "run.started" if n % 2 else "task.completed"} for n in range(500)]},
    }.items():
        (large / ".moru" / name).write_text(json.dumps(value))
    unusual = base / "unusual-project"
    (unusual / ".moru").mkdir(parents=True)
    (unusual / ".moru/scheduler.json").write_text(json.dumps({"tasks": [{"state": 7}]}))
    entries, envs = {}, {}
    for variant, root in roots.items():
        entries[variant], envs[variant] = install_snapshot(base, base / ("home-" + variant), root)
    cases = [("status", ["agent-os-status", "--project", str(small)], b""),
             ("validated_status", ["agent-os-status", "--project", str(small), "--validate"], b""),
             ("status_large", ["agent-os-status", "--project", str(large)], b""),
             ("validated_large", ["agent-os-status", "--project", str(large), "--validate"], b""),
             ("relative_fallback", ["agent-os-status", "--project", "."], b""),
             ("numeric_fallback", ["agent-os-status", "--project", str(unusual)], b""),
             ("native_cat_control", ["claude-pretool-gate"], encode(request(small, "cat notes.txt")))]
    if selected:
        if set(selected) - {name for name, _args, _data in cases}:
            raise RuntimeError("unknown selected workload")
        cases = [case for case in cases if case[0] in selected]
    cache_cases = [("native_cat_control" if name == "native_cat_control" else
                    "validated_status" if name.startswith("validated") else "status", args, data)
                   for name, args, data in cases]
    hits = prepare_cache(base, entries, envs, cache_cases, small)
    empty = base / "empty-path"
    empty.mkdir()
    for name, args, data in cases:
        proof = subprocess.run([str(entries["candidate"]), *args], input=data, capture_output=True,
            env={**envs["candidate"], "PATH": str(empty)}, cwd=small, timeout=10)
        if name in ("relative_fallback", "numeric_fallback"):
            if proof.returncode != 127:
                raise RuntimeError("compatibility workload did not require Python")
        else:
            normalized(proof, name)
    return small, large, unusual, entries, envs, cases, hits


def measure(reference, output, count, budget, selected=None):
    if platform.system() != "Darwin":
        raise RuntimeError("BSD time RSS measurement requires macOS")
    reference = reference.resolve()
    roots = {"reference": reference, "candidate": reference.parent / "candidate"}
    if roots["candidate"].exists():
        raise RuntimeError("preserve old snapshots and choose a new experiment directory")
    capture(roots["candidate"])
    identities = {v: validate(root) for v, root in roots.items()}
    utilities = ("tests/benchmark_native_runtime_status.py", "tests/native_runtime_status_support.py",
        "tests/read_inspection_support.py", "tests/benchmark_native_sha.py", "tests/benchmark_project_discovery.py",
        "tests/native_launcher_support.py", "tests/native_pretool_support.py",
        "tests/discovery_process_measure.py", "tests/runtime_snapshot_normalize.py")
    report = {"status": "running", "platform": platform.platform(), "samples_per_variant": count,
        "method": "original per-snapshot installers and headers, balanced serial paired entrypoints, prepared Python caches, warm filesystem, unreserved host",
        "variants": identities, "utility_sha256": {p: digest(PROJECT / p) for p in utilities},
        "budget_seconds": budget, "cases": {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="native-status-bench-") as tmp:
            base = Path(tmp).resolve()
            small, large, unusual, entries, envs, cases, hits = fixtures(base, roots, selected)
            caches = cache_hashes(base)
            before = {"small": state_hashes(small), "large": state_hashes(large), "unusual": state_hashes(unusual)}
            report.update(cache_hits=hits, bytecode_sha256=caches,
                          entry_sha256={v: digest(p) for v, p in entries.items()},
                          native_only_cases=[name for name, _args, _data in cases if not name.endswith("fallback")],
                          python_fallback_cases=[name for name, _args, _data in cases if name.endswith("fallback")])
            started = time.monotonic()
            deadline = started + budget
            rng = random.Random(81156)
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
                            raise TimeoutError("status timing budget exhausted")
                        metrics_file = base / "metrics.txt"
                        done, metrics = run_measured(["/usr/bin/time", "-l", "-o", str(metrics_file),
                            str(entries[variant]), *args], env=envs[variant], cwd=small,
                            input_bytes=data, timeout=min(10, left))
                        value = normalized(done, name)
                        expected = value if expected is None else expected
                        if value != expected:
                            raise RuntimeError("original/new status output differs")
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
            after = {"small": state_hashes(small), "large": state_hashes(large), "unusual": state_hashes(unusual)}
            if before != after or caches != cache_hashes(base):
                raise RuntimeError("state or bytecode changed during measurement")
            report.update(state_sha256=before, state_unchanged=True,
                          elapsed_seconds=time.monotonic() - started, status="complete")
        if any(validate(root) != identities[v] for v, root in roots.items()):
            raise RuntimeError("source or native artifact changed during measurement")
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
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("use an even sample count >=24")
    measure(args.reference, args.output, args.samples, args.budget_seconds, args.cases)
