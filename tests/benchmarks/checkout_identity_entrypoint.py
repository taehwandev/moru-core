"""Measure the actual stage-one entrypoint against its Python rollback path.

Build and pass runtime parity tests first. Setup and warmups are excluded;
timings include process startup, stdio and operation; parent decoding is excluded.
This does not measure installed hooks or overall agent/token performance.
"""

from __future__ import annotations

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

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "tests"))
from checkout_identity_support import BINARY, WRAPPER, CheckoutFixtures, environment, request, rows


def summary(values):
    return {"n": len(values), "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[28], "samples_ms": values}


def measure(payload, expected, rng):
    samples = {"rust": [], "python": []}
    for backend in samples:
        for _ in range(2):
            result = subprocess.run([str(WRAPPER)], input=payload, capture_output=True,
                                    env=environment(backend), timeout=10)
            if rows(result) != expected:
                raise AssertionError("entrypoint parity failed before timing")
    for _ in range(30):
        order = list(samples)
        rng.shuffle(order)
        for backend in order:
            started = time.perf_counter_ns()
            result = subprocess.run([str(WRAPPER)], input=payload, capture_output=True,
                                    env=environment(backend), timeout=10)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if rows(result) != expected:
                raise AssertionError("entrypoint parity failed during timing")
            samples[backend].append(elapsed)
    return {backend: summary(values) for backend, values in samples.items()}


def main():
    if not BINARY.is_file():
        raise RuntimeError("build the native runtime first")
    state = PROJECT / ".moru/native"
    cache = state / "python-bytecode"
    result = {"platform": platform.platform(), "python": sys.version.split()[0],
              "conditions": "fresh process; warmed filesystem; prepared Python bytecode; randomized sequential order; 30 samples per backend/case; host exclusivity not guaranteed",
              "scope": "direct checkout entrypoint, not installed hooks or whole Core",
              "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(), "cases": {}}
    rng = random.Random(1031)
    with tempfile.TemporaryDirectory(prefix="checkout-entrypoint-benchmark-") as tmp:
        fixture = CheckoutFixtures(tmp)
        env = environment("python")
        env["PYTHONPYCACHEPREFIX"] = str(cache)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        warm = subprocess.run([str(WRAPPER)], input=request(fixture.main), env=env,
                              capture_output=True, timeout=10)
        rows(warm)
        os.environ["PYTHONPYCACHEPREFIX"] = str(cache)
        for name, root in (("main", fixture.main), ("linked", fixture.linked), ("detached", fixture.detached)):
            payload = request(root)
            expected = rows(subprocess.run([str(WRAPPER)], input=payload, env=environment("python"),
                                           capture_output=True, timeout=10))
            result["cases"][name] = measure(payload, expected, rng)
    output = state / "stage-one-benchmark.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"report": str(output), "medians_ms": {
        case: {backend: values["median_ms"] for backend, values in data.items()}
        for case, data in result["cases"].items()}}, indent=2))


if __name__ == "__main__":
    main()
