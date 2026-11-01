---
keyflow_id: sys_native_runtime_status
status: review
type: ai-generated
---

# Prepared runtime status in Rust

## Boundary and behavior

Baseline: performance-branch commit
`1e520405b3ba4066610ac35169700b13f8a6fa9d`. The preceding batch removed unnecessary
Python imports; this increment adds actual native execution for basic and
validated `agent-os-status` on prepared local state. It adds no inventory unit:
the existing status boundary becomes partial native coverage.

The generated launcher now routes this alias to the native handler in auto
mode. Default cwd, `--validate`, an absolute `--project`, and the two supported
project/validate orderings are recognized. Python rollback remains available.
Initialization, trends, other CLI forms, relative project arguments, symlinked
state/lock paths, unavailable locks, malformed or unusual data and modified
runtime Python sources retain the canonical Python implementation.

Native eligibility requires existing writable regular project/file locks,
non-symlink state paths, bounded UTF-8 JSON objects and supported string/null
counter values. Each state file is limited to 1 MiB; larger files use Python.
Missing JSON files are supported after their locks exist. No directory, data
file or lock is created by the native handler.

Lock order remains project lock, then registry, scheduler and event file locks
one at a time under that project lock. Files open with append/read permissions
like Python's `a+b`, without creation, and use nonblocking exclusive flock.
Contention delegates to Python's existing waiting behavior. All native locks
are released before fallback or formatting. A reject-only precheck avoids
scanning all runtime sources for data that cannot be handled natively; supported
paths still validate every byte of all 334 runtime Python files and seven
directory shapes, then read fresh state again under the same locks. No
precheck snapshot is returned and no cross-invocation state/hash cache exists.

The Python status and API owners remain authoritative. A developer-only
`status_contract.py` generator emits immutable API-version/manifest/adapter
snippets from those owners at build time. The artifact receipt includes that
generator and the three new Rust modules: 373 build inputs versus 369 before.
Counter aggregation and exact JSON formatting live in Rust. UUID4 values use
OS random bytes with the standard version/variant bits; UTC timestamps preserve
Python's six-digit microseconds and omission of the fraction when zero.
No runtime dependency, service, compiler installation or model call is added.

## Measurement protocol

Both source/binary versions were frozen before the candidate build. Each
temporary home uses its own frozen version's installer and generated header.
This matters: using the new header for the baseline would add a native process
to its formerly direct Python status path and inflate the improvement. A
regression test verifies that snapshot installation uses its selected source.

The accepted run contains 24 samples per variant per case, balanced serial
AB/BA order with a fixed seed, warm filesystem and an unreserved host. Real
generated callbacks prepare their own Python caches with matching interpreter,
HOME and isolated prefix. Verbose probes prove both variants read the status
owner's cache; 107 cache files per variant are hashed before/after measurement.
Build, installation and warmup are excluded. CPU is child user+system time;
RSS is BSD `time`'s command maximum rather than a concurrent process-tree sum.

Small state has two active runs, two tasks and one event. Large state has
100 runs, 200 tasks and 500 events. A relative-project and a numeric-counter
case exercise Python fallback. The already-native cat pretool is a control.
Candidate native cases pass with no Python on PATH; the two fallback cases
require Python. Only validated UUID/timestamp fields are normalized, using the
existing strict canonical-JSON normalizer. Source, artifact, entrypoint,
utility, bytecode and state hashes are retained. State and caches do not change
during timing.

## Accepted local result: 2026-11-01

Host: macOS 27.0.1 ARM64, Rust 1.94.1 and Apple Python 3.9.6. One completed run
contains 336 timed callbacks across seven cases.

| Generated callback | Wall median, before → after (ms) | Reduction | CPU median, before → after (ms) | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Basic status | 44.76 → 14.73 | 67.1% | 38.07 → 11.90 | 68.7% |
| Validated status | 42.87 → 14.74 | 65.6% | 37.99 → 11.87 | 68.7% |
| Large status | 44.74 → 15.51 | 65.3% | 38.69 → 12.45 | 67.8% |
| Large validated status | 44.24 → 15.30 | 65.4% | 38.59 → 12.32 | 68.1% |
| Relative-project fallback | 45.31 → 46.23 | -2.0% | 38.85 → 39.73 | -2.3% |
| Numeric-value fallback | 43.51 → 46.70 | -7.3% | 38.24 → 40.21 | -5.2% |
| Native cat control | 14.22 → 14.45 | -1.6% | 11.49 → 11.55 | -0.6% |

