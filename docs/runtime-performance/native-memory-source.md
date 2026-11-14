---
keyflow_id: sys_native_memory_source
status: review
type: ai-generated
---

# Native project-memory source verification

`_source_blob` delegates ordinary candidate-file resolution, regular-file checks,
tracked-file verification and bounded Git capture to `MemorySource` in Rust.
Python retains relative-path admission and resolves the project root in its
original process before delegation. [Source-status aggregation](native-memory-status.md)
now batches ordinary checks in Rust while its cache object remains caller-owned.
Neither increment completes migration unit16.

Git remains the hash implementation: `ls-files --error-unmatch` uses literal
pathspecs, and `hash-object --no-filters -- <path>` hashes worktree bytes without
writing an object. SHA1/SHA256 repositories, two-second per-process deadlines,
missing Git, nonzero exits and malformed hashes preserve the original result.
Component-wise resolution preserves macOS supplied case. Final/ancestor links
and nonfiles retain rejection; loops and uncertain resolutions defer.

The private protocol requires matching source/Unicode, UTF-8 and EOF-input
profiles. The bridge proves actual fd0 is `/dev/null` or an empty anonymous pipe
whose writers closed, without reading it. TTYs, live/nonempty pipes, named FIFOs,
regular-file stdin and unproven locales defer before native Git execution.
Descriptor-root queries also decline. Tracked checks retain raw binary output;
hash checks decode stdout before stderr, including on failure. Failing UTF-8 bytes
within packet limits return a typed error so Python raises its original decoding
exception without executing Git again. Transport uncertainty and packet limits
retain the original read-only fallback.

Verification on macOS ARM64: 112 focused Python cases, nine existing Rust memory
tests, and 204 transported bundle checks passed. The new verifier suite covers
exact argv, dirty/filter bytes, SHA256, literal names, paths/links/FIFOs, timeouts,
decoding order/errors, input admission and real caller execution with Python
file checks disabled. Five transported queries use Git-only or empty PATH.
Fixtures are temporary; file, Git index/object state and existing memory records
are preserved. Actual installation is checked separately after main integration.
Linux exact-batch acceptance and the remaining unsupported profiles stay open.
No new hosted build, release, measured speedup or completed-unit claim is made.
