---
keyflow_id: sys_runtime_full_native_migration
status: review
type: ai-generated
---

# Full native migration Goal

## Scope and source of progress

On 2026-11-06 the user explicitly requested a Goal covering all remaining
migration work. The [execution inventory](../native-runtime-migration.md)
currently contains 64 units: 31 primary entry boundaries and 33 ancillary CLIs.
Exact main-guard checks found owners absent from the 56-row
snapshot; they are appended as 57–64 without changing existing IDs or excluding
their already-owned Python responsibilities.
The [machine-readable ledger](migration-ledger.json) accounts for every unit
and every Python source under the owned runtime/build roots. Its initial
snapshot contains 345 owned Python files and one external dependency file.
Entry units and supporting files overlap; these are not additive task counts.

Earlier implementation coverage remains useful evidence. It does not establish
that an entire unit has stopped depending on Python. The initial 17 boundaries
with native work included substantial partial migrations. Existing accepted native
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
both supported bundle hosts (macOS ARM64 and Linux x86_64) plus the following
recorded evidence. The user's distribution decisions remove macOS Intel and
Linux ARM64 from current acceptance; their prior evidence remains historical:

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
completed port because a Rust wrapper invokes it. Wikimap's pinned upstream
source is outside the owned Rust port. Moru's adapter remains in scope, and
the Wikimap search path still requires the upstream Python interpreter.

## Delivery waves

| Wave | Units | Work |
| --- | ---: | --- |
| Frequent callbacks | 12 | Pretool, prompt/mailbox, Stop, continuation, renderer and ingress paths |
| State and observability | 10 | Mailboxes, cards, memory, snapshots, recovery and HQ reports |
| Lifecycle and dispatch | 14 | Admission, hooks, finish, loops, routing, discovery and setup |
| Owned tooling | 27 | Remaining direct CLIs and their owned supporting code |
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

## Build and install approval

The user's current restriction requires an explicit matching request before
native builds or local installation/activation. A request to continue source
work, commit, integrate main or push does not grant either effect. Earlier
batch-delivery assumptions do not override this restriction. Discussing or
editing this policy also does not authorize a build.

Build/package generation, hosted build dispatch and local installation are
separate effects: carry out only the requested subset. Test execution that
compiles native test code has its own boundary; when that authority is unclear,
hold compilation, ask once and continue independent source or static checks.
Never relabel a release build as a test to cross the approval boundary.

The native bundle workflow has only a manual trigger. Its boolean
`build_runtime` input defaults to false, and the bundle job requires the
typed input to be true, a manual dispatch, the public repository and the main
branch. Missing or false opt-in skips the entire job before either matrix
runner starts. GitHub documents the [typed input and job condition semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
Do not dispatch a hosted build merely to validate this guard.

When builds or installation are deferred, preserve the exact source batch and
its remaining verification. Report static checks separately from executed
native tests, transported-bundle checks and installed-runtime acceptance. Do not
mark an uncompiled or uninstalled unit as accepted on that evidence alone.

## Per-batch work

Use the durable performance checkout and existing performance branch. Keep the
main checkout as acceptance boundary and preserve unrelated sessions' work.
Maintain one bounded implementation action per cohesive batch; reuse unchanged
guidance, measurements and checks. Record the complete Goal here and in the
ledger while each action closes only its declared batch.

Implement and run the affected checks within the current approval, then
review/finish the exact source batch before its authorized commit or main
integration. Apply the build and install approval boundary above before any
native compilation, bundling, hosted build or activation. Record deferred
verification explicitly; source completion alone never establishes a verified
native unit. Refresh publication attestation only for an authorized publication
whose rules or inputs require it. Keep CI and other-host results explicit.
Do not report the Goal complete after one batch.

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

The shared native `PythonText` owner removes Unicode string-representation and
decimal-classification deferral from manifest validation and CLI errors. It
uses contiguous character-property ranges generated during the existing static
build-contract step, with no interpreter call during installed execution.
An exhaustive Rust test compares representation and three character classes
against the builder Python digest for every valid Unicode scalar, plus
multi-character quote/escape tests. The contract follows the builder's Unicode
database; a different consumer Python database can differ on newly assigned
characters. Lone surrogates remain a separate JSON-input migration boundary.

Manifest JSON now uses an isolated native value/parser boundary. Integers retain
their exact decimal digits, integer `-0` normalizes to `0`, float negative zero
stays distinct, and Python's `NaN`/`Infinity` spellings and exponent overflow
are represented without changing global serde features. Ordered objects keep
the first key position when a later duplicate overwrites its value. The builder
Python's integer digit limit is captured alongside existing static contracts.
Malformed JSON, lone surrogates, nesting beyond 128 and digit-limit exceptions
still decline before effects; these are open migration work, not silently
accepted inputs. Explicit Python environment overrides keep their earlier
whole-command compatibility behavior.

Run `42161685172` completed all four supported-host bundle and transported
consumer jobs successfully at `d5c0f5e0`. This closes the earlier Intel timeout
acceptance gap for that source revision; subsequent commits retain their own
CI requirements. The ledger keeps direct Python entry/caller reconciliation
separate from the frozen checkout engine's cross-platform acceptance.
