---
keyflow_id: sys_native_memory_status
status: review
type: ai-generated
---

# Native memory source-status aggregation

When a record needs a new hash, the source-status caller sends its source files
and relevant per-recall cache to `MemoryStatus`. Rust queries uncached paths through
the existing [source-blob owner](native-memory-source.md), reuses each hash once,
and emits the original status, warning and ordered unverified paths. `changed`
takes precedence over `unavailable`; duplicate paths retain their warning order.
An empty hash is cached too. The caller's cache keeps its identity, existing
insertion order and unrelated values, including values outside the native schema.
Fully cached records retain the existing in-process Python aggregation and make
zero native requests. This avoids introducing process startup into a cache hit;
the private native protocol can still aggregate cached input for native callers.

The Python bridge validates packets and merges only new cache entries. When a
later path declines native resolution, the completed prefix is returned before
the original loop resumes at the unresolved path. A typed UTF-8 error likewise
preserves that prefix and raises the original exception without replaying Git.
Malformed results, including reversed/excess duplicate warning paths, leave the
cache unchanged. Unsupported/customized inputs and
stdin/locale profiles retain the reference path before native query execution.
Native batching requires an already resolved absolute project path and ordinary
string cache keys. Aliased/relative roots retain the original per-file admission,
including a symlink target changing between hashes; custom key lookups are never
speculatively executed by the transport. Unrelated cache values retain identity.

This is bounded to four ordinary source entries per record and the existing
EOF/UTF-8/Unicode source profile. Git still hashes worktree bytes without filters
or object writes. No record, index, object, configuration or store is modified.
Python still owns project/profile admission, cache-only aggregation, compatibility
cache/error transport, capture/retirement and rendering. Unit16 and the full
migration remain partial.

Verification uses synthetic temporary repositories and caches: real caller
execution with Python hashing disabled, cache reuse across records, precedence,
duplicate ordering, prefix retention on decline/error, unchanged Git state,
malformed packets and negative wiring controls. Transported status queries cover
Git-only execution and cached results with no Git or Python on PATH. Results and
host limits are recorded in the migration ledger after verification.

On macOS ARM64, 126 distinct focused Python cases, 12 Rust memory tests and 207
transported checks passed. Three new Rust tests cover cached aggregation,
duplicate warning order and closed schema. Fourteen native status cases cover
real dispatch, prefix errors, root retargeting, strict response ordering and
cache-only execution without a native request. A parity-fixture cache snapshot
was corrected before those 14 cases were rerun successfully; unrelated passing
checks were retained. The inventory check also identified two existing hook
helpers missing from the ledger; both are now counted as unmigrated support.

Three reference selectors that spy on Python hashing explicitly select the
Python backend; native counterparts count actual Git calls and disable the
Python source loop. Exact-batch Linux and actual installation require separate
acceptance; no measured speedup or completed-unit claim follows from source tests.
