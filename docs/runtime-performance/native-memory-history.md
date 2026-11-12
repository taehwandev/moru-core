---
keyflow_id: sys_native_memory_history
status: review
type: ai-generated
---

# Native replacement-history traversal

The memory history caller delegates replacement-graph traversal to a pure Rust
`MemoryHistory` owner. Its private request contains only record IDs and optional
predecessor/successor links, with a matching Unicode contract. The result names
original input indices. Python returns the same original objects and projects the
original history fields; metadata is never round-tripped through the Rust JSON
representation. Unsupported/customized link shapes retain the Python reference.

Hash maps/sets provide lookup and cycle membership; a separate ordered row vector
keeps output independent of hash iteration. Index construction and graph walks
have expected linear work; no measured timing claim follows from that bound.
Duplicate IDs keep the last record while retaining the first dictionary position.
Inferred successors follow that dictionary order. An explicit nonempty successor
takes precedence even when dangling. Both graph walks stop on a missing link or
cycle; history output remains newest-first and capped at20 records. A scan that
loses the requested record declines before returning a native result, preserving
the original error. Existing record validation still precedes the store scan.

The kernel reads no stores, changes no records and grants no authority. Python
still owns store/existing-record admission, compatibility and projected field
construction. History CLI argument/error handling and complete unit16 retirement
remain open, along with the full56 inventory.

This increment isolates the existing kernel and verifies it against the original
Python history contract. Source oracles cover interrupted predecessor retire,
branches, duplicate order, cycles, missing links, scan races, the20 cap, original
metadata identity, CLI read-only behavior and a negative wiring control.
Transported history requests run with empty PATH. Exact checks and host limits
are recorded after verification; no new timing or whole-unit claim is implied.

The original projection values/order were captured before extracting the fallback,
so shared projection code cannot mask a migration error. Empty scans keep the
original KeyError without starting a native process. Malformed/duplicate-index or
duplicate-ID results defer before selecting original records.

On macOS ARM64, 139 Python cases and 21 Rust memory tests passed, including
13 history cases, nine kernel cases, 40 seeded graph comparisons and a real
temporary-store CLI check from each chain member. The 211 transported checks
include four new history queries with empty PATH. Original projection values,
field order, metadata identity and empty-scan zero-request behavior are covered.
Actual installation and exact-batch Linux acceptance require separate verification.
Deployment, push, tags and hosted builds remain on hold.
