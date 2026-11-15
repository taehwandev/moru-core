---
keyflow_id: runtime_perf_native_retention_registry
status: stable
type: ai-generated
---

# Native retention registry snapshots

The shared run-evidence reader validates ordinary registry state maps, batches
preview scan/classification and identity snapshots, and counts directory bytes
in the existing `RegistryRead` native owner. Inventory unit51 remains partial:
the public CLI, preparation and exceptional/custom profiles, locks, deletion
and maintenance orchestration retain Python work.
Neither this kernel nor source integration completes a public runtime unit.

## Contract and authority

`--registry-read-probe retention-states` accepts a canonical absolute state
directory, the caller's state vocabulary and its integer-decoder limit. The
limit must match the compiled parser contract. The bounded1MiB reader opens
only `run-registry.json`, without creating or acquiring locks. Ordinary registry
snapshot operations keep their different existing-lock contract.

The existing Python-compatible JSON parser preserves schema equality for1,
`true` and1.0, ignored nonfinite/large numbers and last-key JSON semantics.
Ordered ID/state pairs preserve the original map's insertion order. Invalid
schema, rows, states or duplicate IDs return an explicit unreadable result;
no row is dropped to make a malformed registry look valid.

Unrepresentable inputs, parser uncertainty, file/encoding/profile limits and
symlinks decline quietly with125. The original reader then preserves caught
JSON/UTF-8/IO failures and uncaught integer-digit-limit errors. A parse decline
is not silently converted into an empty or unreadable registry. Modified JSON
decoders, file readers or schema settings keep reference behavior; custom
ordinary state vocabularies are transported explicitly.

The native owner cannot prune, initialize a registry, create lock files,
claim a run or change retention policy. Python retains the typed removal
preview and its observations. Application still rechecks live registry state
and evidence identity under both original locks before deleting anything.

## Verification and remaining work

The immutable original `agent_run_evidence.py` at
`61b69b2db57c7cbe32af4ac7af23fc733ba007cf` supplies the reader and preview oracle.
The affected Python suite passed41 cases:9 new native retention cases,
7 existing registry-read cases,22 retention/maintenance cases and3 ledger
cases. The `registry_read::retention` Rust selector passed all four owner cases.

A real observer records one native request, no Python registry file read and
no reference reader replay. A forced-Python negative control records both
Python operations. The native state map also feeds the original typed retention
preview: the running run stays protected and the completed run is classified
identically, with no deletion. Existing regressions cover resume after preview,
modified/replaced evidence, unreadable registries and both deletion locks.

Only synthetic registry/run fixtures are used. No real pruning, release build,
archive, hosted dispatch, provider call or installed-runtime change is part of
this source batch. Portable and installed acceptance remain separate. No
latency, CPU, RSS or cost improvement is inferred from passing parity tests.

The full56-unit ledger keeps all supporting Python sources and the external
Wikimap source. No Python source is retired here. Full native public pruning
and maintenance still require the remaining CLI/IO/policy/locking migration,
complete caller proof and final delivery acceptance.

## Evidence identity metadata

The same read owner serves `retention-identities` with a list of absolute
canonical `paths`. This compatibility API batches the entire list; ordinary
previews now use the combined planning request below, including current-plan
revalidation under the original locks. It discovers paths
iteratively without descending directory symlinks,
then returns the root followed by all children in path-component order. Thus
`a/x` precedes `a-b`, matching `sorted(Path.rglob(...))` rather than sorting
rendered path strings. Hidden names, empty directories, file/directory/broken
symlinks and FIFO metadata retain the original behavior; no file contents are
opened. A root symlink retains reference behavior.

Each row preserves `(relative, device, inode, mode, size, mtime_ns, ctime_ns)`
as integers and a relative path; the root is `.`. Python reconstructs the exact
tuple of tuples. Nanosecond timestamps use checked integer arithmetic, including
negative times. More than256 roots or4096 total entries, oversized output, unrepresentable names,
timestamps, filesystem errors and custom Path methods decline without partial
results. Original traversal/error behavior remains the compatibility path.

Against the immutable `bd675de72eacc55607dbfe1fb8b0bd948097ae8b` source, the
compatible Python checks cover55 cases:54 pass and1 non-UTF-8 filename case is
skipped because this local filesystem or sandbox rejects creating that name.
That filesystem case remains unverified here and must run on a supporting
Linux environment. Raw unrepresentable-root and schema refusals are separately
observed. Three Rust identity cases and5 empty-PATH debug consumer checks pass.

