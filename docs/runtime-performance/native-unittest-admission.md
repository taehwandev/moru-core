---
keyflow_id: sys_native_unittest_admission
status: review
type: ai-generated
---

# Native unittest admission bootstrap

This bounded inventory34 slice moves only the guarded pre-interpreter admission
latch into Rust. Python still owns unittest discovery, imports, result semantics
and the separate JSON receipt. The parent still owns admission, the deadline,
process-session creation, group cleanup and evidence. Inventory34 remains open.

Before spawning, the adapter validates the candidate with `artifact_plan`:
current runtime source membership and hashes must match the build receipt, and
the executable bytes must match its recorded digest. The adapter invokes that
candidate directly with private `--unittest-admission`; it never probes an old
binary, invokes an unverified installed launcher or sends an unknown flag to
its compatibility dispatcher. The candidate must be rebuilt after runtime
source changes. No build or install happens during selection.

`MORU_LAUNCHER_BACKEND=python`, missing/stale/invalid candidates, unsupported
backends and missing, non-executable, non-file or relative executable selections
retain the existing trusted `-I -S` Python bootstrap before any child starts.
Relative executable semantics
remain with Python's `os.execv`; the native path does not search PATH.

The native child accepts only the release byte `0x01`; EOF, a different byte or
read error returns125 without running the selected interpreter. On admission it
removes `MORU_UNITTEST_ADMISSION` and uses Unix exec with the exact selected
executable and arguments. PID, process group, cwd, environment and inherited
descriptors survive exec. An exec failure returns127; unsupported direct native
arguments return2. These internal-mode errors never soften or relaunch tests.
An interpreter removed or changed after selection is a race: once the native
child starts, it fails closed with the native exec error rather than restarting
Python and risking repeated project startup. Stable missing/non-executable inputs
retain the original Python exit1 and diagnostic by selecting compatibility first;
invalid argv retains its original pre-spawn exception.

The caller records the newly created process-group leader before releasing the
byte. Denial and time spent in the admission callback consume the same deadline
and preserve the existing kill-and-reap behavior. No selected-interpreter `.pth`,
`sitecustomize`, PYTHONPATH or project test code may run before that release.

Verification lives beside the native owner in `unittest_admission_tests.rs` and
in `tests/test_native_unittest_admission.py`, including actual-process selection,
startup, PID/group/descriptor/environment observations and negative controls.
The existing verification-hook suite remains the receipt/discovery regression
contract. Local debug verification passed two Rust latch tests, 14 admission
process tests and all 26 existing verification-hook tests with a valid candidate.
Negative controls expose premature startup, spawn-and-wait PID substitution,
forced Python selection and the missing-interpreter exit1/127 mismatch.
No measured speedup, release bundle, installed-runtime, Linux or whole-unit
completion claim follows from these local source checks.

The parent matched all seven handed-off file hashes and all 602 runtime source
bindings before reusing the exact debug artifact in its integration worktree.
Its independent holdout runs a real unittest while making a separate trusted
Python bootstrap unavailable: the original path fails that negative control,
the new path passes, and the real Python compatibility run still passes. The
test observes the admitted PID/group, cleared latch variable, retained cwd/env,
stdin EOF and the actual one-test successful receipt.

Five additional relocated checks run with empty PATH using only `/bin/sh`
builtins after release; EOF/wrong byte, missing executable and relative paths
retain visible failure even with hook soft-fail enabled. Eight existing
workdir callbacks also passed on that relocated 602-source fixture, and four
actual runtime/config file hashes stayed unchanged. The existing manual-only,
two-platform CI selector now includes admission and verification-hook suites;
no hosted workflow or bundle generation was run.
