#!/usr/bin/env python3
"""One frozen-source CLI comparison plus isolated costs for the discovery batch."""
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
import tempfile
import time
from unittest.mock import patch

import agent_project_search as search
from benchmark_project_discovery import PROJECT, digest, fixture, freeze, summary
from support.stable_launcher import ensure_stable_launcher


def orders(count, rng):
    result = [["reference", "candidate"] if i % 2 == 0 else ["candidate", "reference"] for i in range(count)]
    rng.shuffle(result)
    return result


def normalized(done, source, entry):
    if not entry:
        return done.returncode, done.stdout, done.stderr
    source = source.resolve()  # macOS /var and /private/var refer to one temporary tree.
    value = json.loads(done.stdout)
    assert done.stdout == (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    suffixes = {"root": "", "agent_instructions": "AGENTS.md", "index": "index.md",
                "workflow": "scripts/workflow.py", "preflight": "scripts/agent-preflight.py",
                "finish_check": "scripts/agent-finish-check.py"}
    for name, suffix in suffixes.items():
        assert value["moru"][name] == str(source / suffix)
        value["moru"][name] = "<SOURCE>/" + suffix
    assert value["runtime_launch"]["moru_root"] == str(source)
    value["runtime_launch"]["moru_root"] = "<SOURCE>"
    command = value["workflow_command"]
    prefix = f"python3 {source}/scripts/workflow.py "
    assert command.startswith(prefix)
    value["workflow_command"] = "python3 <SOURCE>/scripts/workflow.py " + command[len(prefix):]
    return done.returncode, json.dumps(value, sort_keys=True).encode(), done.stderr


def compare_functions(functions, count, rng):
    samples = {name: [] for name in functions}
    expected = functions["reference"]()
    for order in orders(count, rng):
        for variant in order:
            start = time.perf_counter_ns()
            result = functions[variant]()
            samples[variant].append((time.perf_counter_ns() - start) / 1e6)
            if result != expected:
                raise RuntimeError("isolated component output mismatch: " + variant)
    return {v: summary(times) for v, times in samples.items()}


def measure(output, count):
    rng = random.Random(29103)
    report = {"platform": platform.platform(), "samples_per_variant": count, "seed": 29103,
              "python": platform.python_version(), "baseline_revision": "9e166efd",
              "method": "balanced randomized interleaved fresh generated entrypoint; sibling source snapshots, candidate runtime bytes verified; prepared bytecode, warm filesystem, unreserved host; isolated components measured separately",
              "entry_normalization": "Only declared source-root paths in moru, runtime_launch.moru_root and workflow_command; all other values and pretty JSON format retained",
              "cases": {}, "components": {}}
    changed = ["scripts/agent_project_search.py", "scripts/agent_project_discovery.py",
               "scripts/support/project_facts.py", "scripts/support/literal_boundary.py",
               "tests/benchmark_discovery_batch.py"]
    report["source_sha256"] = {p: digest(PROJECT / p) for p in changed}
    with tempfile.TemporaryDirectory(prefix="discovery-batch-bench-") as tmp:
        base = Path(tmp)
        baseline = base / "reference-source"
        freeze("9e166efd", baseline)
        report["baseline"] = json.loads((baseline / "baseline.json").read_text())
        candidate = base / "candidate-source"
        shutil.copytree(baseline, candidate)
        for relative in changed:
            if relative.startswith("scripts/"):
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT / relative, target)
                assert digest(target) == report["source_sha256"][relative]
        spec = importlib.util.spec_from_file_location("frozen_search", baseline / "scripts/agent_project_search.py")
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        home = base / "home"
        home.mkdir()
        outside = base / "outside"
        outside.mkdir()
        with patch("support.stable_launcher.Path.home", return_value=home):
            ensure_stable_launcher(PROJECT, dry_run=False)
        launcher = home / ".moru/bin/moru-hook"
        report["entry_sha256"] = digest(launcher)
        small = fixture(base / "small", 8, 3)
        heavy = fixture(base / "file-heavy", 40, 250)
        wide = fixture(base / "all-marked", 600, 0)
        for i in range(600):
            folder = wide / f"project-{i:03}"
            (folder / "AGENTS.md").touch()
            (folder / ".git").mkdir()
        registry = base / "registry.json"
        registry.write_text('{"projects":[],"search_roots":[]}')
        rich = base / "rich-registry.json"
        rich.write_text(json.dumps({"projects": [{"disabled": True, "root": str(base / f"unused-{i}"),
                                                   "aliases": [f"unused-alias-{i}"]} for i in range(6000)]}))
        env = dict(os.environ, HOME=str(home), NO_COLOR="1", PYTHONUTF8="1", LC_ALL="C", LANG="C",
                   PYTHONPYCACHEPREFIX=str(output.parent / "batch-bytecode"),
                   MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="0")
        for key in ("PYTHONPATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                    "MORU_PROJECT_SEARCH_ROOTS", "MORU_PROJECT_REGISTRY", "MORU_STATE_HOME"):
            env.pop(key, None)
        cases = [("small", "project-discover", small, registry, "work on project-004"),
                 ("many_selected", "project-discover", wide, registry, "work on project-004"),
                 ("many_ambiguous", "project-discover", wide, registry, "update projects"),
                 ("file_heavy", "project-discover", heavy, registry, "work on project-004"),
                 ("entry_registry", "agent-entry", wide, rich, "work on project-004")]
        roots = {"reference": baseline, "candidate": candidate}
        for name, alias, tree, reg, request in cases:
            command = [str(launcher), alias, "--request", request, "--cwd", str(outside),
                       "--registry", str(reg), "--search-root", str(tree), "--max-depth", "2", "--format", "json"]
            if alias == "agent-entry":
                command += ["--runtime", "generic"]
            expected = None
            for variant, root in roots.items():
                done = subprocess.run(command, capture_output=True, timeout=20, cwd=outside,
                                      env=dict(env, MORU_HOME=str(root)))
                result = normalized(done, root, alias == "agent-entry")
                if expected is None:
                    expected = result
                if result != expected:
                    raise RuntimeError(f"warm mismatch: {name}/{variant}")
            samples = {v: [] for v in roots}
            for order in orders(count, rng):
                for variant in order:
                    start = time.perf_counter_ns()
                    done = subprocess.run(command, capture_output=True, timeout=20, cwd=outside,
                        env=dict(env, MORU_HOME=str(roots[variant]), PYTHONDONTWRITEBYTECODE="1"))
                    samples[variant].append((time.perf_counter_ns() - start) / 1e6)
                    if normalized(done, roots[variant], alias == "agent-entry") != expected:
                        raise RuntimeError(f"timed mismatch: {name}/{variant}")
            row = {v: summary(times) for v, times in samples.items()}
            report["cases"][name] = {"timing": row, "exit_code": expected[0],
                "output_sha256": hashlib.sha256(expected[1]).hexdigest()}
            output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({name: {v: {k: n for k, n in vals.items() if k != "samples_ms"}
                                    for v, vals in row.items()}}), flush=True)
        names = [f"project-{i:03}" for i in range(600)]
        request = "work on project-004"
        components = {
            "name_matching_600": {"reference": lambda: [old.request_name_matches(n, request) for n in names],
                                  "candidate": lambda: [search.request_name_matches(n, request) for n in names]},
            "metadata_pipeline_600": {
                "reference": lambda: [old.build_candidate(p, 35, "scan", "search_root").to_dict()
                                      for p in old.scan_project_roots(wide, max_depth=2)],
                "candidate": lambda: [search.build_candidate(p, 35, "scan", "search_root", facts=f).to_dict()
                                      for p, f in search.scan_project_records(wide, max_depth=2)]},
            "registry_reads": {"reference": lambda: (old.load_registry(rich), old.load_registry(rich))[1],
                               "candidate": lambda: search.load_registry(rich)},
            "long_repeated_name": {
                "reference": lambda: old.request_name_matches("a", "a" * 65536),
                "candidate": lambda: search.request_name_matches("a", "a" * 65536)},
        }
        for name, functions in components.items():
            row = compare_functions(functions, count, rng)
            report["components"][name] = row
            output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({name: {v: {k: n for k, n in vals.items() if k != "samples_ms"}
                                    for v, vals in row.items()}}), flush=True)
    output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/discovery-batch.json")
    args = parser.parse_args()
    if args.samples < 20:
        parser.error("at least 20 samples required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    measure(args.output, args.samples)


if __name__ == "__main__":
    main()
