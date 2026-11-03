---
keyflow_id: sys_runtime_native_request_paths
status: review
type: ai-generated
---

# Native explicit request-path discovery

Extend the shared discovery engine to ordinary project paths inside a request.
Previously any slash, dot or tilde caused Python replay. Supported absolute and
current-home paths now contribute native candidates before registered projects,
cwd, workspace groups and directory scanning. This extends existing inventory
units 3 and 26 without adding another migration unit.

## Contract and limits

The new `discovery_paths.rs` owns read-only request-path candidate projection.
Combine whole whitespace-delimited words with embedded path matches, matching
the canonical `shlex.split`/regex union for the admitted subset. Preserve the
exact punctuation strip set, including its removal of leading dots, before
path expansion and lookup. This port does not correct or reinterpret the old
relative-path behavior. Preserve current-home expansion, existing-path checks,
nearest marker/instruction lookup, explicit-path score, ordered candidate
merges, name boost and final ambiguity decision.

Keep the request's original path spelling for filesystem lookup and use the
existing lowercased request only for name matching. File paths resolve to their
nearest project, links retain the existing resolver, missing/unmarked paths
add no candidates, and repeated paths merge once. Complete-word paths containing
colon punctuation may coexist with regex-extracted prefixes, just as in Python.
An unquoted space does not become part of a single path token.

The admitted grammar has no quotes, backslashes, backticks or dollar signs.
Controls/whitespace outside ordinary space, tab, CR and LF also defer, as do
named-user homes, uncertain filesystem/encoding inputs and unsupported Unicode
case transformations. Quoted/escaped paths with spaces remain usable through
Python. Nothing is executed from request text; path references confer no shell,
launch or cross-repository write authority.

Generated CLI and private snapshot probes share the owner. The Python entry
builder still owns its full manifest, scope/checkpoint guidance and launch
snippets. Forced-Python rollback and exact source/environment guards remain in
place. No crate, process, installer schema, cache, mutable state or paid service
is added by this extension.

## Verification and delivery

All 30 locked offline Rust tests pass. The focused native path/discovery/registry/
group and existing entry suites cover 50 distinct Python tests. The initial run
passed 49 and found one test comparing verbose import diagnostics byte-for-byte:
those diagnostics contain process-specific memory addresses. The corrected
selector passes after comparing stable output/exit, requiring real verbose
diagnostics, and proving fallback fails when Python is absent. Reuse the 49
unchanged passes; no production correction or full-suite rerun was needed.

Checks cover exact generated CLI text/JSON, exit/status, explicit-target
precedence, multiple-target ambiguity, punctuation, home expansion, files/links,
missing paths, ordered merges and complex-input replay against the real Python
entry. An entry-manifest test tripwires the Python path-candidate fallback while
comparing the complete manifest, secondary-write checkpoint and one registry
snapshot. Existing source/environment drift and rollback tests remain covered.

A fresh archive transported to an isolated source root/home passes 57 consumer
checks. Two new cases compare actual Python and native output for ordinary and
embedded request paths while native execution has an empty PATH. Existing
checks remain intact. Formatting, whitespace and build/pack checks pass. The
four-host CI selector includes the new suite; no remote run is attested here.

Follow selective measurement: no repeated latency, CPU/RSS or cost experiment,
and no new numerical performance claim. Other-host CI execution and global
activation require their own evidence. The source and report remain on the
local performance branch for the next authorized integration step; main,
push, release and global runtime activation are separate actions.
