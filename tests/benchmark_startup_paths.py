#!/usr/bin/env python3
"""One bounded CPU/wall comparison of status and next-action startup paths."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

from benchmark_project_discovery import digest, freeze, summary
from discovery_process_measure import run_measured
from runtime_snapshot_normalize import normalize_output
from startup_path_support import PROJECT, environment, prepare
from support.stable_launcher import ensure_stable_launcher


def comparable(done, kind, source):
    if kind in ("validated_status", "trends"):
        return done.returncode, normalize_output(done.stdout, kind), done.stderr
    if kind == "next_empty":
        value = json.loads(done.stdout)
        assert done.stdout == (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
        assert value["status"] == "no_active_run"
        token = f" --rules {source.resolve()} --command "
        assert value["copyable_command"].count(token) == 1
        value["copyable_command"] = value["copyable_command"].replace(token, " --rules <SOURCE> --command ", 1)
        return done.returncode, (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(), done.stderr
    return done.returncode, done.stdout, done.stderr


def measure(output, count, budget):
    runtime = ["scripts/agent-os-status.py", "scripts/agent_next_action.py",
               "scripts/agent_observability.py", "scripts/agent_worker_evidence.py"]
    report = {"platform": platform.platform(), "python": platform.python_version(),
              "baseline": "d00fb87b", "samples_per_variant": count, "budget_seconds": budget,
              "method": "serial child CPU/wall, balanced randomized pairs, sibling source snapshots, prepared bytecode, warm filesystem, unreserved host",
              "source_sha256": {p: digest(PROJECT / p) for p in runtime},
              "utility_sha256": {p: digest(PROJECT / p) for p in ["tests/benchmark_startup_paths.py",
                  "tests/runtime_snapshot_normalize.py", "tests/startup_path_support.py",
                  "tests/discovery_process_measure.py"]}, "cases": {}, "status": "running"}
    rng = random.Random(3821)
    with tempfile.TemporaryDirectory(prefix="startup-bench-") as tmp:
        base = Path(tmp).resolve()
        reference = base / "reference-source"
        candidate = base / "candidate-source"
        freeze("d00fb87b", reference)
        report["baseline_revision"] = json.loads((reference / "baseline.json").read_text())["revision"]
        shutil.copytree(reference, candidate)
        for relative in runtime:
            shutil.copy2(PROJECT / relative, candidate / relative)
            assert digest(candidate / relative) == report["source_sha256"][relative]
        project, active = prepare(base)
        with patch("support.stable_launcher.Path.home", return_value=base / "home"):
            ensure_stable_launcher(PROJECT, dry_run=False)
        launcher = base / "home/.moru/bin/moru-hook"
        report["entry_sha256"] = digest(launcher)
        cases = [
            ("next_empty", ["next", "--project", str(project), "--format", "json"]),
            ("validated_status", ["agent-os-status", "--project", str(project), "--validate"]),
            ("next_active", ["next", "--project", str(project), "--evidence", str(active), "--format", "json"]),
            ("trends", ["agent-os-status", "--project", str(project), "--efficiency-trends",
                        "--spill-db", str(base / "missing-spill.sqlite"), "--codex-db", str(base / "missing-codex.sqlite")]),
            ("next_help", ["next", "--help"]),
            ("status_help", ["agent-os-status", "--help"]),
        ]
        roots = {"reference": reference, "candidate": candidate}
        deadline = time.monotonic() + budget
        active_case = active_variant = None
        try:
            for name, args in cases:
                active_case = name
                values = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms")} for v in roots}
                report["cases"][name] = {"samples": values, "complete": False}
                expected = None
                orders = [list(roots) if i % 2 == 0 else list(reversed(roots)) for i in range(count)]
                rng.shuffle(orders)
                for warm, order in [(True, list(roots)), *[(False, row) for row in orders]]:
                    for variant in order:
                        active_variant = variant
                        remaining = deadline - time.monotonic()
                        if remaining < .05:
                            raise TimeoutError("timing budget exhausted")
                        env = environment(base, roots[variant])
                        env["PYTHONPYCACHEPREFIX"] = str(output.parent / "startup-bytecode")
                        if warm:
                            env.pop("PYTHONDONTWRITEBYTECODE", None)
                        done, metrics = run_measured([str(launcher), *args], env=env, cwd=project,
                                                     timeout=min(15, remaining))
                        result = comparable(done, name, roots[variant])
                        if expected is None:
                            expected = result
                        if result != expected or done.returncode != 0:
                            raise RuntimeError(f"output/status mismatch {name}/{variant}: {done.stderr[:300]!r}")
                        if not warm:
                            for key, value in metrics.items():
                                values[variant][key].append(value)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                row = {v: {k: summary(times) for k, times in fields.items()} for v, fields in values.items()}
                report["cases"][name].update(complete=True, summary=row,
                    output_sha256=hashlib.sha256(expected[1]).hexdigest(), exit_code=expected[0])
                print(json.dumps({name: {v: {k: {a: n for a, n in data.items() if a != "samples_ms"}
                                             for k, data in fields.items() if k in ("wall_ms", "cpu_ms")}
                                         for v, fields in row.items()}}), flush=True)
            report["status"] = "complete"
        except (TimeoutError, subprocess.TimeoutExpired) as error:
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
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/startup-paths.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("samples must be even and at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
