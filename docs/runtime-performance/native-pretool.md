---
keyflow_id: sys_runtime_native_pretool_result
status: review
type: ai-generated
---

# Native plain-query pretool callbacks

The initial experiment below is retained for its exact artifact. The
[cache compatibility correction](native-pretool-cache-compat.md) records the
subsequent installed-source failure, regression repair and matching new timing.

## Decision and scope

Serve repeated plain queries for both Claude and Codex pretool callbacks in
the existing Rust launcher. Inventory units 20 and 24 are **partially converted**:
complex commands, writes and unsupported compatibility conditions retain the
Python gate. This does not remove the whole product's Python dependency.

Registration establishes a frequency proxy: pretool callbacks run for matching
tool uses, prompt delivery per prompt, and Stop at turn end. The existing native
statusline serves redraws. No real session history or invocation counters were
collected; this is not a measured live call-count ranking.

The Codex status-query workload improves median wall time 69.3%, CPU 70.7% and
process maximum RSS 89.4% below. Both aliases serve supported queries with Python
and Git absent from PATH. The callback classifies the command, never executes
it, and silently defers to the provider's native permission flow.

## Contract and ownership

`pretool_query.rs` accepts a finite ASCII grammar: `pwd`; selected `git status`,
`diff`, `rev-parse` and current-branch queries; and optional unquoted absolute
`git -C`. Quotes, shell syntax, assignments, executable-path variants, extra
flags and operands select compatibility. `git diff --stat --output=x` cannot
use the native return.

`pretool_process.rs` handles original JSON and replays received stdin bytes once
for unsupported input. `pretool_guard.rs` verifies the same valid source root,
supported environment, executable/launcher resolution and a build-time snapshot
of all **329 runtime Python sources and seven source directories**. Hashing
streams through a 16 KiB buffer; sorted membership checks detect new sources.
Sourceless bytecode, extension shadows, changed/missing files and unsupported
state/project override paths select Python. No decision is cached across calls.
Known developer cache directories are excluded by one shared build-time list;
unknown directories and cache-named directory symlinks still select compatibility.

A full bounded code snapshot replaces an initially considered eager-import
graph: static imports alone do not account for lazy imports called during
module initialization. The snapshot covers Core code, not `.moru` history,
user repository files, usage databases or a search index. Its cost is included
in the benchmark. Source updates need a matching build for the native path.

`pretool_transcript.rs` checks Codex normalization's failure boundary. Closed
queries defer regardless of a selected valid cwd, but normalization/discovery
errors can emit warnings. It reads at most the runtime-provided 512 KiB tail,
retains nothing, and selects Python for uncertain records, escapes, NUL paths
and unusual line separators. Only synthetic transcripts were used in checks.

Build-time `pretool_contract.py` emits the snapshot without importing policy.
Shared `native_source_inputs.py` owns builder/installer/bundle input enumeration;
receipt validation reads candidate code as data rather than executing it.
One cached `sha2` dependency and locked transitive crates were added. There was
no download, paid call, service or daemon. The existing
`MORU_LAUNCHER_BACKEND=python` rollback remains available.

## Verification and review findings

**303 unique Python tests and nine Rust tests passed** across the focused
suites. Unchanged passing selectors were reused; one command did not run all
checks together. Coverage includes generated entrypoints, Unicode/space cwd,
Codex function/custom-call transcripts, no-Python/Git execution, exact
exit/stdout/stderr parity, malformed inputs, writes, rejected neighbors,
source/root changes, opaque module shadows, source enumeration, statusline,
legacy launcher, build and portable-bundle compatibility.

A separate same-runtime reviewer found a real parity gap: an invalid
`MORU_STATE_HOME` could make Python emit an internal-error warning while native
returned silently. The reproducer failed before guard repair. Repaired tests
require observed baseline parity and proof of Python fallback. The reviewer
also identified sourceless/extension module shadows; directory validation and
an explicit `.pyc` fixture cover that class. This is a second execution
perspective, not independent-model or external-provider evidence.

