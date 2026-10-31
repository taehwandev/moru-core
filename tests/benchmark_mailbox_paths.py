#!/usr/bin/env python3
"""Bounded paired timings of ordinary mailbox paths, with exact output checks."""
from __future__ import annotations

import argparse
import hashlib
from itertools import permutations
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
from startup_path_support import PROJECT, environment, prepare
from support.stable_launcher import ensure_stable_launcher

RUNTIME = ("scripts/agent-mailbox.py", "scripts/agent_mailbox.py", "scripts/agent_mailbox_task.py")
SCOPED = ("scripts/agent_project_memory.py", "scripts/agent_mailbox_hook.py")
GUIDANCE = "common/skills/agent-operating-skill/SKILL.md"


def measure(output, count, budget):
    utilities = ("tests/benchmark_mailbox_paths.py", "tests/discovery_process_measure.py",
                 "tests/startup_path_support.py")
    report = {"status": "running", "baseline": "08c75417", "python": platform.python_version(),
              "platform": platform.platform(), "samples_per_variant": count,
              "budget_seconds": budget, "method": "serial child CPU/wall, balanced three-way order, prepared bytecode, warm filesystem, unreserved host",
              "source_sha256": {p: digest(PROJECT / p) for p in (*RUNTIME, *SCOPED)},
              "utility_sha256": {p: digest(PROJECT / p) for p in utilities}, "cases": {}}
    rng = random.Random(8382)
    with tempfile.TemporaryDirectory(prefix="mailbox-bench-") as tmp:
        base = Path(tmp).resolve()
        reference, imports, candidate = base / "reference", base / "imports", base / "candidate"
        freeze("08c75417", reference)
        report["baseline_revision"] = json.loads((reference / "baseline.json").read_text())["revision"]
        for source in (imports, candidate):
            shutil.copytree(reference, source)
        for source in (reference, imports, candidate):
            (source / GUIDANCE).parent.mkdir(parents=True)
            shutil.copy2(PROJECT / GUIDANCE, source / GUIDANCE)
        report["guidance_sha256"] = digest(PROJECT / GUIDANCE)
        for name in RUNTIME:
            shutil.copy2(PROJECT / name, imports / name)
            shutil.copy2(PROJECT / name, candidate / name)
            assert digest(candidate / name) == report["source_sha256"][name]
        for name in SCOPED:
            shutil.copy2(PROJECT / name, candidate / name)
            assert digest(candidate / name) == report["source_sha256"][name]
        report["imports_only_sha256"] = {p: digest(imports / p) for p in (*RUNTIME, *SCOPED)}
        project, _ = prepare(base)
        with patch("support.stable_launcher.Path.home", return_value=base / "home"):
            ensure_stable_launcher(PROJECT, dry_run=False)
        launcher = base / "home/.moru/bin/moru-hook"
        report["entry_sha256"] = digest(launcher)
        payload = json.dumps({"cwd": str(project), "session_id": "synthetic-benchmark"}).encode()
        cases = [
            ("mailbox_status", ["agent-mailbox", "status", "--project", str(project), "--runtime", "codex", "--json"], None),
            ("mailbox_receive_empty", ["agent-mailbox", "receive", "--project", str(project), "--runtime", "codex", "--json"], None),
            ("prompt_delivery_quiet", ["mailbox-hook", "deliver", "--runtime", "codex"], payload),
            ("ack_empty_control", ["mailbox-hook", "ack", "--runtime", "codex"], payload),
            ("mailbox_help", ["agent-mailbox", "--help"], None),
            ("status_help_control", ["agent-os-status", "--help"], None),
        ]
        roots = {"reference": reference, "imports": imports, "candidate": candidate}
        deadline = time.monotonic() + budget
        try:
            for name, args, stdin in cases:
                data = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms")} for v in roots}
                report["cases"][name] = {"samples": data, "complete": False}
                orders = list(permutations(roots)) * (count // 6)
                rng.shuffle(orders)
                expected = None
                for warm, order in [(True, list(roots)), *[(False, row) for row in orders]]:
                    for variant in order:
                        env = environment(base, roots[variant])
                        env["PYTHONPYCACHEPREFIX"] = str(output.parent / "mailbox-bytecode")
                        if warm:
                            env.pop("PYTHONDONTWRITEBYTECODE", None)
                        remaining = deadline - time.monotonic()
                        if remaining < .05:
                            raise TimeoutError("measurement budget exhausted")
                        done, metrics = run_measured([str(launcher), *args], env=env, cwd=project,
                            timeout=min(15, remaining), input_bytes=stdin)
                        if done.returncode or done.stderr:
                            raise RuntimeError(f"failed {name}/{variant}: {done.stderr[:200]!r}")
                        if warm:
                            continue  # First guidance is shown once; timed turns are deliberately quiet.
                        result = (done.returncode, done.stdout, done.stderr)
                        if expected is None:
                            expected = result
                        if result != expected:
                            raise RuntimeError(f"output differs for {name}/{variant}")
                        if name in ("prompt_delivery_quiet", "ack_empty_control") and done.stdout:
                            raise RuntimeError("quiet hook produced output")
                        for key, value in metrics.items():
                            data[variant][key].append(value)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                stats = {v: {k: summary(values) for k, values in fields.items()} for v, fields in data.items()}
                report["cases"][name].update(complete=True, summary=stats,
                    output_sha256=hashlib.sha256(expected[1]).hexdigest(), exit_code=expected[0])
                print(name, {v: {k: round(n["median_ms"], 3) for k, n in fields.items()
                                 if k in ("wall_ms", "cpu_ms")} for v, fields in stats.items()}, flush=True)
            report["status"] = "complete"
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            report.update(status="incomplete_budget", stopped_case=name, stop_type=type(error).__name__)
        finally:
            output.write_text(json.dumps(report, indent=2) + "\n")
    return report["status"] == "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--budget-seconds", type=float, default=90)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/mailbox-scope-paths.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 6:
        parser.error("samples must be a multiple of six and at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
