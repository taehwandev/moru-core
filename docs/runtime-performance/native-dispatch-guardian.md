---
keyflow_id: runtime_perf_native_dispatch_guardian
status: review
type: ai-generated
---

# Native admitted worker guardian

The existing dispatch launcher can select a source-bound Rust guardian before
spawning its worker. Inventory units30 and62 gain partial native execution;
the parent scheduler, admission lock, provider selection and result policy stay
with their existing owners. No Python source is retired.

## Selection and compatibility

`workflow_dispatch_process.run_worker` still checks task ownership, prepares its
bounded request, acquires the execution lock and persists an admitted receipt.
Its existing pre-start callback runs at the same point. An eligible exact
`artifact_plan` selects the candidate binary without running a capability probe.
An old, changed or unavailable artifact retains Python before spawn. A selected
native error is returned without replay, including nonquiet failures.

The supported profile has an absolute guardian carrier, builtin string argv/env
and a canonical admitted receipt with UTF-8 IDs and a positive int64 attempt.
The filesystem encoding and inherited locale/CF bootstrap profile are checked.
Loaded startup customizers and executable/unknown Python startup overrides
retain Python even when an override matches the initial snapshot. Changed HOME
requires explicit user-site suppression. Forced Python, custom/raw/surrogate
inputs and unsupported metadata also retain the original path before spawn.

This matters beyond dictionary values: a Python gate can add locale/CF entries
or run startup code again. An actual original-source environment mismatch and
a fresh-interpreter startup counter reproduced both cases. The adapter does
not synthesize those effects in Rust. Both real native negative controls fail
the reference-environment observer when the profile guard is removed.

## Receipt and lifetime contract

The private `--dispatch-guardian` entry receives the existing2MiB newline request
and self-spawns `--dispatch-exec-gate` as a fresh session/group. Guardian stdin is
the parent lifeline; the gate waits on its separate pipe. The running receipt
is written atomically and fsynced before that pipe releases the command.
An initial EOF never executes work. A running-write failure cleans up the gated
child and keeps the admitted receipt uncertain. A final-write failure keeps the
running receipt uncertain; neither failure admits a replay.

The guardian retains the inherited execution lock. The gate/worker close other
inherited descriptors, including that lock, while Rust's newly created exec-error
pipe remains usable. The gate preserves its PID when it execs the selected
command, gives it `/dev/null` stdin, and preserves ordered environment values,
cwd, stdout and stderr. There is no shell fallback after a failed exec.

Parent EOF/cancellation stops the owned child group with TERM, a bounded wait
and KILL. Group cleanup also terminates surviving descendants after the leader
exits, then reaps the owned child. No stored PID grants signaling authority.
Receipts preserve the existing field allowlist, insertion order, ASCII JSON
spacing/escaping, mode0600, atomic replacement and file/directory fsyncs.
Successful completion, nonzero exit and signal exit retain their original codes;
interruption records130 and selected guardian failure stays uncertain125.

## Verification and remaining work

The original guardian and receipt source are byte-checked against immutable
`7b6b230ed8ea49594d3117a1e12e7c63efa243b6` before reference execution in their
real dependency layout. Final local verification passes63 Python cases,
including actual spooler-to-result-packet native selection, success/failure,
receipt-write failures, ordered/full environment parity, same-PID exec, FD/lock
ownership, cancellation, dispatcher SIGKILL and TERM-resistant descendants.
The explicit fixture-session runner removes executable startup overrides after
loading repository imports; separate fresh-supervisor cases prove compatibility
for those overrides rather than silently accepting them.

The independent worker's10 focused Rust cases cover the identical eight frozen
source/test hashes. An inherited-FD fixture race was corrected inside its own
child before the passing rerun; the production close contract was retained.
Seven relocated empty-PATH debug checks cover receipt bytes, environment order,
nonzero/missing exec, EOF, PID preservation and unsoftened protocol failures.
All615 runtime inputs match the debug fixture; four actual runtime/config hashes
remain unchanged. No timing, CPU, RSS, cost or Linux result is inferred.

Units30/62 remain partial. Public dispatch CLI/preparation, scheduler/admission/
result orchestration, raw/direct legacy entry behavior and unsupported bootstrap/
receipt profiles remain owned work. Two-host release/consumer acceptance and
actual installation are pending. This batch performs no provider turn, real
worker task, release/profile build, archive, hosted dispatch, push or activation.