Early assertions assumed a specific symlink loop or shadow always caused a
warning/failure. Actual Python behavior did not support that assumption in
every fixture. Checks now require exact baseline parity plus fallback proof,
without inventing a diagnostic. A sandbox restriction on `ps` was resolved by
rerunning only the owned-process cleanup selector with process-metadata access;
it passed. No production policy was weakened for a test.

## Controlled measurement

Rust 1.94.1, Python 3.9.6, macOS 27.0.1 arm64. The same generated temporary-home
callback and source run in `auto` and forced `python` modes. Each workload has
24 balanced randomized AB/BA pairs, prepared isolated bytecode, warm filesystem
and an unreserved host. The 90-second budget includes setup; the run took
15.42 s. The driver runs children serially and checks exact silent success.

macOS `/usr/bin/time -l` records per-process maximum RSS bytes. Child-resource
deltas measure CPU; elapsed time includes the identical wrapper overhead.
Partial samples survive failure/budget exhaustion. Final source, utility and
binary hashes all matched the report. There was one completed bounded timing
run, without retrying to select a desired result.

Each cell is Python → Rust/auto, milliseconds:

| Callback | Wall median | Wall p95 | CPU median | CPU p95 |
| --- | ---: | ---: | ---: | ---: |
| Claude status | 102.759 → 30.994 | 158.165 → 63.732 | 84.064 → 24.213 | 106.528 → 33.791 |
| Codex status with transcript | 70.377 → 21.590 | 114.911 → 41.562 | 64.579 → 18.947 | 89.067 → 26.037 |
| Claude cached diff | 67.897 → 22.882 | 100.793 → 32.081 | 62.118 → 20.011 | 78.731 → 23.867 |
| Codex pwd | 65.455 → 21.084 | 70.017 → 24.207 | 60.162 → 18.352 | 64.341 → 21.431 |
| Quoted-query fallback | 66.371 → 69.182 | 74.932 → 81.070 | 61.003 → 63.474 | 66.543 → 72.001 |

Process maximum RSS, median / p95 in MiB (1 MiB = 1,048,576 bytes):

| Native callback | Python | Rust |
| --- | ---: | ---: |
| Claude status | 21.27 / 21.59 | 2.31 / 2.33 |
| Codex status with transcript | 21.66 / 21.80 | 2.30 / 2.34 |
| Claude cached diff | 21.27 / 21.52 | 2.30 / 2.33 |
| Codex pwd | 21.44 / 21.64 | 2.30 / 2.33 |

Fallback adds 2.81 ms median wall (4.2%) and 2.47 ms CPU (4.1%). Its RSS is not
compared: compatibility starts a Python child and process RSS is not a
simultaneous process-tree total. Fast native callbacks have no Python/Git child,
as separately exercised with an empty PATH. No whole-agent or concurrent memory,
token savings, cold-disk, live call frequency or cross-host speed is proven.
Rows are paired workload experiments, not a time series between workloads.

The launcher is 796,704 bytes, SHA-256
`d5f164a1db5a1b9d3bf6dd0d1bd669660c3c441763e76f144196cfd4563686ac`.
Its ignored receipt binds 355 native/build/runtime inputs. Portable packaging
uses the same source contract; no existing release asset or tag is replaced.

## Reproduction and delivery boundaries

```sh
python3 scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_support_native_source_inputs test_native_pretool test_native_statusline test_stable_launcher test_stable_launcher_help test_codex_exec_workdir test_native_stable_launcher test_build_native_runtime test_native_bundle test_claude_pretool_gate
CARGO_TARGET_DIR=.moru/native/cargo-target cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --samples 24 --budget-seconds 90
```

Process cleanup and macOS time need OS metadata access where a sandbox blocks
those read-only queries. Raw data is ignored `.moru/performance/native-pretool.json`;
artifacts/receipts are ignored `.moru/native/`. Source integration, actual local
activation and a future portable release require separate readbacks. Revert
this unit or select Python to restore legacy callbacks. Complex and write
callbacks still require Python during this stage.
