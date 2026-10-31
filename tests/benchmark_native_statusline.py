#!/usr/bin/env python3
"""Controlled fresh-process comparison; temporary installation, never global.

Owner: reproducible statusline measurements. Allowed: stdlib, stable launcher
generation and verified local artifact. Forbidden: builds, private settings,
network, actual configured chains, global installation. Run after native build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from support.stable_launcher import _launcher_script_text, ensure_stable_launcher

PROJECT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(home, output, count):
    with patch("support.stable_launcher.Path.home", return_value=home):
        ensure_stable_launcher(PROJECT, dry_run=False)
    entry = home / ".moru/bin/moru-hook"
    reference = entry.with_name("python-reference")
    reference.write_text(_launcher_script_text(native=False))
    reference.chmod(0o755)
    cache = output.parent / "prepared-bytecode"
    env = dict(os.environ, HOME=str(home), MORU_HOME=str(PROJECT), NO_COLOR="1",
               PYTHONUTF8="1", PYTHONPYCACHEPREFIX=str(cache), LC_ALL="C", LANG="C",
               MORU_HOOK_SOFT_FAIL="0")
    for name in ("PYTHONPATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"):
        env.pop(name, None)
    payload = json.dumps({"model": {"display_name": "Example Model"},
                          "workspace": {"project_dir": str(home / "project")},
                          "rate_limits": {"five_hour": {"used_percentage": 65},
                                          "seven_day": {"used_percentage": 6}}}).encode()
    fallback = b'{"model":{"display_name":42}}\r\n'
    cases = {
        "plain": (["claude-statusline"], payload),
        "chain_builtin": (["claude-statusline", "--chain", "printf chain"], payload),
        "chain_pipe": (["agy-statusline", "--chain", "/bin/cat >/dev/null; printf chain"], payload),
        "compatibility": (["claude-statusline"], fallback),
        "legacy_help": (["--help"], b""),
    }
    variants = {
        "reference": ([str(reference)], "python"),
        "python_no_site": ([sys.executable, "-S", str(reference)], "python"),
        "native_auto": ([str(entry)], "auto"),
        "python_rollback": ([str(entry)], "python"),
    }
    report = {"platform": platform.platform(), "python": sys.version.split()[0],
              "samples_per_variant": count, "seed": 5189,
              "method": "randomized interleaved fresh processes, warm filesystem and prepared bytecode; captured identical stdout/stderr/exit; temporary generated entrypoints; controlled chains only; unreserved host",
              "hashes": {"reference": digest(reference), "generated": digest(entry),
                         "native": digest(entry.parent / "moru-hook-native")}, "cases": {}}
    receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
    report["native_build"] = receipt
    sources = [Path(__file__), PROJECT / "scripts/support/native_launcher_install.py",
               PROJECT / "scripts/support/launcher_python.py", PROJECT / "scripts/support/statusline.py",
               PROJECT / "scripts/support/runtime_quota.py"]
    report["source_sha256"] = {str(p.relative_to(PROJECT)): digest(p) for p in sources}
    rng = random.Random(5189)
    for name, (args, data) in cases.items():
        expected = None
        samples = {v: [] for v in variants}
        for variant, (command, backend) in variants.items():
            done = subprocess.run(command + args, input=data, env=dict(env, MORU_LAUNCHER_BACKEND=backend),
                                  capture_output=True, timeout=15, check=True)
            actual = (done.returncode, done.stdout, done.stderr)
            if expected is None:
                expected = actual
            if actual != expected:
                raise RuntimeError(f"output mismatch in {name}/{variant}")
        timed_env = dict(env, PYTHONDONTWRITEBYTECODE="1")
        for _ in range(count):
            order = list(variants)
            rng.shuffle(order)
            for variant in order:
                command, backend = variants[variant]
                start = time.perf_counter_ns()
                done = subprocess.run(command + args, input=data,
                    env=dict(timed_env, MORU_LAUNCHER_BACKEND=backend), capture_output=True, timeout=15)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if (done.returncode, done.stdout, done.stderr) != expected:
                    raise RuntimeError(f"output mismatch in {name}/{variant}")
                samples[variant].append(elapsed)
        report["cases"][name] = {v: {"median_ms": statistics.median(values),
            "p95_ms": sorted(values)[max(0, (95 * count + 99) // 100 - 1)],
            "samples_ms": values} for v, values in samples.items()}
        print(json.dumps({name: {v: {k: n for k, n in row.items() if k != "samples_ms"}
                               for v, row in report["cases"][name].items()}}), flush=True)
    output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/statusline-comparison.json")
    args = parser.parse_args()
    if args.samples < 20:
        parser.error("at least 20 samples are required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="moru-statusline-bench-") as tmp:
        measure(Path(tmp), args.output, args.samples)


if __name__ == "__main__":
    main()
