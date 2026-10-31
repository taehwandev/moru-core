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

Baseline is local-main revision `527097ec`. Keep subsequent work and reviewable
commits on the dedicated performance integration branch. Main integration,
remote publication and actual user-global installation are separate later
decisions; this programme does not continue the earlier automatic-main pattern.
Existing baseline commits are preserved.

The [52-unit inventory](../native-runtime-migration.md) defines coverage: 30
primary units and 22 ancillary CLIs. Inventory coverage is not a commitment to
rewrite all 52. Keep infrequent tooling in Python when conversion has no proven
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
- Preserve fallback and operator control. Confirm real native execution without
  Python on PATH, not only compilation or an apparently successful response.
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

## Current bounded experiment

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

## Reproduction and decision records

Each result records baseline, changed owner, method, passed/failing conditions,
measured delta, remaining cost and adoption state. Keep before/after samples
separate and preserve counterexamples. Reject or defer a port that fails
semantic parity or measured usefulness; correctness can be repaired without
declaring a performance win. This file is the programme contract; per-unit
contracts and sample artifacts retain the technical evidence.
