#!/usr/bin/env python3
"""Compare real startup-reference helpers with isolated, on-disk memory stores.

This is a local ablation, not an inference, full-startup or reasoning benchmark.
The baseline hook comes from Git; other dependencies are the current checkout.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_project_memory as memory


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def hooks(revision):
    baseline_sha = git(ROOT, "rev-parse", "--verify", revision + "^{commit}")
    source = git(ROOT, "show", baseline_sha + ":scripts/agent-hook.py")
    baseline = types.ModuleType("reference_ablation_baseline")
    baseline.__file__ = str(ROOT / "scripts/agent-hook.py")
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, baseline.__file__, "exec"), baseline.__dict__)
    spec = importlib.util.spec_from_file_location("reference_ablation_candidate", baseline.__file__)
    candidate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = candidate
    spec.loader.exec_module(candidate)
    assert callable(baseline._start_reference_lines)
    return baseline_sha, baseline, candidate


def fixture(root, count):
    project = root / "project"
    project.mkdir()
    git(project, "init", "-q")
    (project / "README.md").write_text("Synthetic queue delivery contract.\n", encoding="utf-8")
    git(project, "add", "README.md")
    git(project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic fixture")
    blob = git(project, "hash-object", "--no-filters", "--", "README.md")
    store = memory.store_dir(project)
    store.mkdir(parents=True)
    for number in range(count):
        record = dict(schema_version=1, id=f"{number + 1:016x}", status="active",
                      body=f"queue delivery contract item {number}", source=f"fixture{number}",
                      scope="all", review_on="2099-01-01")
        if number < 3:
            record["source_files"] = [{"path": "README.md", "blob": blob}]
        record["digest"] = memory._digest(record)
        (store / (record["id"] + ".json")).write_text(json.dumps(record), encoding="utf-8")
    run_id = "a" * 32
    evidence = project / ".moru" / "runs" / run_id / "preflight.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps(dict(work=dict(id=run_id))), encoding="utf-8")
    return argparse.Namespace(project=project, evidence=evidence, command="test",
                              target_summary="Synthetic queue delivery", request="queue delivery",
                              surface_path=["README.md"]), store


def store_digest(store):
    digest = hashlib.sha256()
    for path in sorted(store.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def counted_run(module, args):
    reads, hashes = [], []
    read, source_blob = memory.read_record, memory._source_blob

    def read_record(path):
        reads.append(1)
        return read(path)

    def hash_source(*values, **kwargs):
        hashes.append(1)
        return source_blob(*values, **kwargs)

    with patch.object(memory, "read_record", read_record), \
            patch.object(memory, "_source_blob", hash_source):
        lines = module._start_reference_lines(args)
    encoded = "\n".join(lines)
    return dict(record_reads=len(reads), source_hash_calls=len(hashes),
                output_chars=len(encoded), output_utf8_bytes=len(encoded.encode("utf-8")),
                delivered_records=sum(line.startswith("- {") for line in lines))


def confidence_interval(differences):
    rng = random.Random(0)
    boot = sorted(statistics.median(rng.choices(differences, k=len(differences)))
                  for _ in range(2000))
    return [boot[49], boot[1949]]


def measure(baseline, candidate, args, store, count, samples):
    before = store_digest(store)
    observed = {name: counted_run(module, args)
                for name, module in (("baseline", baseline), ("candidate", candidate))}
    assert observed["baseline"]["record_reads"] == count, observed
    assert observed["candidate"] == dict(record_reads=0, source_hash_calls=0,
                                         output_chars=0, output_utf8_bytes=0, delivered_records=0), observed
    if count:
        assert observed["baseline"]["delivered_records"] > 0, observed
        assert observed["baseline"]["source_hash_calls"] == 1, observed
    times = dict(baseline=[], candidate=[])
    for sample in range(samples):
        order = (("baseline", baseline), ("candidate", candidate))
        for name, module in (order if sample % 2 == 0 else reversed(order)):
            start = time.perf_counter_ns()
            module._start_reference_lines(args)
            times[name].append((time.perf_counter_ns() - start) / 1_000_000)
    assert before == store_digest(store), "memory store was mutated"
    differences = [old - new for old, new in zip(times["baseline"], times["candidate"])]
    return dict(records=count, operations_per_call=observed, store_unchanged=True,
                milliseconds={name: dict(median=statistics.median(values), samples=values)
                              for name, values in times.items()},
                paired_saved_ms=dict(median=statistics.median(differences),
                                     bootstrap_95_ci=confidence_interval(differences)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="d77f2402f376c351bc61a0a7f0d6085f51526f89")
    parser.add_argument("--sizes", type=int, nargs="+", default=[0, 10, 1000, 3000])
    parser.add_argument("--samples", type=int, default=21)
    args = parser.parse_args()
    if not 3 <= args.samples <= 101 or any(not 0 <= size <= 10000 for size in args.sizes):
        parser.error("samples must be 3..101; sizes must be 0..10000")
    baseline_sha, baseline, candidate = hooks(args.baseline)
    results = []
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="moru-reference-ablation-") as name:
            root = Path(name)
            with patch.dict(os.environ, {"MORU_STATE_HOME": str(root / "state")}):
                values, store = fixture(root, size)
                results.append(measure(baseline, candidate, values, store, size, args.samples))
    print(json.dumps(dict(
        scope="Real startup-reference helper including work cards, disk scan and source hashes; warm OS caches",
        excludes="Full start lifecycle, process startup, model calls, token counts, judgment and native analysis reuse",
        baseline_commit=baseline_sha,
        candidate_hook_sha256=hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest(),
        dependencies="Current checkout shared by both arms; no algorithm changes in those dependencies",
        python=platform.python_version(), platform=platform.platform(), samples_per_arm=args.samples,
        interval="Exploratory paired-median percentile bootstrap, 2000 resamples, seed 0; one machine",
        results=results), indent=2))


if __name__ == "__main__":
    main()
