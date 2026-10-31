---
keyflow_id: sys_runtime_startup_paths_result
status: review
type: ai-generated
---

# Status and next-action startup

## Decision and scope

Keep the bounded import deferrals on the performance branch. This is a Python
startup optimization for [inventory](../native-runtime-migration.md) units 8
and 15, not another Rust conversion. No-run next and validated basic status
save 13.60 ms and 6.39 ms median wall time, respectively. Their 13.9% and 8.7%
gains do **not** meet the [programme](prd.md) frequent-path 20% target. Active
next has no measured benefit. Main integration and global activation remain
pending; help-only gains do not establish workflow acceptance or token savings.

The inventory now has changes in eight boundaries: four involving native code
(including the partial launcher), four retaining Python. Eight of 52 overall,
or eight of 30 primary units, is scope coverage, not effort-weighted completion.
The remaining 44 are retained candidates rather than a mandatory rewrite list.

## Owned changes

- `agent-os-status.py`: parse arguments before importing observability; import
  the API validator only for `--validate`.
- `agent_observability.py`: load hashing in run collection, SQLite after each
  reader's existing missing-input return, and statistics in run summarization.
  Basic status does not load optional trend libraries.
- `agent_next_action.py`: keep runtime-session discovery available; defer gate,
  review, route, skill and template imports until readable active evidence is
  present. Gate selection and generated commands are unchanged.
- `agent_worker_evidence.py`: defer the gate-path helper into its two reservation
  producers. This removes an indirect eager dependency through runtime-session
  discovery. Token, symlink, ownership, path and ledger checks are unchanged.

The parent owns runtime, fixtures, integration and evidence. Claude supplied
the fresh-child import tripwire; AGY supplied strict status normalization using
generic briefs without source or private configuration. Both returned through
existing CLI access. Their code was checked locally; responses alone are not
verification. No paid API fallback, dependency or persistent service was added.

## Falsification and behavior

Fresh subprocess checks reject blocked imports, including already-preloaded
ones. Status help succeeds with observability and API imports blocked; validated
basic status succeeds with SQLite and statistics blocked. Next help and no-run
inspection succeed with gate evidence and review imports blocked. A deliberate
SQLite import fails the same tripwire, and spaces, shell-looking text and
newlines remain argv data. This guard is functional evidence, never a timer.

The first checks exposed two real implementation gaps: the statistics import
was temporarily missing from the trend summarizer, and runtime-session discovery
still loaded gate evidence indirectly through worker evidence. Both were fixed
before timing. The corrected trend checks and 30 worker/session checks passed;
the latter retain reservation and negative-authority coverage. There was no
runtime policy rewrite to satisfy the tripwire.

The focused suite covers six startup/comparator checks, 13 existing next/status/API
checks, 30 worker/session checks and two inventory checks: 51 unique tests.
Successful unchanged cases were reused; only failed or newly affected checks
were rerun. Existing trend tests use synthetic databases, not actual usage data.

## Measurement

One bounded run compares frozen baseline `d00fb87b1fb4416cb2b79cc669d29182a03f2955`
with a sibling snapshot overlaying exactly the four runtime files above. Both
use the same generated temporary-home launcher, synthetic project, registry,
scheduler and events. Active next gets explicit synthetic evidence; no-run next
gets no session identity. Trend timing uses explicitly absent temporary database
paths. No actual usage database or private configured command is read.

Python 3.9.6, macOS 27.0.1 arm64. Prepared bytecode and warm filesystem; one warmup
per variant/case, then 24 balanced randomized AB/BA pairs per case. This yields
288 timed child processes across six cases. Child CPU is user plus system time;
wall includes process/launcher overhead. Guard bootstrap is excluded. The host
is unreserved, so tails and small differences are observations, not causal
diagnoses or cross-machine guarantees. The auto launcher deliberately delegates
these aliases to Python; its native fast path handles other aliases. This does
not measure the installed global runtime or native fast-path overhead.

All rows show reference to candidate, in milliseconds. p95 uses the recorded
nearest-rank sample statistic; this is a small single-run sample.

| Path | Wall median | Wall p95 | CPU median | CPU p95 |
| --- | ---: | ---: | ---: | ---: |
| Next, no active run | 97.855 → 84.254 | 115.290 → 92.653 | 84.124 → 69.972 | 93.171 → 76.271 |
| Validated basic status | 73.072 → 66.687 | 82.094 → 80.113 | 63.457 → 57.426 | 68.865 → 59.777 |
| Next, active control | 99.830 → 100.346 | 114.068 → 111.612 | 90.963 → 91.318 | 103.605 → 101.688 |
| Trends, missing DB control | 67.024 → 61.656 | 74.805 → 70.077 | 61.253 → 56.305 | 68.739 → 63.744 |
| Next help | 77.640 → 62.458 | 83.028 → 67.619 | 72.112 → 56.945 | 76.914 → 61.506 |
| Status help | 67.321 → 44.589 | 69.833 → 48.177 | 61.599 → 39.171 | 64.122 → 42.013 |

Active next is 0.516 ms slower at the median (about 0.5%); no speedup is claimed
for it. Help medians improve 19.6% and 33.8%, but help is not a proxy for frequent
working paths. Full trend aggregation latency, peak memory, cold-disk behavior,
other hosts and live task latency remain unmeasured.

Each invocation requires equal exit status, stderr and output. Help and active
next compare exact bytes. No-run next replaces only the single source-root
token in its copyable command after checking canonical JSON and no-run status.
Validated status replaces only nested `snapshot_id` and `captured_at`; trends
replace only root `captured_at`. IDs must be 32 lowercase hex characters,
timestamps valid UTC, and input canonical JSON. Unknown fields and list order
remain significant. No timing or functional fields are broadly stripped.

## Reproduction and retained evidence

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_startup_paths test_agent_next_action test_agent_observability test_agent_os_api test_agent_worker_evidence test_agent_runtime_session
PYTHONPATH=scripts:tests python3 -B tests/benchmark_startup_paths.py --samples 24 --budget-seconds 90
```

The benchmark preserves partial samples on budget exhaustion rather than
retrying until a pass. This run completed all cases within its budget. Raw
samples, summaries, output hashes, baseline revision and runtime/utility hashes
are in ignored `.moru/performance/startup-paths.json`. Runtime SHA-256 values:

| Source | SHA-256 |
| --- | --- |
| agent-os-status.py | `4f4c2e5f4be46df170a584096caecd6907f284368a661748b66721ddb4ce5a6e` |
| agent_next_action.py | `2e44176b68ccd84fdceb225ec705d88f21fed33e056e73752c5f39a4bcae92d3` |
| agent_observability.py | `57804bb83da4c40453931121bae0caab82c8d3f41a798f83c426503fdfbe5216` |
| agent_worker_evidence.py | `cc730f8b4cc8e6e07973345a7362a3cd0cbe27018aeb051fd9167049e4d59167` |

Rollback is a revert of this isolated import-placement unit. No schema, stored
state, launcher installation, dependency or public API migration is required.
