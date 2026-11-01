---
keyflow_id: sys_runtime_native_literal_paths
status: review
type: ai-generated
---

# Literal file paths and callback validation cost

## Contract

The existing Claude/Codex file-query boundaries now accept whole single- or
double-quoted literal operands and Unicode alphanumeric paths. Spaces are
accepted inside quoted paths. The admitted commands remain `rg --files`,
`rg -n WORD`, `cat [-n]` and `head [-n COUNT]`; no additional executable or
option is admitted. This extends the same two partial boundaries, leaving
inventory coverage at 14/53, including nine boundaries involving Rust.

`pretool_files.rs` owns one parser used by command admission, payload-cwd
eligibility and Codex transcript-workdir checks. It accepts at most 20 words
and 16 KiB of command text. Quotes must enclose a complete word; the executable
and option markers cannot be quoted. Escapes, quote concatenation, expansion,
shell operators, control characters in paths, parent components and unresolved
operands select the original Python owner. Git's quoted options still select
Python. The native classifier executes no query.

The environment/source guard, local executable-shadow checks, symlink/error
checks, transcript bounds and raw-request replay remain in force. Python still
owns uncertain inputs and all policy/state changes. There is no cache, daemon,
telemetry or added dependency. No real user command, file contents or transcript
is collected by the developer measurements.

## Separating validation from callback startup

The opt-in `callback_guard_profile` Cargo example compiles the actual unchanged
`pretool_guard.rs` and statusline implementation. It performs one guard check,
reports the interval around `CallbackGuard::root`, and exits. It is not a
runtime handler and cannot bypass admission. The regular bundle excludes it.
`tests/profile_native_guard.py` compares fresh probe processes with actual
generated callbacks in a temporary installation, using balanced serial order,
24 samples per mode, a warm filesystem and a 90-second measurement budget.

The guard checks 332 Python source files and seven directory shapes, plus
environment and path eligibility. Its internal duration is not a hash-only
measurement. Comparing this interval with a separately compiled full callback
shows its scale; subtracting the medians does not isolate shell, loader or IO
cost. No cache is introduced from this observation: a future optimization must
still detect changed bytes, new lazy modules, opaque shadows and directory
changes. Size/mtime-only reuse would not establish that contract.

The final probe measures **11.036 ms median / 11.547 ms p95 inside the
guard**, compared with **19.985 ms median / 20.990 ms p95** for the complete
generated plain-file callback. The probe process including startup is
16.508 ms median, 14.447 ms CPU and 2.11 MiB peak RSS; the full callback is
16.918 ms CPU and 2.31 MiB peak RSS. This identifies a substantial validation
cost without establishing how much could safely be removed.

The 1.70-second final run, after formatting the probe driver, is retained in
`.moru/performance/native-guard-profile-final.json`, SHA-256
`5c18daad1ba56576ef85e24e7e57ac25a61b87b3bbc3673065e8a7b85bcce7c8`.
Its source and utility hashes match current files. The developer probe hash is
`95cff0c22cc803e2c4f905b9ed2aab44e90ae2f8ab3d1ad6eb9de76aca6b51f5`.
The initial pre-extension probe is retained separately in
`.moru/performance/native-guard-profile.json` (10.953 ms guard median);
these are separate snapshots, not a claimed guard speedup.

## Callback results

The generated entrypoint was measured on macOS 27.0.1 arm64 with Python 3.9.6
and Rust 1.94.1. Each row uses 24 balanced Python/auto sample pairs after
warmup, identical synthetic inputs and prepared bytecode. Build/setup is
excluded. The host was not reserved; the tail variance below is retained.

| Case | Wall median, Python → Rust (ms) | Wall p95 (ms) | CPU median (ms) | Peak RSS median (MiB) |
| --- | ---: | ---: | ---: | ---: |
| Claude quoted Korean `cat` | 79.343 → 22.151 | 142.732 → 56.052 | 67.404 → 18.298 | 21.26 → 2.33 |
| Codex quoted search with transcript | 82.690 → 21.623 | 98.328 → 40.730 | 66.459 → 18.341 | 21.48 → 2.34 |
| Claude quoted `head` | 74.597 → 20.852 | 98.063 → 34.114 | 64.182 → 17.922 | 21.30 → 2.33 |
| Codex existing plain-query control | 66.620 → 20.293 | 78.136 → 29.765 | 59.574 → 17.370 | 21.50 → 2.31 |
| Quoted Git option, compatibility control | 65.910 → 68.619 | 79.293 → 79.967 | 58.283 → 60.966 | Not compared |

The newly supported paths improve median wall time by 72–74%, meeting the
programme's 20%/5 ms target. The fallback control retains **2.71 ms additional
wall time and 2.68 ms additional CPU time**. It is not accelerated. These
figures measure callback classification, not the execution of `cat`, `rg` or
`head`. The earlier ASCII experiment is a separate host-time snapshot, not a
paired old-native/new-native comparison.

The 15.49-second run is retained in ignored
`.moru/performance/native-literal-paths.json`, SHA-256
`1e2d8407aadfa0d2c45e6083de220876a0aafcac7bd55e58aa6a965c77d10996`.
Its 365 source inputs match the built runtime. The measured native binary is
846,992 bytes, SHA-256
`c0d7cdd2853c750ae461a0573062cbd5e3c689c84ec82eb71378fcafc0f94504`.

## Verification and delivery boundary

The pre-change binary failed all 26 new supported-form/runtime no-Python
subcases. The implementation passes those comparisons against exact Python
exit/stdout/stderr, plus 44 uncertain-quoting/runtime cases requiring Python.
Tests retain Unicode control characters, option quoting, expansion, mixed
quotes, shell operators, missing paths, symlink errors, executable shadows,
environment overrides and different Codex transcript workdirs. Legacy tests
that required all quoted paths to fall back were updated to the new contract;
their unsafe controls were preserved.

Across the affected suites, 78 distinct Python tests and 10 Rust tests pass,
including the corrected legacy expectations. The first Python run had one
obsolete expectation; its corrected selector passed. One attempted launcher
module name was invalid; the actual `test_native_stable_launcher` suite then
passed all 20 tests. These collection/expectation corrections are not runtime
policy repairs. The transported bundle additionally passes **23 checks**,
including both runtime aliases with quoted Korean paths and no Python on PATH.
Only the local macOS arm64 bundle was exercised in this increment; the
existing four-host CI smoke will run on subsequent authorized publication.
No new public release or global runtime activation is claimed here.

## Reproduction

Build the normal local runtime with `scripts/build_native_runtime.py`, then:

```sh
cargo build --offline --locked --release --example callback_guard_profile \
  --manifest-path native/checkout-identity/Cargo.toml \
  --target-dir .moru/native/guard-target
PYTHONPATH=scripts:tests python3 -B tests/profile_native_guard.py \
  --probe .moru/native/guard-target/release/examples/callback_guard_profile \
  --output .moru/performance/native-guard-profile.json
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py \
  --workloads literal-files --samples 24 --budget-seconds 90 \
  --output .moru/performance/native-literal-paths.json
```

These CPU/RSS probes require macOS BSD `time`; sandbox restrictions can prevent
its kernel queries. Setup/build time is excluded. Timings do not establish live
call frequency, whole-agent speed, token savings or another host's performance.
Source verification, transported temporary installation, public release and
actual global activation remain separate acceptance boundaries.
