---
keyflow_id: sys_runtime_full_native_migration
status: review
type: ai-generated
---

# Full native migration Goal

## Scope and source of progress

On 2026-11-06 the user explicitly requested a Goal covering all remaining
migration work. The [execution inventory](../native-runtime-migration.md)
currently contains 56 units: 31 primary entry boundaries and 25 ancillary CLIs.
The [machine-readable ledger](migration-ledger.json) accounts for every unit
and every Python source under the owned runtime/build roots. Its initial
snapshot contains 345 owned Python files and one external dependency file.
Entry units and supporting files overlap; these are not additive task counts.

Earlier implementation coverage remains useful evidence. It does not establish
that an entire unit has stopped depending on Python: the 17 boundaries with
native work include substantial partial migrations. Existing accepted native
engines are revalidated or reuse matching evidence; they are not rewritten to
create new progress. The Goal stays active until its complete contract is met.

The ledger uses stable source-owner IDs; numeric inventory positions may move
when the product gains a new entry. Newly discovered public entries and owned
supporting modules must be reconciled, never silently omitted. A new source
file is not an independent migration commitment when it belongs to an existing
engine, but its remaining Python responsibility still needs an owner.

## Acceptance for a completed unit

`native_local_verified` records a complete engine accepted on the named local
host while other-host acceptance remains pending. `native_verified` requires
all four supported bundle hosts plus the following recorded evidence:

1. Rust owns the full supported public behavior, including arguments, formats,
   failures, state/lock behavior and negative authority decisions. A Rust
   dispatcher that still calls Python for ordinary execution is partial work.
2. Actual native entrypoints pass observing behavior and adversarial checks
   against the existing contract. Matching earlier evidence may be reused;
   changed inputs require only their affected verification.
3. A transported consumer runs the supported path without Python or a compiler
   on PATH. Explicit developer rollback/reference modes may remain.
4. The installed runtime is bound to the reviewed sources and artifacts.
   Platform-specific acceptance is named; one host does not attest other hosts.
5. Supporting Python is either still openly unmigrated, retired with its caller
   proof, or explicitly reference-only with a native owner and verification.
   Completing an entry does not erase another entry's remaining dependencies.

The entire Goal additionally requires no pending owned Python responsibility
and no unverified public unit. External/vendor code has a separate ownership,
license and replacement boundary. It cannot become an implicit exclusion or a
completed port because a Rust wrapper invokes it. Any final exclusion requires
an explicit user decision; until then the target remains open.

## Delivery waves

| Wave | Units | Work |
| --- | ---: | --- |
| Frequent callbacks | 11 | Pretool, prompt/mailbox, Stop, continuation, renderer and ingress paths |
| State and observability | 9 | Mailboxes, cards, memory, snapshots and recovery |
| Lifecycle and dispatch | 11 | Admission, hooks, finish, loops, routing, discovery and setup |
| Owned tooling | 24 | Remaining direct CLIs and their owned supporting code |
| External boundary | 1 | Wikimap ownership and native replacement/adapter decision |

These waves partition the current inventory and order investigation; they do
not waive lower-frequency targets. Related stable responsibilities may be
batched. Each implementation remains within the repository's review limits;
shared engines can satisfy several entry boundaries with their own acceptance.
No new paid model/service use, device effect, deployment or destructive action
is implied by the migration Goal.

Keep temporary compatibility paths until their native replacements meet the
contract. Preserve authority, user data, configuration and provider neutrality.
Keep developer tests in their useful reference language; migrating an execution
tool does not require rewriting every test fixture.

## Per-batch work

Use the durable performance checkout and existing performance branch. Keep the
main checkout as acceptance boundary and preserve unrelated sessions' work.
Maintain one bounded implementation action per cohesive batch; reuse unchanged
guidance, measurements and checks. Record the complete Goal here and in the
ledger while each action closes only its declared batch.

Implement, run affected observing checks, verify a source-matching portable
bundle, review/finish the exact unit, then perform the authorized commit, main
integration, push and actual local activation. Refresh publication attestation
only when actual rules/input freshness requires it. Keep CI and other-host
results explicit. Do not report the Goal complete after one batch.

Existing comparisons establish the Rust direction. Do not repeat wall/CPU/RSS
or cost calculations for each file or syntax extension. Measure again only for
a materially different architecture, a concrete regression or a user request.

The first Goal batch extends the existing pretool boundaries with bounded `rg`
context options and stdin-only search filters. Their specific contract remains
in [native query/registry](native-query-registry.md); neither adds an inventory
unit or completes the full pretool policy migration.

The baseline Linux CI also exposed two fixture assumptions. Unusual environment
names are now checked directly in both engines and separately through the real
launcher, whose host shell may filter those names. The SQLite contention test
takes its byte snapshot before the exclusive transaction, preserving the lock
that the test is meant to observe; closing another descriptor for the same file
can cancel POSIX locks. See the [SQLite locking explanation](https://www.sqlite.org/howtocorrupt.html#_posix_advisory_locks_canceled_by_a_separate_thread_doing_close_).
These repairs retain the original parity and fallback assertions. Linux
acceptance stays pending until the corrected CI actually passes.

The Intel macOS job in run `42157432003` was cancelled by its 15-minute
execution limit, as confirmed by job `127694808548`'s timeout annotation.
Its ceiling is now 30 minutes; other hosts retain 15 minutes. The runner,
test selectors, assertions and consumer packaging are unchanged. This removes
an observed acceptance interruption and does not establish an Intel pass.

Units 36–37 now have source-bound launcher ingress and native local manifest
engines. Android compares snapshot paths and bounded Git identities; React/RN
checks provenance, ownership and optional local source hashes. Existing direct
Python CLIs remain available. Their ledger status stays `partial_native`:
exceptional input compatibility and direct callers still need migration.
React/RN remote checks decline before any effects, preserving the reference
implementation's decoding, timeout and output behavior without replaying a
remote request. Process tests use fake Git only; this batch fetches no sources
and performs no real remote checks. Unsupported native inputs remain explicit
remaining work, not completed migrations.

Local acceptance for this increment: 43 focused Python/reference/installed-entry
tests, 45 Rust tests with both standard and software SHA implementations, and
95 transported-bundle checks passed. The process tests include Python-free
local checks, ordered validation failures, preserved compatibility refusals and
fake-Git proof that remote fallback executes once. Platform CI and actual local
activation are separate delivery evidence; these counts do not attest them.

The following increment moves React/RN help and ordinary argument errors into
Rust, including option abbreviations, repeated values, ambiguity before help,
and terminal-newline negative-number classification. Maintained skill guidance
now invokes both installed aliases; historical audit reports remain unchanged.
The legacy Python entrypoints remain compatibility/reference paths, not extra
completed units. Native help uses the artifact builder's argparse section
title, emitted during existing static-contract generation: a consumer running
a different Python generation may see a different title on explicit rollback.
No runtime Python process is required for native help. Exotic/non-UTF-8 CLI
inputs and engine exceptions remain in the ledger along with remote execution.
