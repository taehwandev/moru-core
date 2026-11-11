---
keyflow_id: sys_native_doc_transcript
status: review
type: ai-generated
---

# Native required-document transcript scans

This copy-first extension moves the shared delivery helper's real file scans
into Rust. The original Python delivery owner still decides the run/evidence,
reads document contents, serializes marker updates, enforces redelivery budgets
and renders context. It remains the compatibility path when native input,
filesystem, source or environment admission declines.

The existing lifecycle CLI and Claude/Codex/Antigravity callers share these
helpers. This is supporting runtime progress for inventory units 5, 19 and 31;
it does not complete their public CLIs, callbacks or remaining owned code.

| Operation | Source contract |
| --- | --- |
| `compacted` | File size zero means false. Scan candidate byte lines to EOF, including a final row without LF. |
| `aligned` | Preserve the recorded size, final-LF shortcut, last 65536-byte window, inclusive fallback bound and read-error size result. |
| `due` | Keep exact-offset/counter checks first; same size means false, a shorter rewritten file restarts at zero, and only LF-complete candidate rows count. |

The cheap filter matches the original quoted ASCII marker bytes before JSON
decoding. The parser preserves duplicate keys and unused nonfinite values.
UTF8 BOM is accepted; unsupported byte encodings, surrogate/depth/parser shapes
decline the entire read-only query instead of silently skipping a valid boundary.
Native streaming adds no total transcript-size or line-length cap.

The private source-bound protocol returns typed facts only. Regular files and
safe symlinks are admitted with nonblocking guarded opens; descriptor aliases,
devices, pipes, sockets, uncertain inode changes and excessive symlink chains
defer before consuming those streams. Ordinary size-zero and exhausted-budget
answers retain their original short circuits. Queries never edit transcript,
document, marker, evidence, session or settings bytes. No cross-call cache is added.

The Python adapter validates exact input/result types and uses the original
helper for unsupported integer/customized profiles or failed/old native packets.
It does not parse transcript lines. Marker locks, atomic replacement, offsets,
compaction budget and advisory fail-quiet behavior remain in the original owner.

Acceptance uses real synthetic files and source/native results, partial/replaced
transcripts, byte-encoding edge cases, no-write and inherited-descriptor checks,
shared delivery/Antigravity marker flows, and a transported empty-PATH consumer.
No real user transcript or model/provider invocation is required. Exact-batch
Linux acceptance and full Python retirement remain separate open work; no new
cross-host speedup claim is made.

Verification: 92 distinct Python 3.9 source/native/caller/ledger cases (91 first
passes and one corrected platform-specific negative-seek exception assertion),
14 Python 3.14 cases, 15 Rust tests (14 initial passes plus the sandbox-blocked
owned Unix socket case rerun with the required local capability), and 187
transported macOS ARM64 checks passed. Independent review repaired raw UTF8
surrogatepass classification, searchable-only ancestor admission and optional
accelerator-availability errors; all retain original behavior through native
execution or explicit compatibility fallback. No source assertion was waived.

The wider Claude/Antigravity caller, generic transport, inventory and template
regression covered 71 cases (70 initial passes plus one repaired existing
test-fixture isolation error; three ledger cases overlap the 92-case cohort).
That verifier test already failed with native acceleration disabled: it patched
the state module's marker root while an imported copy in the verifier still
pointed at the real home. Patching both fixture roots preserves every cleanup
assertion and avoids writing real user evidence. Production verifier code is unchanged.
