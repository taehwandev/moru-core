---
keyflow_id: sys_runtime_performance_programme
status: review
type: ai-generated
---

# Runtime performance programme

## Outcome and delivery boundary

Reduce observable latency and resource use at real Moru entrypoints while
preserving their behavior. The goal is useful performance, not a language
rewrite count. Try simpler local import/process/algorithm improvements before
adding infrastructure. No daemon, runtime model call, paid service or Locate
dependency is introduced by this programme.

Baseline is local-main revision `527097ec`. Develop and review on the dedicated
performance branch. On 2026-10-31 the user authorized the accumulated verified
batch's main integration, remote availability and local installation. These
remain separate observable delivery steps, with exact source/artifact readback.
Existing baseline commits and negative timing evidence are preserved.

For subsequent work, batch two or three related, disjoint slices when the
contract is stable. Share provider dispatch, fixtures, focused verification and
one integration review instead of closing a lifecycle for each tiny edit. Keep
the parent as integration owner; do not batch unrelated scope or publication
effects. Each change still needs its own falsifying check and measured limits.

The [inventory](../native-runtime-migration.md) now defines 53 boundaries: 30
primary units and 23 ancillary CLIs, including the new bundle tool. Its baseline
had 52. Inventory coverage is not a commitment to rewrite them all.
Keep infrequent tooling in Python when conversion has no proven
benefit. Shared implementations can serve more than one entrypoint.

## Measurement and acceptance

- Compare identical input, output, error handling and external work. Build and
  setup are excluded. A stub or a changed requirement cannot beat a baseline.
- Measure the actual generated entrypoint in a temporary installation. Report
  fresh-process latency separately from initialized computation and from any
  chained command. Record median, p95, samples, toolchains, cache preparation,
  artifact/source hashes and host limitations.
- Target at least 20% and 5 ms median improvement for a selected frequent
  fresh-process path. Treat regression or uncertain tails as a reason to keep
  investigating. State the exact path that improved; do not extrapolate an
  entire workflow or token savings without corresponding measurements.
- Preserve fallback and operator control. For native changes, confirm execution
  without Python on PATH, not only compilation or an apparently successful response.
- Passing tests establish behavior. Controlled timing establishes bounded
  performance. Source integration, temporary installation, actual global
  activation and live workflow improvement are distinct evidence levels.
- Keep chained and unchained status lines in the workload. Preserve the
  existing renderer chain and its input; never overwrite another tool's slot.

## Existing evidence

These are separate experiments, not a paired causal time series:

| Boundary | Python/reference median | Native median | Evidence/limit |
| --- | ---: | ---: | --- |
| Stage-one direct checkout entrypoint | 48.0504 ms | 8.9694 ms | Prepared bytecode, 30 fresh samples, same host |
| Stage-two generated launcher lookup | 67.0261 ms | 9.9810 ms | Actual temporary-home entrypoint, 30 samples |
| Stage-two synthetic legacy dispatch | 38.1214 ms | 41.0105 ms | Auto bridge adds about 2.889 ms; not an improvement |

The first two units are native lookup and compatible ingress, not a completed
Core migration. At this baseline, 28 legacy processors still use Python. Previously built
artifacts and temporary-home checks do not prove the installed global runtime
has switched. No whole-agent speedup, call-frequency total or token saving is
established by these measurements. See the [stage-two evidence](../../native/checkout-identity/LAUNCHER.md).

## Statusline increment

Profile the shared Claude/AGY status line, which the existing source describes
as a repeated redraw callback. It renders a model label, session path and
remaining quota from an already-supplied payload, plus an optional chained
renderer. This avoids permission-policy and lifecycle-state migration first.

Measure both no-chain rendering and a controlled local chain. Do not execute
the user's private configured chain during benchmarking. Read only wiring
metadata when selecting representative workloads; retain no command text or
account data in this document. Preserve Python-compatible rounding, window
ordering, color and path shortening. Unusual Python-specific input forms may
use an explicitly tested compatibility path rather than silently changing text.

Claude owns a bounded implementation slice. AGY challenges the measurement
and conformance contract when existing access permits. The lead owns contract,
integration, benchmarks, failure reproduction and final verification. Provider
opinions are hypotheses until tested; unavailable review is reported as such.
External briefs contain generic interfaces, not repository source or private
configuration. Raw worker streams, fixtures and samples stay in ignored state.

The branch result now covers both statusline entrypoints through one native
renderer, leaving 26 primary processors in Python. Across the 52-unit inventory,
four primary boundaries have native work (including the partial launcher),
not four fully migrated subsystems. The [specification](spec.md) records the
measured rendering gain, compatibility regression, tests and reproduction;
the [decision record](ard.md) explains the alternatives. Actual global
activation remains pending.

## Project discovery increment

The next bounded item optimizes directory enumeration while keeping Python.
Claude owns the helper, AGY challenges semantics and timing, and the lead owns
integration and focused verification. Marker/ranking and traversal policies
stay with their existing owners. See the [discovery scan result](discovery-scan.md)
for the measured file-heavy benefit, retained small/directory-heavy observations
and reproducible frozen-source comparison. This does not add a native unit or
change the 52-candidate inventory.

The [discovery/entry batch](discovery-batch.md) follows with literal name
matching, scan-to-candidate metadata reuse and one registry snapshot per entry.
Claude and AGY own separate helpers; the lead owns adapters and combined
verification. Component timings do not substitute for real entrypoint results
or prove additive gains. Small-workload costs remain visible.

The [follow-up repair](discovery-repair.md) reuses each producer's path and each
entry cwd observation once, preserves the generic raw-input API, and rejects
an existence shortcut that hides later errors. A single bounded three-way
CPU/wall run checks earlier controls; no repeated loop is used to seek a pass.

## Status and next-action startup increment

The [startup result](startup-paths.md) expands coverage into inventory units 8
and 15. Defer trend/validation libraries and active-run contracts until needed;
retain Python, existing gate decisions and worker reservation checks. Claude
contributes an import tripwire, AGY a strict volatile-field comparator, and the
lead integrates runtime changes, fixtures, tests and one bounded CPU/wall run.

Eight inventory boundaries now have measured changes (8/52, or 8/30 primary).
Four involve native code, including the partial launcher, and four optimize
Python. This measures touched scope, not total effort or accepted migrations.
No-run next and basic status improve about 14% and 9% in this run, below the
frequent-path 20% target; active next has no measured gain. Keep these limits
visible and leave main/global adoption pending.

## Reproduction and decision records

The [mailbox result](mailbox-paths.md) adds ordinary mailbox imports, optional
task-binding imports and per-prompt repository identity reuse. Four Git queries
become one per delivery, freshly queried next prompt. One import-only screening
and one subsequent three-way comparison retain their separate observations;
quiet delivery improves 26.9% median in the latter, while status/receive and
ack controls provide no material gain. Coverage is now 10/53 boundaries, with
four native and six Python improvements, not a migration-completion percentage.

The [portable installation guide](../native-runtime-install.md) addresses the
missing distribution path. Build two binaries on each supported host, transport
a bounded host/source/hash-checked archive, install without Rust/Cargo, then
refresh the existing runtime connections. Python and Git remain required for
the rest of Core. Other-host CI and this-PC activation are checked separately.

Each result records baseline, changed owner, method, passed/failing conditions,
measured delta, remaining cost and adoption state. Keep before/after samples
separate and preserve counterexamples. Reject or defer a port that fails
semantic parity or measured usefulness; correctness can be repaired without
declaring a performance win. This file is the programme contract; per-unit
contracts and sample artifacts retain the technical evidence.