All four native status cases exceed the programme's 20% and 5 ms wall-median
targets. Python fallback still costs an extra 0.93–3.19 ms in this run. The cat
control regresses 0.23 ms; its process RSS rises 48 KiB. Do not infer a
general improvement for unrelated callbacks or statistical significance.

| Callback | Wall p95, before → after (ms) |
| --- | ---: |
| Basic status | 51.68 → 16.74 |
| Validated status | 50.32 → 19.20 |
| Large status | 53.04 → 20.01 |
| Large validated status | 51.34 → 19.59 |
| Relative fallback | 52.92 → 54.85 |
| Numeric fallback | 49.84 → 53.28 |
| Native cat control | 20.08 → 21.35 |

Fallback and control p95 regress and remain visible. These are single-host
samples with no reserved CPU; median improvement is not a tail-latency promise.
Status RSS medians fall from about 13.8 MiB to 2.5 MiB, and large-status RSS from
14.0 to 3.1 MiB. These are per-command measurements, not whole-agent CPU,
memory or token savings. The launcher grows 16,768 bytes to 897,280 bytes.

## Retained experiments and receipts

The initial implementation's generated-entry tests caught a missing auto-mode
dispatch entry and an incorrect test normalization of help text. Both were
corrected before acceptance; native-only tests now cover the actual entrypoint.
The first six-case timing run is retained. A separate numeric-data control then
showed approximately 10 ms extra fallback latency from scanning sources before
rejecting unsupported values. The reject-only precheck addresses that cost;
fresh locked reads after validation preserve the final snapshot semantics.
Pre-review ownership checks also required aggregation behind the single
`StatusSnapshot` owner. Moving it to a private associated method changed the
compiled binary hash, so the accepted timing and transport checks were repeated
on that final binary. The final comparison includes both fallback controls. These are separate
experiments, not a paired causal series across candidate revisions.

- Accepted report: `.moru/performance/native-runtime-status-owned.json`, SHA-256
  `2210558ec825c3ea0297893da5ba47e96421e1c1d2eb23e764cfcc9f92cd6e3b`.
- Baseline launcher SHA-256:
  `4ff1e1adb423cb166daa8c205b2df07cb6ff094eb8d1e56898887d6e229af84d`.
- Final launcher SHA-256:
  `bcff910686f8148a62101e2b175c7956c7eacbb0936ce782a0f711b00be48e28`.
- The pre-structure report `.moru/performance/native-runtime-status-final.json`
  remains preserved with SHA-256
  `c20ecfb35f8ac06a1ed9452649e872ff5d497658c753c1b40f9d55065661fcf9`.
- Initial six-case report: `.moru/performance/native-runtime-status-comparison.json`,
  SHA-256 `b9fcdd15688749c2574238065c48dc31b638fb20761dd088ec3c4f601ebbe921`.
- Initial numeric control: `.moru/performance/native-runtime-status-controls.json`,
  SHA-256 `037cadfd2d791c392b2f196701d02ce63f157b84ec923bb617773b3c5fc3be8a`.
  Both initial source/binary snapshots and measurement utilities are preserved.

```sh
# Capture the baseline before editing/rebuilding in a new experiment directory.
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_sha.py \
  --capture .moru/performance/native-runtime-status-owned/reference
# Build the default candidate, then compare original per-version entrypoints.
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_runtime_status.py \
  --reference .moru/performance/native-runtime-status-owned/reference \
  --output .moru/performance/native-runtime-status-owned.json \
  --samples 24 --budget-seconds 90
```

## Verification and delivery

Rust metadata/count vectors and existing tests pass 22 cases. Final focused status,
build, observability and API checks pass 23 cases, including native-only basic
and validated output, initialization, every missing lock, source mutation,
unsupported CLI/data, symlinks, contention and snapshot-installer provenance.
Packing and installing the default archive in a fresh temporary root/home passes
36 transported checks. New status checks cover missing-lock rejection without
creation, followed by native basic/validated output with no Python on PATH.

The four-host CI definition includes these status tests; local integration
passed 167 tests in 368.966 seconds before the private-helper regrouping.
A dedicated trends test then passed; final affected checks reran all 23 focused
cases, Rust tests, and transport on the rebuilt binary. Together, 178 distinct
current Python tests pass, with unchanged-owner checks reused from the full suite.
No remote CI run, main integration, release,
global activation or cross-host timing is claimed. Python remains required for
initialization, trends, compatibility paths and other Core functions.
