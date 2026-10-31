#!/usr/bin/env python3
"""Real generated next-action entrypoint, with canonical resolver discovery."""
from __future__ import annotations

import argparse
import hashlib
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

from benchmark_project_discovery import digest, freeze, summary
from benchmark_runtime_evidence_lookup import BASELINE, RUNTIME, TIMED
from discovery_process_measure import run_measured
from runtime_evidence_lookup_probe import PROJECT, SESSION, environment, fixture
from support.stable_launcher import ensure_stable_launcher


def measure(output, count, budget):
    report = {"status": "running", "baseline_revision": BASELINE,
              "platform": platform.platform(), "python": platform.python_version(),
              "samples_per_variant": count, "budget_seconds": budget, "seed": 61032,
              "method": "generated temporary-home launcher next, no explicit evidence path; exact output/status comparison; balanced AB/BA, warm filesystem, prepared bytecode, serial child CPU/wall",
              "runtime_sha256": digest(PROJECT / RUNTIME),
              "utility_sha256": {p: digest(PROJECT / p) for p in (
                  "tests/benchmark_runtime_evidence_entry.py", "tests/runtime_evidence_lookup_probe.py",
                  "tests/discovery_process_measure.py", "tests/benchmark_project_discovery.py",
                  "tests/benchmark_runtime_evidence_lookup.py")}, "cases": {}}
    deadline = time.monotonic() + budget
    rng = random.Random(61032)
    try:
        with tempfile.TemporaryDirectory(prefix="evidence-entry-") as tmp:
            base = Path(tmp).resolve()
            roots = {v: base / v for v in ("reference", "candidate")}
            freeze(BASELINE, roots["reference"])
            shutil.copytree(roots["reference"], roots["candidate"])
            shutil.copy2(PROJECT / RUNTIME, roots["candidate"] / RUNTIME)
            env = environment(base)
            (base / "home").mkdir()
            with patch.dict(os.environ, env, clear=True):
                cases = {kind: fixture(base, kind) for kind in TIMED}
                with patch("support.stable_launcher.Path.home", return_value=base / "home"):
                    ensure_stable_launcher(PROJECT, dry_run=False)
            launcher = base / "home/.moru/bin/moru-hook"
            report["launcher_sha256"] = digest(launcher)
            for kind, (project, expected_path) in cases.items():
                # A truthful active route, resolved via its registered session;
                # no explicit --evidence shortcut bypasses the measured owner.
                path = Path(expected_path)
                data = json.loads(path.read_text())
                data["route"] = {"command": "task", "gates": ["tests"], "required_docs": []}
                path.write_text(json.dumps(data))
                values = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms")} for v in roots}
                report["cases"][kind] = {"samples": values, "complete": False}
                expected = None
                orders = [["reference", "candidate"], ["candidate", "reference"]] * (count // 2)
                rng.shuffle(orders)
                for warm, order in [(True, list(roots)), *[(False, row) for row in orders]]:
                    for variant in order:
                        remaining = deadline - time.monotonic()
                        if remaining < .05:
                            raise TimeoutError("entrypoint measurement budget exhausted")
                        child_env = environment(base, roots[variant])
                        child_env.update(CLAUDE_CODE_SESSION_ID=SESSION["session_id"],
                                         PYTHONPYCACHEPREFIX=str(base / "bytecode"),
                                         MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="0")
                        if warm:
                            child_env.pop("PYTHONDONTWRITEBYTECODE")
                        done, metrics = run_measured([str(launcher), "next", "--project", str(project),
                                                      "--format", "json"], env=child_env, cwd=project,
                                                     timeout=min(10, remaining))
                        payload = json.loads(done.stdout)
                        assert payload["status"] == "active_run" and payload["evidence"] == expected_path
                        assert payload["remaining_gates"] == ["tests"]
                        result = done.returncode, done.stdout, done.stderr
                        expected = result if expected is None else expected
                        if result != expected or done.returncode != 0 or done.stderr:
                            raise RuntimeError(f"entrypoint mismatch: {kind}/{variant}")
                        if not warm:
                            for key, value in metrics.items():
                                values[variant][key].append(value)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                row = {v: {k: summary(times) for k, times in fields.items()} for v, fields in values.items()}
                report["cases"][kind].update(complete=True, summary=row,
                    output_sha256=hashlib.sha256(expected[1]).hexdigest())
                print(json.dumps({kind: {v: {k: {a: n for a, n in d.items() if a != "samples_ms"}
                                           for k, d in fields.items() if k in ("wall_ms", "cpu_ms")}
                                        for v, fields in row.items()}}), flush=True)
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
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/evidence-entry.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("samples must be even and at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
