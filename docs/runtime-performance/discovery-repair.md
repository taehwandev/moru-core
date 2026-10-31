---
keyflow_id: sys_discovery_repair_performance
status: review
type: ai-generated
---

# Discovery follow-up: remove repeated path resolution

## Verified work and rejected alternative

Immediate baseline: `5958ffe0`; pre-batch baseline: `9e166efd`. The previous
batch retained small/file-heavy wall regressions. This follow-up removes
observable duplicate work and separates child CPU from elapsed time rather
than assuming that every delay is caused by imports or host scheduling.

A fresh import profile observed about 0.654 ms in project_facts and 0.306 ms
in literal_boundary. That single profile does not explain the full earlier
wall differences. The record type and matcher remain unchanged.

Candidate construction already resolves its path. A new build-and-add helper
sets aliases before merging, then reuses that producer's resolved-or-fallback
path immediately. All core producer/collector call sites use it, including
workspace groups. Operation tests verify **two resolver calls become one**.
The original generic add_candidate API still resolves raw relative/symlink
input and mutates candidate.path before merging. No cached path/trust flag
survives a call. An entry manifest similarly uses one resolved-cwd observation
for discovery and reported cwd instead of resolving it twice.

The helper shares the original merge implementation: max confidence and stable
unique lists, aliases included. New calls observe symlink retargeting. Persistent
resolver failure retains the same absolute fallback; the new pipeline does not
make a second attempt within that producer/collector operation. Neither old
nor new filesystem discovery is an atomic snapshot under concurrent mutation.

A proposed `any(Path.exists(...))` shortcut was **rejected**. The old full
instruction list can raise on a later file even when AGENTS.md exists; stopping
at the first hit hides that error. A forced later PermissionError falsifies the
shortcut. Original presence-probe ordering and error behavior are retained.
AGY's conditional design approval was not treated as executed evidence.

## Collaboration and measurement

Claude supplied the POSIX process-measurement utility; AGY reviewed canonical
merge, aliases, raw callers, symlink/cwd and timing preconditions from a generic
source-free brief. The lead owns runtime changes, counterexamples, driver,
integration and final verification. No new production module, dependency,
native build, model call or persistent cache is introduced.

One serial benchmark compares all three revisions through the same generated
launcher, with sibling source snapshots, verified current runtime bytes,
prepared bytecode and explicit synthetic roots/registry. Twenty-four rounds
balance all six three-way orders. Five workloads produce **360 timed child
invocations**, plus warmups. A 90-second timing budget includes warmups and
stops with an explicit incomplete result if exhausted; setup is outside it.
This run completed every case within that budget. No further timing loop ran.

CPU is the difference of RUSAGE_CHILDREN user/system counters around each
waited child. The driver must not spawn/reap another child concurrently.
Wall time is monotonic elapsed subprocess time. Their difference cannot identify
scheduler delay versus I/O wait or parent capture overhead. It is not a cause
diagnosis. Outputs, statuses and stderr match; only declared agent-entry source
metadata paths are normalized, with pretty JSON formatting still checked.

macOS 27.0.1 arm64, Python 3.9.6, warm filesystem, unreserved host. Fixtures are
startup help, 8 directories x 3 files, 40 directories x 250 files, 600 AGENTS-marked
directories, and entry over those 600 projects with 6,000 disabled registry
records. This fixture set is compared only within this run, not pooled with
prior batches.

## Results

Median milliseconds, shown as **wall / child CPU**:

| Workload | Pre-batch `9e166efd` | Previous `5958ffe0` | Repaired |
| --- | ---: | ---: | ---: |
| Startup help | 60.5677 / 53.8170 | 61.7703 / 54.4505 | 61.0989 / 54.9285 |
| Small | 68.0787 / 59.1515 | 69.2771 / 61.1810 | 66.4004 / 59.4400 |
| File-heavy | 100.3114 / 81.6180 | 102.4776 / 83.0525 | 101.4644 / 83.1575 |
| Many, ambiguous | 390.6140 / 332.5460 | 250.5139 / 211.4680 | 242.6810 / 203.1820 |
| Entry with registry | 347.7037 / 296.9910 | 229.8123 / 199.5720 | 209.3355 / 180.3420 |

Entry saves **20.48 ms wall and 19.23 ms CPU** against the immediate baseline
(about 8.9% and 9.6%). The many-project path saves 7.83 ms wall and 8.29 ms CPU.
These incremental gains do not individually reach the programme's 20% median
target for a new port; this is a duplicate-work repair, not a new native unit.
Cumulatively against pre-batch, those paths save about **38–40% wall**.

Small/file-heavy repaired medians are within **1.7 ms wall and 1.6 ms CPU** of
the pre-batch reference. A material 5 ms median regression is not reproduced in
this run. That does not prove the cause of earlier wall regressions or guarantee
that they cannot recur.

Tail values remain mixed. p95 milliseconds, **wall / child CPU**:

| Workload | Pre-batch | Previous | Repaired |
| --- | ---: | ---: | ---: |
| Startup help | 77.3882 / 70.1520 | 75.3735 / 67.9240 | 77.4922 / 67.6590 |
| Small | 76.6597 / 65.5790 | 81.0399 / 66.7800 | 78.5375 / 66.3550 |
| File-heavy | 126.8895 / 99.7230 | 138.3579 / 95.5910 | 137.5211 / 101.2200 |
| Many, ambiguous | 493.4787 / 382.0080 | 324.7533 / 241.0520 | 427.5670 / 254.8480 |
| Entry with registry | 517.4618 / 373.7440 | 299.9494 / 239.1790 | 304.6005 / 241.2570 |

In particular, many-project p95 is slower than the immediate baseline even
though its median improves. This is not an all-tail or cross-host guarantee.
Keep the earlier batch's negative observations. Broad rollout remains a later
decision; this bounded repair establishes removed work and local median bounds.

## Reproduction and verification

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_discovery_repair
PYTHONPATH=scripts:tests python3 -B tests/benchmark_discovery_repair.py --samples 24 --budget-seconds 90
```

Eight repair tests cover single resolution, generic raw API behavior, aliases
before collisions, legacy/new merge equivalence, one cwd observation, later
probe errors, next-call symlink freshness, resolver fallback, and process
stdin/bytes/nonzero/error behavior. The 36 existing discovery/batch/scan tests
passed this run's initial integration check; those results are reused because
their runtime inputs did not change afterward. Two initial score assertions
were corrected to account for an AGENTS-only fixture having no project marker;
the production scoring rule was not changed.

`.moru/performance/discovery-repair.json` retains raw wall/user/system/CPU
samples, complete-case status and source/measurement hashes. The source and
measurement utilities match the recorded hashes. Source inspection/profile
and operation-count evidence complement timing; they do not substitute for
real installed runtime evidence. Main, remote and global installation remain
unchanged. No token or whole-agent improvement is claimed.
