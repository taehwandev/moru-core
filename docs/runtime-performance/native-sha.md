---
keyflow_id: sys_runtime_native_sha
status: review
type: ai-generated
---

# Runtime-detected ARM64 source hashing

## Contract and dependency scope

The pinned RustCrypto `sha2` 0.10.9 source selects its software SHA-256 backend
on ARM64 unless the `asm`/`asm-aarch64` feature is enabled. Its ARM64 backend
checks CPU SHA support at runtime and retains `super::soft::compress` when it
is unavailable. The target-specific dependency enables that existing feature
only for ARM64; no cryptographic implementation, unconditional CPU instruction
flag, skipped digest, metadata cache or extra worker is introduced.

Both macOS/Linux ARM64 Cargo feature graphs contain `asm,asm-aarch64,sha2-asm`
in addition to the existing defaults. Both x86-64 graphs retain only
`default,std`, including the pre-existing x86 CPU detection. These graph checks
are source/configuration evidence, not cross-host execution.

Cargo.lock adds `sha2-asm` 0.6.4 and its developer build dependencies `cc`
1.2.62, `find-msvc-tools` 0.1.9 and `shlex` 1.3.0. Native compilation uses the
existing developer C toolchain. Receiving PCs still install the same native
archive: no Rust compiler, assembler, Python package or additional runtime
service is required by this feature. Git and Python remain required by the
other Core paths as before.

The source guard still checks every byte of all 332 Python sources and all
seven directory shapes on each eligible call. Digest values, environment,
session/state/lock checks, command grammar and Python fallback are unchanged.
Repository-key and guidance hashes use the same SHA-256 values. The change
does not add an inventory unit or migrate an additional policy boundary.

## Verification and comparison protocol

Two Rust tests add standard empty, short, padding-boundary and million-byte
streaming vectors. All 20 Rust tests pass in both default and forced-software
builds (`--features sha2/force-soft`). Forced software exercises the same soft
implementation used by the dispatcher's fallback; an actual ARM CPU without
SHA support was not emulated. The existing four-host CI definition runs both
modes before normal artifact creation. No remote run is claimed by that edit.

`benchmark_native_sha.py --capture` freezes the current source receipt and both
native executables before dependency changes. It adds the required guarded
directory shapes and three source markers, then verifies every captured hash.
The first capture exposed that the existing fixture copier copied only the
launcher; the missing identity executable was supplied and revalidated before
any production edit. Original snapshots are never overwritten.

The paired measurement compares the prior native implementation with the new
native implementation, not Python startup. Both run through actual generated
temporary-home launchers. Source snapshots and home names have equal length;
runtime Python contents and markers are identical. The fixture proves every
selected case with Git-only PATH before timing. Only the known source-root and
entrypoint tokens of `next` JSON are normalized; its exact formatting is checked
first. Other output bytes must match. No real mailbox, project state or
transcript is used.

Five cases cover Claude pretool, Codex pretool with a synthetic transcript,
quiet mailbox, quiet Stop and inactive next advice. CPU/wall are serial child
measurements; RSS is BSD `time`'s command maximum, not a concurrent tree sum.
Build/setup and the Python driver are excluded. Sample order is balanced and
seeded, with warm filesystem and no reserved host. Full source, marker, utility,
binary and toolchain identities are retained; snapshots are checked again after
measurement. Live frequency, token savings, whole-agent gains and cross-host
timings are not inferred.

```sh
# Capture before editing dependencies or rebuilding the candidate.
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_sha.py \
  --capture .moru/performance/native-sha/reference
# After building the current default candidate:
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_sha.py \
  --reference .moru/performance/native-sha/reference \
  --output .moru/performance/native-sha-comparison.json --samples 24 --budget-seconds 90
```

## Local result: 2026-11-01

One completed run on macOS 27.0.1 ARM64, Rust 1.94.1, contains 24 samples per
variant per case (240 timed callbacks). The source baseline is commit
`41a8189fff8b3b6276267aba5a4f7bdcf72ab808`. This comparison is native versus
native with identical runtime Python contents, rather than another comparison
against interpreter startup. Values below come from the completed JSON report.

| Generated callback | Wall median, before → after (ms) | Reduction | CPU median, before → after (ms) | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Claude file pretool | 17.243 → 12.436 | 27.9% | 15.107 → 10.188 | 32.6% |
| Codex transcript pretool | 17.894 → 13.055 | 27.0% | 15.539 → 10.637 | 31.5% |
| Quiet mailbox | 28.415 → 23.371 | 17.8% | 22.861 → 17.703 | 22.6% |
| Quiet Stop | 27.071 → 21.987 | 18.8% | 21.549 → 16.287 | 24.4% |
| Inactive next JSON | 27.386 → 22.737 | 17.0% | 22.375 → 17.540 | 21.6% |

Wall medians fall by 4.65–5.08 ms. This is a useful bounded improvement for
frequent callbacks; these samples do not establish statistical significance or
whole-session savings. CPU medians improve in all five selected cases. RSS is
effectively unchanged: pretool medians are 2,384–2,416 KiB, quiet mailbox/Stop
are 4,112 KiB, and next is 4,832 KiB. Both launcher executables are 880,496 bytes.

Tail results are mixed and are not filtered or rerun for a better result:

| Callback | Wall p95, before → after (ms) |
| --- | ---: |
| Claude file pretool | 18.931 → 14.076 |
| Codex transcript pretool | 19.153 → 15.522 |
| Quiet mailbox | 35.653 → 51.033 |
| Quiet Stop | 28.128 → 23.541 |
| Inactive next JSON | 30.879 → 26.134 |

In particular, the mailbox p95 regresses in this unreserved-host run. A median
gain must not be presented as a tail-latency guarantee. Broader workload and
cross-host measurements remain open.

Two earlier setup attempts failed before collecting any timing samples: the
driver resolved the reference root but left the candidate root relative. Its
`MORU_HOME` then resolved under the synthetic project's cwd, so the unchanged
same-root guard rejected it. Both roots now derive from the resolved reference.
The same relative-path CLI shown above subsequently passed all ten no-Python
preflight calls and completed. The failed reports are retained separately;
no runtime guard or fallback rule was loosened to obtain the result.

Local ignored evidence:

- `.moru/performance/native-sha-comparison.json`, SHA-256
  `c96539e96ecccf3ef98c04154130b9ac888337eb7c5fddaad510296e73c515c0`.
- Before launcher SHA-256:
  `4f65423614d9c6f85d215f7aa0b6e5b5a95cf2afc9d178540349510302b78df5`.
- After launcher SHA-256:
  `aa4475c454e80a2a6522b1c7df0bcfead01b5354b47cac2344d43cf697d3be9b`.
- Frozen source and artifact receipts under
  `.moru/performance/native-sha/{reference,candidate}`; both include all 367
  build inputs and both executables. Reports retain every sample and utility hash.

The existing integration suite resolved all 120 distinct Python tests as
passing. Its first sandboxed run passed 119; the process-group timeout test
could not inspect `/bin/ps` there and passed when rerun with process inspection
available. Both Rust backend modes passed all 20 tests. The default release
artifact was rebuilt after the forced-software tests. Packing and installing
that artifact in a fresh temporary root/home passed all 27 transported checks,
including eligible callbacks with Python absent from PATH.

This is a local performance-branch commit. It does not merge main, publish a
tag or release, activate the user's installed launcher, or prove execution on
the other three CI hosts. No further Python policy path is migrated by this
increment.
