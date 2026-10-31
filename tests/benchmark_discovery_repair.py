#!/usr/bin/env python3
"""Bounded three-way discovery comparison, with child CPU and elapsed time."""
from __future__ import annotations

import argparse
import hashlib
import itertools
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

from benchmark_discovery_batch import normalized
from benchmark_project_discovery import PROJECT, digest, fixture, freeze, summary
from discovery_process_measure import run_measured
from support.stable_launcher import ensure_stable_launcher


class BudgetStop(Exception):
    pass


def measure(output, count, budget):
    runtime = ["scripts/agent_project_search.py", "scripts/agent_project_discovery.py",
               "scripts/agent_workspace_scope.py"]
    report = {"platform": platform.platform(), "python": platform.python_version(),
              "samples_per_variant": count, "budget_seconds": budget, "seed": 1981,
              "method": "serial child CPU deltas and elapsed time; balanced three-way order; sibling source snapshots; matched prepared bytecode; warm filesystem; unreserved host",
              "status": "running", "cases": {},
              "source_sha256": {p: digest(PROJECT / p) for p in runtime},
              "measurement_sha256": {p: digest(PROJECT / p) for p in
                  ["tests/benchmark_discovery_repair.py", "tests/discovery_process_measure.py"]}}
    rng = random.Random(1981)
    with tempfile.TemporaryDirectory(prefix="discovery-repair-bench-") as tmp:
        base = Path(tmp)
        roots = {v: base / v for v in ("prebatch", "previous", "candidate")}
        freeze("9e166efd", roots["prebatch"])
        freeze("5958ffe0", roots["previous"])
        report["baseline_revisions"] = {v: json.loads((roots[v] / "baseline.json").read_text())["revision"]
                                         for v in ("prebatch", "previous")}
        shutil.copytree(roots["previous"], roots["candidate"])
        for relative in runtime:
            shutil.copy2(PROJECT / relative, roots["candidate"] / relative)
            assert digest(roots["candidate"] / relative) == report["source_sha256"][relative]
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
        wide = fixture(base / "many", 600, 0)
        for i in range(600):
            (wide / f"project-{i:03}/AGENTS.md").touch()
        registry = base / "registry.json"
        registry.write_text('{"projects":[],"search_roots":[]}')
        rich = base / "rich.json"
        rich.write_text(json.dumps({"projects": [{"disabled": True, "root": str(base / f"unused-{i}")}
                                                  for i in range(6000)]}))
        env = dict(os.environ, HOME=str(home), NO_COLOR="1", PYTHONUTF8="1", LC_ALL="C", LANG="C",
                   PYTHONPYCACHEPREFIX=str(output.parent / "repair-bytecode"),
                   MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="0")
        for key in ("PYTHONPATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                    "MORU_PROJECT_SEARCH_ROOTS", "MORU_PROJECT_REGISTRY", "MORU_STATE_HOME"):
            env.pop(key, None)
        cases = [("startup_help", "project-discover", None, registry, None),
                 ("small", "project-discover", small, registry, "work on project-004"),
                 ("file_heavy", "project-discover", heavy, registry, "work on project-004"),
                 ("many_ambiguous", "project-discover", wide, registry, "update projects"),
                 ("entry_registry", "agent-entry", wide, rich, "work on project-004")]
        deadline = time.monotonic() + budget
        active_case = active_variant = None
        try:
            for name, alias, tree, reg, request in cases:
                active_case = name
                command = [str(launcher), alias]
                if tree is None:
                    command += ["--help"]
                else:
                    command += ["--request", request, "--cwd", str(outside), "--registry", str(reg),
                                "--search-root", str(tree), "--max-depth", "2", "--format", "json"]
                    if alias == "agent-entry":
                        command += ["--runtime", "generic"]
                expected = None
                values = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms")} for v in roots}
                report["cases"][name] = {"samples": values, "complete": False}
                order_rows = list(itertools.permutations(roots)) * (count // 6)
                rng.shuffle(order_rows)
                for warm, order in [(True, list(roots)), *[(False, row) for row in order_rows]]:
                    for variant in order:
                        active_variant = variant
                        remaining = deadline - time.monotonic()
                        if remaining < .05:
                            raise BudgetStop()
                        child_env = dict(env, MORU_HOME=str(roots[variant]))
                        if not warm:
                            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
                        done, metrics = run_measured(command, env=child_env, cwd=outside,
                                                     timeout=min(20, remaining))
                        result = normalized(done, roots[variant], alias == "agent-entry")
                        if expected is None:
                            expected = result
                        if result != expected:
                            raise RuntimeError(f"output mismatch {name}/{variant}")
                        if not warm:
                            for key, value in metrics.items():
                                values[variant][key].append(value)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                row = {v: {k: summary(times) for k, times in metrics.items()} for v, metrics in values.items()}
                report["cases"][name].update(complete=True, summary=row, exit_code=expected[0],
                    output_sha256=hashlib.sha256(expected[1]).hexdigest())
                print(json.dumps({name: {v: {k: {a: n for a, n in data.items() if a != "samples_ms"}
                                            for k, data in metrics.items() if k in ("wall_ms", "cpu_ms")}
                                        for v, metrics in row.items()}}), flush=True)
            report["status"] = "complete"
        except (BudgetStop, subprocess.TimeoutExpired) as error:
            report.update(status="incomplete_budget", stopped_case=active_case,
                          stopped_variant=active_variant, stop_type=type(error).__name__)
            print(json.dumps({"status": report["status"], "case": active_case}), flush=True)
        finally:
            output.write_text(json.dumps(report, indent=2) + "\n")
    return report["status"] == "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--budget-seconds", type=float, default=90)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/discovery-repair.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 6:
        parser.error("samples must be a multiple of six, at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
