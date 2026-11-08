---
keyflow_id: sys_runtime_native_work_cards
status: review
type: ai-generated
---

# Native work-card CLI

## Scope and contract

The generated launcher handles `work-cards [--project PATH] list [--all]` in
Rust. Internal Python card callers now use the private native snapshot reader
described below. The existing module retains writes, migrations, resume,
liveness and error/recovery beyond the bounded close
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
shortcut. Unknown versions, custom indexes, public CLI float/blob conversion,
unusual CLI forms, source/environment drift and uncertain paths also retain Python.

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
The original four-host CI coverage predates the current two supported targets,
macOS ARM64 and Linux x86_64. No remote or other-host run is claimed here.

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

## Internal typed snapshots

`list_cards` now submits an optional private read request, so ordinary lifecycle
callers use native SQLite reads rather than only the public CLI. The source,
environment, existing-store, schema, index, lock and path checks are shared with
CLI lookup. No database path or SQL arrives in a request: the native owner
derives the existing store from the normal global state location. No store,
table, index, schema, cache or card is created or changed. The original Python
lookup remains the rollback and exceptional recovery path.

The Python caller retains its canonical repository-key lookup and per-read-scope
Git memo, supplying that content-free key to the native query. The native reader
does not repeat Git identity resolution or replace a memoized identity with a
later checkout observation.

Snapshots preserve `SELECT *` column order, remove `repo`, and append only
missing legacy `run_id`, `runtime` and `session_id` defaults. Private cells carry
explicit NULL/integer/real/text/blob tags; real text round-trips binary64 values
and infinities, and hexadecimal blobs round-trip arbitrary bytes. This retains
Python's internal return types without forcing them through public JSON number
or string conversion. The adapter validates the complete response before
returning any row. Invalid UTF-8, malformed tags, oversized output or unsupported
state declines the whole read. SQLite's ordinary shared-memory locking remains
in force; no immutable/no-lock shortcut is added. Public CLI float/blob fallback
is retained. Creation, schema upgrades, internal writes, resume/liveness,
exceptional recovery and direct Python removal remain in unit 17's open scope.

The internal-read increment passed 60 initial Python card/reference/lifecycle/
identity/inventory cases, then all 10 affected snapshot cases after a review
correction (61 distinct Python cases). Ten Rust card tests and 163 final
transported macOS ARM64 checks passed. Native-required cases disable Python
SQLite replay, compare exact types and dictionary order, and observe committed
WAL snapshots. Private transported reads run with empty PATH. Review exposed an
early `RuntimeError` from path identity lookup replacing the original empty-store
or schema error; the adapter now declines and reproducer tests preserve the
original order. Missing stores remain absent and main database bytes unchanged.
SQLite may still perform its normal transient shared-memory locking. Linux
acceptance for this exact batch remains pending an authorized manual build.
