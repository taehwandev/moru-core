#!/usr/bin/env python3
"""Frozen-source comparison of project enumeration and generated CLI latency.

Owner: controlled local measurement. Allowed: stdlib, source snapshot and
temporary generated launcher. No private registry/config scans or installation.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import tarfile
import time
from unittest.mock import patch

from support.stable_launcher import ensure_stable_launcher
import agent_project_search as current_search

PROJECT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(values):
    return {"median_ms": statistics.median(values),
            "p95_ms": sorted(values)[(95 * len(values) + 99) // 100 - 1],
            "samples_ms": values}


def fixture(path, folders, files):
    path.mkdir()
    for i in range(folders):
        child = path / f"project-{i:03}"
        child.mkdir()
        if i % 4 == 0:
            (child / "AGENTS.md").touch()
        for j in range(files):
            (child / f"source-{j:03}.txt").touch()
    for name in (".hidden", "node_modules", "build"):
        child = path / name
        child.mkdir()
        (child / "AGENTS.md").touch()
    return path


def freeze(revision, destination):
    """Snapshot tracked Git bytes without a checkout, worktree or network."""
    revision = subprocess.check_output(["git", "rev-parse", "--verify", revision + "^{commit}"],
                                       cwd=PROJECT, text=True).strip()
    data = subprocess.check_output(["git", "archive", "--format=tar", revision,
                                    "scripts", "AGENTS.md", "index.md"], cwd=PROJECT)
    hashes = {}
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.isdir():
                continue
            relative = Path(member.name)
            if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("unsupported baseline archive member")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = archive.extractfile(member).read()
            target.write_bytes(content)
            target.chmod(member.mode & 0o777)
            hashes[member.name] = hashlib.sha256(content).hexdigest()
    (destination / "baseline.json").write_text(json.dumps({"revision": revision,
        "source_sha256": hashes}, indent=2))


def measure(baseline, output, count, selected_cases):
    metadata = json.loads((baseline / "baseline.json").read_text())
    for name, expected in metadata["source_sha256"].items():
        if digest(baseline / name) != expected:
            raise RuntimeError("frozen baseline changed: " + name)
    spec = importlib.util.spec_from_file_location("frozen_project_search", baseline / "scripts/agent_project_search.py")
    old_search = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_search)
    report = {"baseline_revision": metadata["revision"], "platform": platform.platform(),
              "python": sys.version.split()[0], "samples_per_variant": count, "seed": 7421,
              "method": "randomized paired fresh generated entrypoint, warm filesystem, prepared bytecode; separate initialized scan; controlled fixtures only; unreserved host",
              "baseline_owner_sha256": metadata["source_sha256"]["scripts/agent_project_search.py"],
              "current_owner_sha256": digest(PROJECT / "scripts/agent_project_search.py"),
              "helper_sha256": digest(PROJECT / "scripts/support/project_directory_scan.py"),
              "benchmark_sha256": digest(Path(__file__)),
              "cases": {}}
    rng = random.Random(7421)
    with tempfile.TemporaryDirectory(prefix="project-discovery-bench-") as tmp:
        base = Path(tmp)
        home = base / "home"
        home.mkdir()
        outside = base / "outside"
        outside.mkdir()
        registry = base / "registry.json"
        registry.write_text('{"projects":[],"search_roots":[]}')
        with patch("support.stable_launcher.Path.home", return_value=home):
            ensure_stable_launcher(PROJECT, dry_run=False)
        launcher = home / ".moru/bin/moru-hook"
        report["entry_sha256"] = digest(launcher)
        cache = output.parent / "discovery-bytecode"
        env = dict(os.environ, HOME=str(home), NO_COLOR="1", PYTHONUTF8="1", LC_ALL="C", LANG="C",
                   PYTHONPYCACHEPREFIX=str(cache), MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="0")
        for key in ("PYTHONPATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                    "MORU_PROJECT_SEARCH_ROOTS", "MORU_PROJECT_REGISTRY", "MORU_STATE_HOME"):
            env.pop(key, None)
        small = fixture(base / "small", 8, 3)
        heavy = fixture(base / "file-heavy", 40, 250)
        wide = fixture(base / "directory-heavy", 300, 0)
        cases = [("small", small, 2), ("file_heavy", heavy, 2),
                 ("directory_heavy", wide, 2), ("depth_zero", heavy, 0)]
        roots = {"reference": baseline, "candidate": PROJECT}
        for name, tree, depth in cases:
            if selected_cases and name not in selected_cases:
                continue
            command = [str(launcher), "project-discover", "--request", "work on project-004",
                       "--cwd", str(outside), "--registry", str(registry), "--search-root", str(tree),
                       "--max-depth", str(depth), "--format", "json"]
            expected = None
            samples = {v: [] for v in roots}
            for variant, root in roots.items():
                done = subprocess.run(command, capture_output=True, timeout=20,
                                      env=dict(env, MORU_HOME=str(root)), cwd=outside)
                actual = (done.returncode, done.stdout, done.stderr)
                if expected is None:
                    expected = actual
                if actual != expected:
                    raise RuntimeError(f"warm output mismatch: {name}/{variant}")
            timed_env = dict(env, PYTHONDONTWRITEBYTECODE="1")
            orders = [list(roots) if i % 2 == 0 else list(reversed(roots)) for i in range(count)]
            rng.shuffle(orders)
            for order in orders:
                for variant in order:
                    start = time.perf_counter_ns()
                    done = subprocess.run(command, capture_output=True, timeout=20, cwd=outside,
                                          env=dict(timed_env, MORU_HOME=str(roots[variant])))
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    if (done.returncode, done.stdout, done.stderr) != expected:
                        raise RuntimeError(f"timed output mismatch: {name}/{variant}")
                    samples[variant].append(elapsed)
            scan_samples = {v: [] for v in roots}
            scans = {"reference": old_search.scan_project_roots,
                     "candidate": current_search.scan_project_roots}
            expected_paths = list(scans["reference"](tree, max_depth=depth))
            for _ in range(count):
                order = list(scans)
                rng.shuffle(order)
                for variant in order:
                    start = time.perf_counter_ns()
                    paths = list(scans[variant](tree, max_depth=depth))
                    scan_samples[variant].append((time.perf_counter_ns() - start) / 1e6)
                    if paths != expected_paths:
                        raise RuntimeError(f"initialized path/order mismatch: {name}/{variant}")
            row = {"fresh": {v: summary(values) for v, values in samples.items()},
                   "initialized_scan": {v: summary(values) for v, values in scan_samples.items()},
                   "output_sha256": hashlib.sha256(expected[1]).hexdigest(),
                   "exit_code": expected[0], "project_count": len(expected_paths)}
            report["cases"][name] = row
            print(json.dumps({name: {kind: {v: {k: n for k, n in vals.items() if k != "samples_ms"}
                                          for v, vals in row[kind].items()}
                                    for kind in ("fresh", "initialized_scan")}}), flush=True)
    output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--baseline-root", type=Path)
    group.add_argument("--baseline-revision", default="2b9655f2")
    parser.add_argument("--case", action="append", choices=("small", "file_heavy", "directory_heavy", "depth_zero"))
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/project-discovery.json")
    args = parser.parse_args()
    if args.samples < 20:
        parser.error("at least 20 samples required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.baseline_root:
        measure(args.baseline_root.resolve(), args.output, args.samples, args.case)
    else:
        with tempfile.TemporaryDirectory(prefix="project-discovery-baseline-") as tmp:
            baseline = Path(tmp) / "source"
            freeze(args.baseline_revision, baseline)
            measure(baseline, args.output, args.samples, args.case)


if __name__ == "__main__":
    main()
