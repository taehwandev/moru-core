#!/usr/bin/env python3
"""Paired native/native SHA-backend comparison in isolated, verified source snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time

from benchmark_project_discovery import digest, summary
from discovery_process_measure import run_measured
from native_launcher_support import copied_build_root, install
from native_next_support import prepare_next
from native_pretool_support import PROJECT, encode, environment, request
from support.native_source_inputs import pretool_contract, source_inputs

MARKERS = ("AGENTS.md", "index.md", "common/skills/agent-operating-skill/SKILL.md")


def validate(root):
    receipt = json.loads((root / ".moru/native/build.json").read_text())
    if set(receipt["source_sha256"]) != {p.relative_to(root).as_posix() for p in source_inputs(root)}:
        raise RuntimeError("unexpected source receipt paths")
    for relative, expected in receipt["source_sha256"].items():
        if digest(root / relative) != expected:
            raise RuntimeError("source snapshot does not match its receipt")
    for name, item in (("moru-native-launcher", receipt["launcher"]), ("moru-checkout-identity", receipt)):
        if digest(root / ".moru/native/bin" / name) != item["sha256"]:
            raise RuntimeError("native snapshot does not match its receipt")
    binary = {**receipt["launcher"], "binary": str(root / ".moru/native/bin/moru-native-launcher")}
    return {"source_sha256": receipt["source_sha256"], "binary": binary,
            "rustc": receipt["rustc"], "markers_sha256": {p: digest(root / p) for p in MARKERS}}


def capture(destination):
    if destination.exists():
        raise RuntimeError("snapshot destination already exists; do not overwrite original evidence")
    receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
    validate(PROJECT)
    for relative, expected in receipt["source_sha256"].items():
        if digest(PROJECT / relative) != expected:
            raise RuntimeError("build current source before snapshotting")
    copied_build_root(destination)
    shutil.copy2(PROJECT / ".moru/native/bin/moru-checkout-identity",
                 destination / ".moru/native/bin/moru-checkout-identity")
    for relative in pretool_contract(PROJECT)[1]:
        (destination / relative).mkdir(parents=True, exist_ok=True)
    for relative in MARKERS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / relative, target)
    return validate(destination)


def prepare(base, roots):
    _entry, project = prepare_next(base)
    (project / "notes.txt").write_text("TODO synthetic\n")
    transcript = base / "synthetic.jsonl"
    transcript.write_text(json.dumps({"payload": {"type": "function_call", "arguments":
        json.dumps({"cmd": "cat notes.txt", "workdir": str(project)})}}) + "\n")
    entries, environments = {}, {}
    for variant, root in roots.items():
        home = base / ("home-" + variant)
        install(home, root)
        # The installer returns metadata; use its stable documented location.
        entry = home / ".moru/bin/moru-hook"
        env = environment(base, root)
        env.update(HOME=str(home))
        payload = encode({"cwd": str(project), "session_id": "synthetic-sha"})
        for runtime in ("claude", "codex"):
            for _ in range(2):
                done = subprocess.run([str(entry), "mailbox-hook", "deliver", "--runtime", runtime],
                    input=payload, capture_output=True, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                    cwd=project, timeout=10)
                if done.returncode or done.stderr:
                    raise RuntimeError("mailbox fixture warmup failed")
        done = subprocess.run([str(entry), "codex-stop-gate"], input=payload, capture_output=True,
            env={**env, "MORU_LAUNCHER_BACKEND": "python"}, cwd=project, timeout=10)
        if (done.returncode, done.stdout, done.stderr) != (0, b"", b""):
            raise RuntimeError("Stop fixture warmup failed")
        entries[variant], environments[variant] = entry, env
    git_only = base / "git-only"
    git_only.mkdir()
    (git_only / "git").symlink_to(shutil.which("git"))
    cases = [("claude_file", ["claude-pretool-gate"], encode(request(project, "cat notes.txt"))),
             ("codex_transcript", ["codex-pretool-gate"], encode(request(project,
                 "cat notes.txt", transcript_path=str(transcript)))),
             ("quiet_mailbox", ["mailbox-hook", "deliver", "--runtime", "claude"], payload),
             ("quiet_stop", ["codex-stop-gate"], payload),
             ("next_json", ["next", "--project", str(project), "--format", "json"], b"")]
    for variant in roots:
        for name, args, data in cases:
            done = subprocess.run([str(entries[variant]), *args], input=data, capture_output=True,
                env={**environments[variant], "PATH": str(git_only)}, cwd=project, timeout=10)
            comparable(done, name, roots[variant], entries[variant])
    return project, entries, environments, cases


def comparable(done, name, root, entry):
    if done.returncode or done.stderr:
        raise RuntimeError(f"native callback failed: {root.name}/{name}: "
                           f"{done.returncode}, {done.stderr!r}; entry={entry}")
    if name != "next_json":
        if done.stdout:
            raise RuntimeError("quiet callback emitted output")
        return done.stdout
    value = json.loads(done.stdout)
    if done.stdout != (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode():
        raise RuntimeError("next JSON formatting changed")
    if value["status"] != "no_active_run":
        raise RuntimeError("unexpected next advice")
    command = value["copyable_command"]
    for actual, replacement in ((str(entry), "<ENTRY>"), (str(root), "<SOURCE>")):
        if command.count(actual) != 1:
            raise RuntimeError("unrecognized normalization boundary")
        command = command.replace(actual, replacement, 1)
    value["copyable_command"] = command
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def measure(reference, output, count, budget):
    if platform.system() != "Darwin":
        raise RuntimeError("BSD time RSS measurement requires macOS")
    reference = reference.resolve()
    roots = {"reference": reference, "candidate": reference.parent / "candidate"}
    if roots["candidate"].exists():
        saved, current = validate(roots["candidate"]), validate(PROJECT)
        if (saved["source_sha256"] != current["source_sha256"]
                or saved["binary"]["sha256"] != current["binary"]["sha256"]
                or saved["markers_sha256"] != current["markers_sha256"]):
            raise RuntimeError("candidate changed; preserve the old snapshot and choose a new experiment directory")
    else:
        capture(roots["candidate"])
    identities = {variant: validate(root) for variant, root in roots.items()}
    if (pretool_contract(roots["reference"]) != pretool_contract(roots["candidate"])
            or identities["reference"]["markers_sha256"] != identities["candidate"]["markers_sha256"]):
        raise RuntimeError("runtime Python or marker inputs differ between variants")
    utility = {p: digest(PROJECT / p) for p in ("tests/benchmark_native_sha.py",
        "tests/benchmark_project_discovery.py", "tests/discovery_process_measure.py",
        "tests/native_launcher_support.py", "tests/native_next_support.py", "tests/native_pretool_support.py")}
    report = {"status": "running", "platform": platform.platform(), "samples_per_variant": count,
              "method": ("balanced serial native/native fresh processes; equal-length sibling source "
                         "and home names; warm filesystem; no-Python proof before timing; build/setup excluded"),
              "variants": identities, "utility_sha256": utility, "cases": {}, "budget_seconds": budget}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="native-sha-bench-") as tmp:
            project, entries, environments, cases = prepare(Path(tmp).resolve(), roots)
            started = time.monotonic()
            deadline = started + budget
            rng = random.Random(61038)
            for name, args, data in cases:
                values = {v: [] for v in roots}
                report["cases"][name] = {"samples": values, "complete": False}
                orders = [["reference", "candidate"], ["candidate", "reference"]] * (count // 2)
                rng.shuffle(orders)
                expected = None
                for warm, order in [(True, list(roots)), *[(False, o) for o in orders]]:
                    for variant in order:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            raise TimeoutError("SHA timing budget exhausted")
                        metrics_file = Path(tmp) / "metrics.txt"
                        done, metrics = run_measured(["/usr/bin/time", "-l", "-o", str(metrics_file),
                            str(entries[variant]), *args], env=environments[variant], cwd=project,
                            input_bytes=data, timeout=min(10, left))
                        result = comparable(done, name, roots[variant], entries[variant])
                        expected = result if expected is None else expected
                        if result != expected:
                            raise RuntimeError("native variants disagree")
                        matches = re.findall(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$", metrics_file.read_text())
                        if len(matches) != 1:
                            raise RuntimeError("invalid BSD time RSS output")
                        metrics["peak_rss_bytes"] = int(matches[0])
                        if not warm:
                            values[variant].append(metrics)
                    output.write_text(json.dumps(report, indent=2) + "\n")
                fields = {v: {key: ({"median_bytes": statistics.median(r[key] for r in rows),
                    "p95_bytes": sorted(r[key] for r in rows)[(95 * len(rows) + 99) // 100 - 1]}
                    if key == "peak_rss_bytes" else summary([r[key] for r in rows])) for key in rows[0]}
                    for v, rows in values.items()}
                report["cases"][name].update(complete=True, summary=fields,
                    output_sha256=hashlib.sha256(expected).hexdigest())
                print(json.dumps({name: {v: {key: {k: n for k, n in item.items() if not k.startswith("samples_")}
                    for key, item in f.items() if key in ("wall_ms", "cpu_ms", "peak_rss_bytes")}
                    for v, f in fields.items()}}), flush=True)
            report.update(status="complete", elapsed_seconds=time.monotonic() - started)
        for variant, root in roots.items():
            if validate(root) != identities[variant]:
                raise RuntimeError("snapshot changed during measurement")
    except Exception as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--budget-seconds", type=float, default=90)
    args = parser.parse_args()
    if args.capture:
        capture(args.capture.resolve())
        print("verified native snapshot captured")
    elif args.reference and args.output and args.samples >= 24 and args.samples % 2 == 0:
        measure(args.reference, args.output, args.samples, args.budget_seconds)
    else:
        parser.error("capture a reference, or supply reference/output and an even sample count >=24")