The real observer records one metadata request for multiple roots with no
Python rglob/lstat or identity replay; the forced-Python control observes those
calls. Immediate pre-delete identity checks remain in the original Python path,
at the original point in each loop. They are not replaced by a stale batch.
An actual apply operation on owned fixtures uses batched preview snapshots
under the existing locks: modified evidence is kept and only the unchanged
eligible fixture is removed. A regression changes the second candidate after
the first deletion and proves the second is preserved. The existing project-maintenance test now explicitly
disables global skill curation so its retention check stays within that fixture.
Global skill-learning storage is outside this fixture's acceptance boundary.

That debug receipt bound589 runtime inputs. Actual runtime/config file hashes
remain unchanged; this is still source/test acceptance, not a user-runtime
installation, Linux release result or full unit51 completion. No Python source
is retired and all remaining full56-unit responsibilities remain in the ledger.

## Batched directory-size accounting

`retention-bytes` accepts the same bounded root list and reads target metadata
only. A fresh stat follows the file predicate, preserving the original per-item
read order. File symlinks contribute their target sizes, directory symlinks are
not descended, duplicate roots contribute repeatedly, and an explicitly supplied
file root contributes zero because the existing function counts descendants.
Unsupported roots or errors decline the whole request without a partial total.

Native accumulation uses a checked128-bit integer and returns canonical decimal
text; Python reconstructs an exact integer. Plain lists and canonical removal
previews with builtin list iteration are supported. Preview identity observations,
options and opaque values stay local. Custom containers/Path methods preserve
reference behavior. Empty lists and empty typed previews start no process.

The immutable `c8919ff2f60e553e76ba45518c9f906437c3d910` source provides the size
oracle. The final affected run covers63 cases:62 pass and the existing local
non-UTF-8 filename case remains skipped. Four Rust metadata cases and5 fresh
empty-PATH size checks pass. Observers prove one request for multiple roots and
for the actual typed removal list, with no original Python size scan. Report
totals match the original without creating locks or changing fixture bytes.

That size-accounting batch bound589 runtime source inputs. Source/test evidence
does not prove Linux, release, installation or full unit51 acceptance. Immediate
Python identity checks and all original deletion authority remain intact.

## Prepared preview planning

`retention-plan` receives the already prepared directory, registry state map or
uncertainty, protected IDs, cutoffs, keep count and state/phase vocabularies.
Python performs the original directory/state/protected/time preparation once.
An ordinary populated preview then uses one native request for directory
classification, stable newest-first order and all removable-root identities.
Registry preparation can separately use the existing state-map request; there
is no per-candidate subprocess. Empty directories start no planning process.

Held/active/uncertain and orphan branches skip phase reads exactly as before.
The first phase read precedes the settled-state test; a nonfinished candidate
uses the original second phase observation before age classification. Missing,
invalid JSON and invalid UTF-8 keep their empty-phase meaning. Unsupported
parser/digit-limit profiles, phase symlinks, filesystem conditions and bounds
decline the whole response, then resume the reference loop with its prepared
context. That fallback does not read the registry or protected iterator again,
or start a second metadata request after a failed combined request.

The reader caps4096 entries,256 removable roots,4096 shared identity entries,
1MiB per phase read and8MiB across phase reads. Responses keep the existing1MiB
transport bound. Python validates category names/order relationships, protected
and holding-state exclusions, and complete root-relative identity rows before
constructing the existing removal-list type. Original options remain local,
including opaque threshold values already converted by preparation.

A source review found a real error mismatch: Rust `Path::is_dir` hid permission
errors that the Python3.9 reference raises. A readable but nonsearchable owned
directory reproduced the public-boundary failure before repair. The planner
now distinguishes ordinary ignored path errors from uncertainty, which selects
reference behavior. No permission or exception rule was weakened.

The immutable `0424ec5d81517f79773e7f90538550914acf7be5` source supplies the
planning oracle. Focused checks cover78 distinct Python cases:77 pass and the
existing local non-UTF-8 filename case remains skipped. All22 registry Rust
tests and five fresh relocated empty-PATH planning checks pass. Observers prove
zero original Python phase/run-predicate replay and one combined request on
ordinary previews; forced Python records the original loop. Held-run and
escaping-metadata response injections cannot create invalid deletion candidates.

All604 runtime-source hashes match the debug fixture, and four actual runtime/
config file hashes stayed unchanged. Both original deletion locks, live owner
revalidation and immediate Python identity checks remain at their original
points, including the regression that changes a second candidate after the
first deletion. Only owned fixtures are removed in these checks. No latency,
release bundle, hosted build, actual activation, Linux or full-unit completion
claim is made. No Python source is retired.
