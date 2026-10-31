#!/usr/bin/env python3
"""Bounded generated-callback CPU/wall and macOS per-process peak RSS."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import statistics
import subprocess
import tempfile
import time

from benchmark_project_discovery import digest, summary
from discovery_process_measure import run_measured
from native_pretool_support import PROJECT, environment, prepare, request, encode
from support.native_source_inputs import pretool_contract


def measure(output, count, budget):
    if platform.system() != "Darwin":
        raise RuntimeError("this RSS probe requires macOS /usr/bin/time -l; no cross-host claim")
    receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
    sources, directories = pretool_contract(PROJECT)
    report = {"status": "running", "platform": platform.platform(),
              "python": platform.python_version(), "rustc": receipt["rustc"],
              "samples_per_variant": count, "budget_seconds": budget, "seed": 61034,
              "method": "same generated callback and source, auto native versus forced Python; balanced AB/BA, isolated prepared bytecode, warm filesystem, unreserved host; serial child CPU/wall; BSD time per-process maximum RSS bytes",
              "source_sha256": receipt["source_sha256"], "binary": receipt["launcher"],
              "contract_sources": len(sources), "contract_directories": len(directories),
              "utility_sha256": {p: digest(PROJECT / p) for p in (
                  "tests/benchmark_native_pretool.py", "tests/native_pretool_support.py",
                  "tests/discovery_process_measure.py", "tests/benchmark_project_discovery.py")},
              "cases": {}}
    deadline = time.monotonic() + budget
    rng = random.Random(61034)
    try:
        with tempfile.TemporaryDirectory(prefix="native-pretool-bench-") as tmp:
            base = Path(tmp).resolve()
            launcher, project = prepare(base)
            transcript = base / "synthetic-transcript.jsonl"
            transcript.write_text(json.dumps({"payload": {"type": "custom_tool_call", "input":
                'await tools.exec_command({cmd:"git status --short",workdir:"' + str(project) + '"})'}}) + "\n")
            cases = [
                ("claude_status", "claude-pretool-gate", request(project)),
                ("codex_status_transcript", "codex-pretool-gate", request(project, transcript_path=str(transcript))),
                ("claude_cached_diff", "claude-pretool-gate", request(project, "git diff --cached --stat")),
                ("codex_pwd", "codex-pretool-gate", request(project, "pwd")),
                ("quoted_fallback", "claude-pretool-gate", request(project, "git status '--short'")),
            ]
            for name, alias, payload in cases:
                values = {v: {k: [] for k in ("wall_ms", "cpu_ms", "user_ms", "system_ms", "peak_rss_bytes")}
                          for v in ("python", "auto")}
                row = {"samples": values, "complete": False,
                       "rss_comparable": name != "quoted_fallback"}
                report["cases"][name] = row
                orders = [["python", "auto"], ["auto", "python"]] * (count // 2)
                rng.shuffle(orders)
                expected = None
                for warm, order in [(True, ["python", "auto"]), *[(False, order) for order in orders]]:
                    for variant in order:
                        left = deadline - time.monotonic()
                        if left < .05:
                            raise TimeoutError("native pretool timing budget exhausted")
                        env = environment(base)
                        env.update(MORU_LAUNCHER_BACKEND=variant, PYTHONPYCACHEPREFIX=str(base / "bytecode"))
                        if warm:
                            env.pop("PYTHONDONTWRITEBYTECODE")
                        rss_file = base / "time-metrics.txt"
                        done, metrics = run_measured(
                            ["/usr/bin/time", "-l", "-o", str(rss_file), str(launcher), alias],
                            env=env, cwd=project, input_bytes=encode(payload), timeout=min(10, left))
                        result = done.returncode, done.stdout, done.stderr
                        expected = result if expected is None else expected
                        if result != expected or result != (0, b"", b""):
                            raise RuntimeError(f"callback result mismatch: {name}/{variant}: {done.stderr[:300]!r}")
                        matches = re.findall(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$", rss_file.read_text())
                        if len(matches) != 1:
                            raise RuntimeError("unrecognized BSD time maximum RSS format")
                        if not warm:
                            for key, value in metrics.items():
                                values[variant][key].append(value)
                            values[variant]["peak_rss_bytes"].append(int(matches[0]))
                    output.write_text(json.dumps(report, indent=2) + "\n")
                row.update(complete=True, output_sha256=hashlib.sha256(expected[1]).hexdigest(),
                           summary={v: {k: ({"median_bytes": statistics.median(times),
                                           "p95_bytes": sorted(times)[(95 * len(times) + 99) // 100 - 1],
                                           "samples_bytes": times} if k == "peak_rss_bytes" else summary(times))
                                        for k, times in fields.items()}
                                    for v, fields in values.items()})
                print(json.dumps({name: {v: {k: {a: n for a, n in d.items() if not a.startswith("samples_")}
                                            for k, d in fields.items() if k in ("wall_ms", "cpu_ms", "peak_rss_bytes")}
                                         for v, fields in row["summary"].items()}}), flush=True)
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
    parser.add_argument("--output", type=Path, default=PROJECT / ".moru/performance/native-pretool.json")
    args = parser.parse_args()
    if args.samples < 24 or args.samples % 2:
        parser.error("samples must be even and at least 24")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(0 if measure(args.output, args.samples, args.budget_seconds) else 3)


if __name__ == "__main__":
    main()
