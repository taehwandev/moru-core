---
keyflow_id: sys_runtime_native_work_cards
status: review
type: ai-generated
---

# Native work-card CLI

## Scope and contract

The generated launcher handles `work-cards [--project PATH] list [--all]` in
Rust. The existing Python module remains the owner of internal card reads,
writes, migrations, resume, liveness and error/recovery beyond the bounded close
extension below. This
extends one already-covered inventory boundary without adding another entry.

Open only an existing database with SQLite read-only flags. Missing stores,
missing tables and a symlinked card directory preserve the existing empty list;
valid database-file symlinks retain their resolved target. Supported schemas are
0–3. Preserve active/all-state filtering, repository isolation, descending update
order, field names/nulls/integers/Unicode and empty defaults for missing legacy
run/runtime/session fields. Output retains Python's JSON spacing and key order.
Repository keys use the same bounded Git common-dir command and SHA-256 prefix,
including linked-worktree identity and non-Git/missing-Git fallback.
Storage, repository identity and CLI rendering have separate native owners.

The native connection uses an immediate busy check. A lock or other uncertainty
closes native resources and delegates to Python, which retains its existing
two-second timeout and recovery. Native does not use immutable/no-lock flags.
The Python owner can use its pre-existing immutable retry after an operational
error; preserving that behavior is a compatibility boundary, not a new native
shortcut. Unknown versions, custom indexes, float/blob conversion, unusual CLI
forms, source/environment drift and uncertain paths also retain Python.

## Bundled dependency and distribution

Pin `rusqlite` 0.41.1 with default features disabled and `bundled` enabled.
The locked `libsqlite3-sys` 0.39.1 provides SQLite 3.54.1. This fits the existing
Rust 1.94.1 toolchain; consumers need no system SQLite installation. Offline
builds still require previously fetched crates. No paid service or new daemon
is introduced. The source receipt covers the dependency notices, which are also
retained inside the executable; the archive format is unchanged.

The local dependency inspection shows no dynamic SQLite library dependency.
This is a packaging observation, not a speed or memory measurement.
The upstream [bundled-driver description](https://github.com/rusqlite/rusqlite#readme)
explains static inclusion. SQLite's [URI/immutable contract](https://www.sqlite.org/uri.html)
and [WAL documentation](https://www.sqlite.org/wal.html) explain why the native
path retains locking and delegates uncertain recovery.

## Verification and delivery boundary

The final Rust suite passes 28 tests, including the minimum bundled SQLite
version and JSON-format checks. Python verification covers 69 distinct passing
cases: the first 39-case card/identity run passed 38 cases; its remaining test
incorrectly expected a locked-store error instead of the canonical recovery.
Correct that expectation and rerun only that case plus 20 launcher tests, all
21 passing. Ten bundle tests also pass. After notice/source binding changed,
rerun the affected source-drift case, which passes. Previously passed unchanged
cases are retained rather than rerun just for a cleaner aggregate log.
After separating the identity owner, rerun its two affected cases and the
fresh-consumer archive; both cases and all 53 consumer checks pass again.

These checks cover schema versions, equal timestamps, linked/non-Git identity,
live and checkpointed WAL, locked/corrupt/future stores, read-only directories,
symlinks and unusual data/CLI fallback. Main database bytes and live WAL bytes
remain unchanged by the supported reads. SQLite's normal shared-memory locking
is retained; this does not claim that no transient SQLite sidecar activity occurs.

The final archive passes all 53 transported consumer checks. The three added
checks prove missing-store listing without Git/Python and active/all listing
with Git-only PATH, including exact Python output and unchanged database bytes.
Four-host CI includes the new suite; no remote or other-host run is claimed.

No latency, CPU/RSS or cost experiment is repeated, and no numerical speed or
savings claim is made. Those initial read-only acceptance results preceded
the later authorized main integration, push and local activation batches.

## Existing-store settlement

The full migration Goal next extends `work-cards [--project PATH] close WORK_ID`
with optional `--state done|cancelled`. `CardSettlement` owns one transaction;
the CLI owns arguments/output and reuses the repository identity, source guard,
path validation and UTC formatter. No general SQL operation is exposed.

Eligibility requires an existing canonical version-3 WAL store with its exact
owned schema and no custom indexes/triggers. Native reserves the writer with
`BEGIN IMMEDIATE` before inspecting the schema, so concurrent DDL/writers cannot
change that decision before UPDATE. Unknown stores, legacy/future schemas,
non-WAL mode, symlinked directories/sidecars, busy locks and unsupported inputs
close the reservation and defer before DML. The unit remains partial: Python
still owns creation, upgrades, open, resume and other recovery.

One UPDATE changes only an active card matching the repository and work ID.
It preserves all other fields/rows and the Python UTC timestamp shape. Commit
precedes public success. An absent/already-settled card returns the canonical
exit 2 diagnostic. Once UPDATE is attempted, SQLite failures return directly;
the CLI never retries through Python after a possible mutation. Connection
closure rolls back an uncommitted transaction. Unit-test process trees retain
the requirement for an explicit temporary state home before native writes.

Observing checks cover both backends, Git-only PATH, default/cancelled results,
unmodified rows, timestamp bounds, read-snapshot isolation, file symlinks and
the declined-store/input/lock boundaries. Transported-consumer smoke includes
both settled states and the already-settled diagnostic without Python.

Local verification covers 41 distinct passing card/reference/identity/ledger
cases. The first 23-case run passed 22; one fixture expected its WAL pathname
to be absent although the host SQLite left an empty WAL after its last reader.
The fixture now checks that it is empty before replacing it with the synthetic
symlink. That case plus 18 reference/identity cases pass. An extended real
store-guard test and the three ledger cases pass after the final conservative
non-UTF-8 environment handling change. Rust tests pass in both default and
software-SHA modes (31 each); final consumer acceptance covers 93 checks.
These are local results for this extension; its other-host CI remains open.
