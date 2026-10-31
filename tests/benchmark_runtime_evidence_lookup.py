#!/usr/bin/env python3
"""Bounded canonical evidence lookup comparison; no live project state."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from benchmark_project_discovery import digest, freeze, summary
from discovery_process_measure import run_measured
from runtime_evidence_lookup_probe import PROJECT, environment, fixture, resolve

BASELINE = "24246a961174975350a94b406a16171477af0a83"
RUNTIME = "scripts/agent_runtime_session.py"
TIMED = ("compact", "history_500", "cache_10000", "custom")
CONTROLS = ("ambiguous", "settled_tie", "worker_parent", "worker_hint",
            "nested_checkout", "file_symlink", "moved_state")


def load(source, name):
    spec = importlib.util.spec_from_file_location(name, source / RUNTIME)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def operation_counts(module, project, kind):
    counts = {"walk_calls": 0, "visited_directories": 0, "file_names": 0, "directory_opens": 0}
    original_walk, original_scandir = os.walk, os.scandir

    def walk(*args, **kwargs):
        counts["walk_calls"] += 1
        for root, dirs, files in original_walk(*args, **kwargs):
            counts["visited_directories"] += 1
            counts["file_names"] += len(files)
            yield root, dirs, files

    def scandir(*args, **kwargs):
        counts["directory_opens"] += 1
        return original_scandir(*args, **kwargs)

    with patch.object(os, "walk", walk), patch.object(os, "scandir", scandir):
        result = resolve(module, project, kind)
    return result, counts


def measure(output, count, budget):
    report = {"status": "running", "baseline_revision": BASELINE, "seed": 61031,
              "platform": platform.platform(), "python": sys.version,
              "samples_per_variant": count, "budget_seconds": budget,
              "method": "balanced AB/BA, prepared bytecode, warm filesystem; fresh public-resolver subprocess CPU/wall and initialized resolver CPU/wall; no full pretool or agent latency claim",
              "runtime_sha256": digest(PROJECT / RUNTIME),
              "utility_sha256": {p: digest(PROJECT / p) for p in (
                  "tests/benchmark_runtime_evidence_lookup.py", "tests/runtime_evidence_lookup_probe.py",
                  "tests/discovery_process_measure.py", "tests/benchmark_project_discovery.py")},
              "fresh": {}, "initialized": {}, "controls": {}, "operation_counts": {}}
    deadline = time.monotonic() + budget
    rng = random.Random(61031)

    def remaining():
        left = deadline - time.monotonic()
        if left < .05:
            raise TimeoutError("measurement budget exhausted")
        return min(5, left)

    def orders():
        rows = [["reference", "candidate"], ["candidate", "reference"]] * (count // 2)
        rng.shuffle(rows)
        return rows

    try:
        with tempfile.TemporaryDirectory(prefix="evidence-lookup-") as tmp:
            base = Path(tmp).resolve()
            roots = {v: base / v for v in ("reference", "candidate")}
            freeze(BASELINE, roots["reference"])
            shutil.copytree(roots["reference"], roots["candidate"])
            shutil.copy2(PROJECT / RUNTIME, roots["candidate"] / RUNTIME)
            report["reference_runtime_sha256"] = digest(roots["reference"] / RUNTIME)
            env = environment(base)
            (base / "home").mkdir()
            with patch.dict(os.environ, env, clear=True):
                cases = {kind: fixture(base, kind) for kind in (*TIMED, *CONTROLS)}
            probe = PROJECT / "tests/runtime_evidence_lookup_probe.py"
            for kind, (project, expected) in cases.items():
                remaining()
                expected_bytes = (json.dumps({"resolved": expected}, sort_keys=True) + "\n").encode()
                values = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms")} for v in roots}
                report["fresh"][kind] = {"samples": values, "complete": False}
                rounds = [(True, list(roots))]
                if kind in TIMED:
                    rounds.extend((False, row) for row in orders())
                for warm, order in rounds:
                    for variant in order:
                        child_env = environment(base, roots[variant])
                        child_env["PYTHONPYCACHEPREFIX"] = str(base / "bytecode")
                        if warm:
                            child_env.pop("PYTHONDONTWRITEBYTECODE")
                        done, metrics = run_measured(
                            [sys.executable, str(probe), "--source", str(roots[variant]),
                             "--project", str(project), "--kind", kind],
                            env=child_env, cwd=project, timeout=remaining())
                        if (done.returncode, done.stdout, done.stderr) != (0, expected_bytes, b""):
                            raise RuntimeError(f"resolver mismatch: {kind}/{variant}: {done.stdout!r} {done.stderr[:300]!r}")
                        if not warm:
                            for key, value in metrics.items():
                                values[variant][key].append(value)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                row = {v: {k: summary(times) for k, times in fields.items()} for v, fields in values.items()} if kind in TIMED else {}
                report["fresh"][kind].update(complete=True, summary=row,
                    output_sha256=hashlib.sha256(expected_bytes).hexdigest())
                report["controls"][kind] = "exact exit/stdout/stderr matched both variants"
                if row:
                    print(json.dumps({"fresh": kind, "wall_median_ms": {
                        v: d["wall_ms"]["median_ms"] for v, d in row.items()}}), flush=True)
            with patch.dict(os.environ, env, clear=True):
                # All dependencies are unchanged; load only the changed owner
                # twice to compare initialized logic without import startup.
                modules = {v: load(root, "evidence_bench_" + v) for v, root in roots.items()}
                for kind in TIMED:
                    project, expected = cases[kind]
                    values = {v: {k: [] for k in ("wall_ms", "cpu_ms")} for v in roots}
                    for variant, module in modules.items():
                        actual, counts = operation_counts(module, project, kind)
                        assert actual == expected
                        report["operation_counts"].setdefault(kind, {})[variant] = counts
                    for order in orders():
                        for variant in order:
                            remaining()
                            cpu, wall = time.process_time_ns(), time.perf_counter_ns()
                            actual = resolve(modules[variant], project, kind)
                            elapsed = (time.perf_counter_ns() - wall) / 1e6
                            cpu_ms = (time.process_time_ns() - cpu) / 1e6
                            assert actual == expected
                            values[variant]["wall_ms"].append(elapsed)
                            values[variant]["cpu_ms"].append(cpu_ms)
                    row = {v: {k: summary(times) for k, times in fields.items()} for v, fields in values.items()}
                    report["initialized"][kind] = row
                    print(json.dumps({"initialized": kind, "wall_median_ms": {
                        v: d["wall_ms"]["median_ms"] for v, d in row.items()}}), flush=True)
            report["status"] = "complete"
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        report.update(status="incomplete_budget", error=type(error).__name__)
    except Exception as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        report["elapsed_seconds"] = budget - (deadline - time.monotonic())
        output.write_text(json.dumps(report, indent=2) + "\n")
    return report["status"] == "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--budget-seconds", type=float, default=90)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/evidence-lookup.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("samples must be even and at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
