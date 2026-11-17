---
keyflow_id: sys_native_memory_analysis
status: review
type: ai-generated
---

# Native memory analysis binding and candidates

The analysis binding caller delegates ordinary question/context normalization to
`MemoryAnalysis` in Rust. Both original strings must be printable, nonempty after
stripping, and at most 300 Unicode characters before stripping. Empty original
strings together preserve the absent binding. Invalid ordinary text returns a
typed invalid packet so the caller raises its original ValueError. Customized
and non-string values retain original falsey, subclass and exception behavior.
The absent ordinary binding and an empty candidate list retain their original
constant-time caller return, without launching a native process. The typed
adapter also handles these empty cases directly and rejects a false absent
binding or empty normalized fields returned for nonempty inputs.

Candidate selection requires exact scope, question and context strings in the
original order. Case, negation, internal spacing and Unicode composition are not
normalized for identity. The protocol carries only these fields and returns
indices; Python retains original records and metadata. Duplicate candidates are
preserved, and no result cap is applied before freshness checks.
Candidate index ordering is validated in linear time. Customized binding keys
defer before key comparisons, preserving original short-circuit/error behavior.

The existing workspace EvidenceInputs capture, source-status checks, candidate
rendering, result limits and store/write authority remain with Python. Empty
candidate selection still returns before workspace hashing. Malformed or
unsupported profiles defer before changing the original decisions. Unit16 and
the full56 inventory remain partial.

This increment isolates the existing kernel and typed adapter. Checks compare exact original
normalization/errors, Unicode/300-character boundaries, candidate identity and
ordering, metadata object identity, unchanged freshness/budgets and an actual
temporary-store CLI that misses after source drift. Negative wiring controls
detect Python validation/filter replay. Pure transported requests need neither
Python nor Git.

Original binding and recall outputs were captured before extraction so shared
fallback code cannot mask output-field/order changes. The real CLI fixture must
also pass the original record reader before native execution is required.
The current macOS ARM64 batch passes 155 Python cases (including 16 analysis
cases), 29 Rust memory tests and 216 transported bundle checks. Actual local
activation is verified separately against the committed source and binary
hashes; this source batch does not attest Linux execution. No timing or
full-unit claim is implied.
Push, external deployment, hosted builds and release remain on hold.
