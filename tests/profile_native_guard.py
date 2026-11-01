#!/usr/bin/env python3
"""Opt-in fresh-process guard probe versus the real generated callback, synthetic data only."""
import argparse
import json
from pathlib import Path
import platform
import random
import re
import statistics
import tempfile
import time

from benchmark_project_discovery import digest, summary
from discovery_process_measure import run_measured
from native_pretool_support import PROJECT, encode, environment, prepare, request
from support.native_source_inputs import pretool_contract


def profile(probe, output, count):
    if platform.system() != "Darwin":
        raise RuntimeError("BSD time RSS probe requires macOS; no cross-host claim")
    receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
    for relative, expected in receipt["source_sha256"].items():
        if digest(PROJECT / relative) != expected:
            raise RuntimeError("stale runtime source receipt")
    native = PROJECT / ".moru/native/bin/moru-native-launcher"
    if digest(native) != receipt["launcher"]["sha256"]:
        raise RuntimeError("stale native binary receipt")
    sources, directories = pretool_contract(PROJECT)
    samples = {mode: [] for mode in ("guard", "callback")}
    report = {"status": "running", "platform": platform.platform(), "samples_per_mode": count,
              "python": platform.python_version(), "budget_seconds": 90,
              "method": ("balanced serial fresh processes, warm filesystem; internal guard timing "
                         "is a subset measurement, not a cache or an isolated hash-only measurement"),
              "source_sha256": receipt["source_sha256"], "binary": receipt["launcher"],
              "probe_sha256": digest(probe), "rustc": receipt["rustc"],
              "utility_sha256": {p: digest(PROJECT / p) for p in (
                  "tests/profile_native_guard.py", "tests/native_pretool_support.py",
                  "tests/discovery_process_measure.py", "tests/benchmark_project_discovery.py",
                  "native/checkout-identity/examples/callback_guard_profile.rs")},
              "contract_sources": len(sources), "contract_directories": len(directories),
              "samples": samples}
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 90
    try:
        with tempfile.TemporaryDirectory(prefix="native-guard-profile-") as tmp:
            base = Path(tmp).resolve()
            launcher, project = prepare(base)
            (project / "notes.txt").write_text("synthetic\n")
            env = environment(base)
            orders = [["guard", "callback"], ["callback", "guard"]] * (count // 2)
            random.Random(61035).shuffle(orders)
            for warm, order in [(True, ["guard", "callback"]), *[(False, o) for o in orders]]:
                for mode in order:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError("guard profiling budget exhausted")
                    metrics_file = base / "time.txt"
                    argv = [str(probe), str(launcher)] if mode == "guard" else [str(launcher), "claude-pretool-gate"]
                    done, metrics = run_measured(
                        ["/usr/bin/time", "-l", "-o", str(metrics_file), *argv],
                        env=env, cwd=project, input_bytes=encode(request(project, "cat notes.txt")),
                        timeout=min(10, left))
                    if done.returncode or done.stderr or (mode == "callback" and done.stdout):
                        raise RuntimeError(f"unexpected {mode} result: {done.returncode}, {done.stderr!r}")
                    if mode == "guard":
                        result = json.loads(done.stdout)
                        if not result["valid"]:
                            raise RuntimeError("guard rejected fixture")
                        metrics["guard_ms"] = result["guard_ms"]
                    matches = re.findall(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$", metrics_file.read_text())
                    if len(matches) != 1:
                        raise RuntimeError("invalid BSD time RSS output")
                    metrics["peak_rss_bytes"] = int(matches[0])
                    if not warm:
                        samples[mode].append(metrics)
                    output.write_text(json.dumps(report, indent=2) + "\n")
        report["summary"] = {
            mode: {key: ({"median_bytes": statistics.median(row[key] for row in rows),
                         "p95_bytes": sorted(row[key] for row in rows)[(95 * len(rows) + 99) // 100 - 1]}
                        if key == "peak_rss_bytes" else summary([row[key] for row in rows]))
                   for key in rows[0]}
            for mode, rows in samples.items()}
        report["status"] = "complete"
        print(json.dumps({mode: {key: {k: v for k, v in values.items() if not k.startswith("samples_")}
                                for key, values in fields.items()}
                          for mode, fields in report["summary"].items()}, indent=2))
    except Exception as error:
        report.update(status="failed", error=type(error).__name__)
        raise
    finally:
        report["elapsed_seconds"] = 90 - (deadline - time.monotonic())
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("samples must be even and at least 24")
    profile(args.probe.resolve(), args.output, args.samples)
