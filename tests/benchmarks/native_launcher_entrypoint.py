"""Measure the generated stable launcher, not just the native binary.

Setup, compilation and parent JSON validation are outside runtime timing.
Legacy dispatch is a synthetic no-op, not a full hook latency measurement.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from checkout_identity_support import CheckoutFixtures, environment, request, rows
from native_launcher_support import NATIVE, fixture_root, install
from support.stable_launcher import _launcher_script_text


def measure(programs, arguments, payload, base_env, rng):
    samples = {name: [] for name in programs}
    expected = None
    for name, (command, backend) in programs.items():
        env = dict(base_env, MORU_LAUNCHER_BACKEND=backend)
        for _ in range(2):
            result = rows(subprocess.run([str(command), *arguments], input=payload,
                                        capture_output=True, env=env, timeout=10))
            if expected is None:
                expected = result
            if result != expected:
                raise AssertionError("launcher output parity failed before measurement")
    for _ in range(30):
        order = list(programs)
        rng.shuffle(order)
        for name in order:
            command, backend = programs[name]
            env = dict(base_env, MORU_LAUNCHER_BACKEND=backend)
            started = time.perf_counter_ns()
            result = subprocess.run([str(command), *arguments], input=payload,
                                    capture_output=True, env=env, timeout=10)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if rows(result) != expected:
                raise AssertionError("launcher output parity failed during measurement")
            samples[name].append(elapsed)
    return {name: {"n": len(values), "median_ms": statistics.median(values),
                   "p95_ms": sorted(values)[28], "samples_ms": values}
            for name, values in samples.items()}


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    if not NATIVE.is_file():
        raise RuntimeError("build and test the native runtime first")
    state = ROOT / ".moru/native"
    output = state / "launcher-benchmark.json"
    report = {"status": "in_progress", "platform": platform.platform(), "python": sys.version.split()[0],
              "native_sha256": hashlib.sha256(NATIVE.read_bytes()).hexdigest(),
              "conditions": "30 fresh samples per mode/case; warm filesystem and prepared Python bytecode; randomized sequential mode order; setup/build/parent JSON validation excluded; host exclusivity not guaranteed",
              "scope": "actual temporary-home stable launcher; legacy case is synthetic dispatch only",
              "cases": {}}
    rng = random.Random(1031)
    with tempfile.TemporaryDirectory(prefix="native-launcher-benchmark-") as tmp:
        base = Path(tmp)
        home = base / "home"
        install(home)
        launcher = home / ".moru/bin/moru-hook"
        if not launcher.read_text().startswith("#!/bin/sh"):
            raise AssertionError("native launcher was not selected")
        reference = base / "python-reference"
        reference.write_text(_launcher_script_text())
        reference.chmod(0o755)
        fixture = CheckoutFixtures(base / "git")
        legacy = fixture_root(base / "legacy", 'print(\'{"legacy":"ok"}\')\n')
        env = environment()
        env.update(HOME=str(home), MORU_HOME=str(ROOT), MORU_HOOK_SOFT_FAIL="0",
                   PYTHONPYCACHEPREFIX=str(state / "launcher-bytecode"))
        warm_env = dict(env)
        warm_env.pop("PYTHONDONTWRITEBYTECODE", None)
        rows(subprocess.run([str(reference), "checkout-identity"], input=request(fixture.main),
                            env=warm_env, capture_output=True, timeout=10))
        programs = {"native_auto": (launcher, "auto"), "native_forced": (launcher, "rust"),
                    "python_reference": (reference, "python")}
        report["launcher_sha256"] = hashlib.sha256(launcher.read_bytes()).hexdigest()
        report["cases"]["checkout_identity"] = measure(programs, ["checkout-identity"], request(fixture.main), env, rng)
        save(output, report)
        report["cases"]["legacy_dispatch"] = measure(programs, ["workflow"], b"", dict(env, MORU_HOME=str(legacy)), rng)
    report["status"] = "complete"
    save(output, report)
    print(json.dumps({"report": str(output), "medians_ms": {
        case: {mode: value["median_ms"] for mode, value in data.items()}
        for case, data in report["cases"].items()}}, indent=2))


if __name__ == "__main__":
    main()
