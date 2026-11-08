---
keyflow_id: sys_runtime_native_work_cards
status: review
type: ai-generated
---

# Native work-card CLI

## Scope and contract

The generated launcher handles `work-cards [--project PATH] list [--all]` in
Rust. Internal Python card callers now use the private native snapshot reader
described below. The existing module retains bootstrap, migrations, resume
and exceptional recovery beyond the bounded native extensions below. This
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
with optional `--state done|cancelled`. `CardTransaction` owns one transaction;
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
is retained. Creation, schema upgrades, internal writes, resume,
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

## Native recall context

`open_card_lines` now requests native context directly. The read-only owner
filters out current work, checks at most 20 other cards against project existence
and their cached run registries, and renders at most three live cards plus the
unchecked/hidden count. Only `completed` and `cancelled` are settled registry
states; an unknown nonempty state retains the original unfinished result.
Missing projects, registries or run IDs and settled entries produce ordered
settlement candidates. Registry cache lifetime is one request.
Cache keys use the original lexical dot equivalence (`p` and `./p`) without
canonicalizing distinct aliases; the guarded read keeps its original path.

The private result contains complete lines and ordered candidates. Python still
dispatches candidates through the original `settle_card` writer when requested,
with the original first-error abort behavior. Native policy does not write the
database or registry. The adapter rejects an entire result containing an action
for current work before dispatching any returned candidate. Invalid UTF-8 or
JSON syntax retains the original empty
registry result; unsupported parse shapes and unusual files decline before
use. In particular `runs: null` retains its original error through rollback,
and FIFOs/symlinks are declined before stream consumption. Rendering reads only
fields that the original bounded algorithm reaches. Exceptional input recovery,
all creation/upgrades and remaining internal writes remain open migration work.

The context increment passed 70 initial Python cases and all 10 affected context
cases after review corrections (71 distinct cases), 19 final Rust card tests and
164 transported macOS ARM64 checks. Tests prohibit Python policy/SQLite replay,
compare original recall and write ordering, and verify first-error abort and
unchanged rows. Review found two missing checks: malformed returned actions
could target current work, and `p`/`./p` split a cache that Python shares. Full
result rejection now precedes any returned action, and a seeded-cache regression
checks lexical equivalence while retaining roots, parent components and distinct
aliases. Unsupported streams are declined within a fixed process timeout. These
checks use synthetic state only; exact-batch Linux acceptance remains pending.

## Internal card transactions

`open_card` and `settle_card` retain their original Python bootstrap and argument
evaluation order, then offer the DML to `CardTransaction`. Opening inserts or
reactivates the repository/work pair, preserves its original creation timestamp,
refreshes its current run/session fields and prunes all rows whose update text
precedes the 90-day cutoff. Upsert and pruning commit together. Settlement changes
only an active matching pair and returns the original boolean. Native does not
create files, upgrade schemas or receive arbitrary SQL/database paths.

The private ingress accepts canonical v3 WAL stores, including the known column
orders produced by the existing legacy bootstrap. A writer reservation protects
schema inspection and DML. Unknown schemas, constraints, indexes, triggers,
unsupported arguments and busy stores decline before any DML; Python then owns
the original operation and timeout. The public close CLI keeps its previous,
narrower schema admission. No stored format or schema version changes.
The private adapter reads the actual parent connection's foreign-key setting
and applies/verifies it before reserving the native writer. This matters because
bundled SQLite enables foreign keys by default while supported Python builds
can default to disabled. Retention therefore preserves the original dependent
rows, cascades or constraint failures. Public CLI close cannot inspect a live
Python connection and declines incoming foreign-key schemas to its original
owner. Unrelated tables without incoming card references remain eligible.

Writes use a separate effect-aware transport. A read-only capability exchange
first rejects old installed binaries without ever starting their writer. Only a
failure before writer creation or an empty exit-125 response permits Python
execution. Once a child may
have attempted DML, timeout, malformed/duplicate/oversized output, stderr or an
unexpected exit raises an error without replay. The child is killed and reaped
on interrupted communication. A structured SQLite failure keeps its class and
message; Python 3.11+ also retains the extended code/name. The mapping follows
the selected interpreter: [CPython 3.9](https://github.com/python/cpython/blob/3.9/Modules/_sqlite/util.c)
and [3.11+](https://github.com/python/cpython/blob/3.11/Modules/_sqlite/util.c)
differ for misuse/range failures. This protocol never uses the read-only probe's
retry/fallback behavior.

Bootstrap/schema upgrades, resume, exceptional read/registry recovery,
unsupported customized writes and direct Python retirement remain open in unit
17. The new Python file is transport/eligibility glue and remains in the full
migration ledger; this increment does not claim full native card ownership.

Final local verification passes 87 Python 3.9 card/reference/lifecycle/identity/
ledger cases, two selected Python 3.14 error/FK oracle cases, 31 Rust card tests
and 169 transported macOS ARM64 checks. The new consumer checks run native
insert, reactivation, global pruning and both settlement results with no Python
or Git on PATH. Parent SQL traces prove supported public APIs use native DML.
Fault peers prove that actual committed child effects survive lost responses
without a second parent write. Transaction tests exercise all eight bootstrap
layouts, quote/token distinctions and DELETE/COMMIT/UPDATE rollback.

The initial 85-case Python suite exposed stale installed launchers: 14 errors
and two lifecycle failures. Read-only capability negotiation and an old-protocol
regression repair that boundary. Independent review additionally exposed the
SQLite foreign-key default difference; Python/native CASCADE and RESTRICT
oracles now compare exact card and dependent-table outcomes under both settings.
The final suite and independent correction review pass. All fixtures are
synthetic. Exact-batch Linux CI remains pending; no release or speed claim is
made by this local increment.
