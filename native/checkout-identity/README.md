---
keyflow_id: sys_native_checkout_identity
status: review
type: ai-generated
---

# Checkout identity runtime: migration stage one

The first Rust unit reads checkout Git common-directory and branch metadata.
It promotes the verified experiment into a reusable library and direct process
entrypoint. It does not replace policy decisions or install global hooks.

Owner: checkout metadata lookup. Allowed imports: standard filesystem, JSON and
process libraries plus pinned serde_json. Forbidden: networking, credentials,
task/ledger writes and policy mutation. Callers: the command-line entrypoint;
tests compare real processes with scripts/claude_worktree_gate.py.

## Frozen interface

The executable `moru-checkout-identity` accepts UTF-8 NDJSON. Each request is
`{"schema_version":1,"root":"/absolute/path"}` with exactly these two keys.
The version is integer 1, not boolean or floating point. Root is nonempty and
contains no NUL. The input limit is 1,048,576 bytes including newline; drain
oversized lines before accepting another request. Empty EOF emits nothing.

Success is `{"schema_version":1,"ok":true,"common_dir":PATH_OR_NULL,"branch":STRING}`.
Compute common directory and branch independently, in that order, with no
result cache. Values equal the existing Python production functions on a
stable filesystem, including disk-first metadata and read-only Git fallback
with a two-second timeout per call. Missing Git yields the existing fallback
result. Use argv, never shell evaluation.

Errors have schema version 1, `ok:false` and `error` equal to `invalid_json`,
`invalid_request`, `input_too_large` or `io_error`. A request error does not
terminate the stream. Object order and Unicode escaping are not significant.
This is UTF-8 JSON, not Python NaN/Infinity or UTF-16/32 autodetection. The Rust
parser retains its nesting limit. POSIX behavior is the initial target.

## Entrypoint and build

Run `python3 scripts/build_native_runtime.py` with an existing Rust toolchain
and cached crates. The build is locked/offline and atomically publishes the
local executable to ignored `.moru/native/bin/moru-checkout-identity`.

The common launcher now also has native plain-query pretool callbacks. Cargo's
build script uses Python to generate a static runtime-source snapshot; this is
a developer/CI build requirement. Supported prebuilt native callbacks do not
start Python. Source receipts include the build generator and runtime inputs;
see the [pretool contract and measurements](../../docs/runtime-performance/native-pretool.md).

Call `scripts/moru-checkout-identity` with requests on stdin. It directly execs
the local native binary when present; Python initialization is absent on that
path. When the binary is missing it execs `scripts/checkout_identity.py`, which
calls the existing Python functions. Set `MORU_CHECKOUT_IDENTITY_BACKEND` to
`python` for rollback, `rust` to require native execution, or `auto` (default).
An executed native failure propagates; consumed input is never silently replayed.
No toolchain is needed to run a compiled artifact on its compatible platform.

## Staged acceptance

The [stage-two launcher bridge](LAUNCHER.md) connects this handler to the stable
entrypoint without Python initialization. The [migration inventory](../../docs/native-runtime-migration.md)
tracks the complete candidate entry-owner scope and retains Python policy paths.

1. This unit: reusable Rust implementation, direct invocation, explicit Python
   rollback, offline build, real-process parity and no-Python-PATH smoke check.
2. Next: route a bounded existing execution path through native startup; verify
   its exact output/exit behavior and end-to-end latency before widening use.
3. Later: move one policy/processing owner at a time, retaining its safety tests.

Installed hooks continue using Python in stage one. A Python process that
launches this binary would retain its own startup cost; no such bridge is added.
Whole-Core latency, token savings, other operating systems and release-package
acceptance remain unmeasured. Claude supplied the protocol, library facade and
thin executable from a generic interface brief without repository source.
The parent promoted the verified metadata implementation, repaired the bounded
Git pipe wait, and owns integration and verification. No publication is part
of this stage.

## Verified stage-one result

On macOS arm64 with Rust 1.94.1 and Python 3.9.6, the optimized executable built
offline and passed 29 checks: 13 process/adapter tests, four original metadata
tests, four build/rollback tests and eight Rust tests. These include real Git
layouts, absent Git/toolchains/Python on PATH, live HEAD mutation, malformed
input and stream recovery, explicit rollback, failure exit propagation and
input/output errors. A fake Git process exiting while its descendant held a
pipe open reproduced an unbounded join; the native wait now uses the remaining
per-call deadline and its regression passes. This bounds the caller's wait;
it does not promise cancellation of arbitrary Git descendants.

Fresh-process median milliseconds through the actual shell entrypoint:

| Layout | Rust | Python rollback |
| --- | ---: | ---: |
| Plain checkout | 8.9694 | 48.0504 |
| Linked worktree | 8.7710 | 48.4197 |
| Detached HEAD | 20.7756 | 60.6801 |

Thirty samples per backend/layout, randomized sequential order, warm filesystem
and prepared Python bytecode; setup/build excluded. These times include the
shell entrypoint, process execution and lookup; parent decoding is outside the
timing window. Host exclusivity
was not guaranteed, and this is a separate run from the earlier experiment.
Raw samples and p95 values are in ignored `.moru/native/stage-one-benchmark.json`.
The stripped executable is 494,000 bytes on this host.

Reproduce from this checkout:

```sh
python3 scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_checkout_identity_runtime test_build_native_runtime test_claude_worktree_gate_git_dir
CARGO_TARGET_DIR="$PWD/.moru/native/cargo-target" cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
python3 -B tests/benchmarks/checkout_identity_entrypoint.py
```
