---
keyflow_id: sys_runtime_performance_decisions
status: review
type: ai-generated
---

# Performance decisions

## Dedicated integration branch

Keep this programme on `taehwandev/perf/runtime-performance`, based on
`527097ec`. Preserve earlier main commits. A verified local branch commit is
the delivery boundary; main integration and actual global activation require
a later decision. This makes performance evidence reviewable together with
the implementation before changing the user's installed runtime.

## Select frequent, data-only work first

The two provider statusline entrypoints share one renderer. Moving this pure
formatting work avoids migrating admission, authority, workflow state and
failure-recovery policy. Keep Python as the reference and compatibility path.
The 52-unit inventory remains a candidate set, not a conversion quota.

## Compare a cheaper Python option

Measure Python `-S` as well as the native path at the same generated entrypoint.
Skipping site initialization needs less code, but a statusline optimization
does not justify applying that option to other commands with different import
requirements. Isolated `-I` also changes environment/import semantics and is
not adopted as a transparent replacement. Unprepared startup screening is not
used as evidence for the final decision.

## Reuse the existing optional native artifact

Add formatting to the already-optional native launcher rather than creating a
new service or runtime dependency. Ordered serde_json maps preserve quota
entry precedence. Cached indexmap dependencies and float-roundtrip parsing
support compatibility; builds remain locked and offline. The tradeoff is a
larger binary and a slower compatibility path when both native selection and
Python startup are required. Record both rather than hiding them in a mean.

Do not introduce a daemon, FIFO, shell/jq schema parser or direct execution of
guessed simple chain commands. These add lifetime, installation or shell
semantics costs without evidence that they are necessary. Preserve the exact
configured `/bin/sh -c` contract and execute it once. A private process group
allows a timed-out chain's descendants to be terminated without targeting the
operator's process group.

## Evidence and adoption

The initial branch-only boundary was superseded by the user's 2026-10-31
request for main integration, other-PC availability and local installation.
Ship the reviewed accumulated batch while retaining qualified claims and
Python rollback; no whole-agent or cross-host performance gain is inferred.
Portable packaging validates host and exact native source/binary hashes, and
the distribution build smoke-tests a fresh consumer without a toolchain on PATH.

The lead integrates Claude's pure formatter and AGY's falsification questions.
Provider output is a contribution, not proof that code ran. Parent-owned real
entrypoint tests and randomized measurements decide branch readiness.
The [specification](spec.md) records observed results and costs; the
[programme](prd.md) defines acceptance. Neither proves whole-agent speed,
token reduction, installed activation or compatibility on an untested host.

## Optimize enumeration before porting discovery

For project discovery, first replace file-by-file directory probing and sorting
with the stdlib directory-entry API. This keeps registry, marker, ranking and
traversal policy in Python and avoids another language boundary for the same
measured bottleneck. The [scan result](discovery-scan.md) meets the local target
on file-heavy trees; directory-heavy and small CLI gains are not established.
Do not use this result to justify rewriting the rest of discovery or relaxing
its selection rules.

## Batch related work while preserving the acceptance boundary

The discovery/entry batch shares one output/selection contract across three
reductions. Separate helpers allow disjoint implementation; the existing
adapters remain lead-owned. A single reviewed commit keeps that pipeline change
and its counterexamples together. Isolated component checks and frozen-source
CLI comparisons preserve visibility of each responsibility. Long repetitive
requests retain regex after a measured regression; registry state is scoped to
one entry call, never cached across calls. See the [batch evidence](discovery-batch.md).

## Account for registered evidence before recursive discovery

The general runtime-session resolver first verifies canonical paths for every
registered binding. Only a fully accounted set skips enumeration; unresolved
custom, worker or moved-state claims retain legacy discovery and completeness
checks. Exact session/generation/ownership decisions remain downstream, and
directory readability, symlink and nested-checkout exclusions remain enforced.
No cross-call authorization cache or Rust adapter is added. The
[evidence lookup result](evidence-lookup.md) measures both initialized lookup
and an actual generated next-action entrypoint, including fallback overhead
and compact-state tails rather than claiming universal improvement.
