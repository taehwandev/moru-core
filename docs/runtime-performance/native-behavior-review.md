---
keyflow_id: sys_runtime_performance_native_behavior_review
status: review
type: ai-generated
---

# Native offline review export

Unit 58 now connects the existing `agent_behavior_trace.py` CLI to a fused,
read-only native export. The normal CLI still uses Python argparse. After
parsing, it selects the private native command only when the explicitly
supplied executable resolves to the current source-bound artifact. The native
process reads at most 4 MiB + 1 byte, validates the finished journal and matching
receipt, rejects event content fields, calls the existing `BehaviorTrace`
normalizer directly, and emits the same ASCII JSON bytes and newline.
No second normalizer process is needed on this selected path.

`BehaviorReview` owns this capability. Allowed imports are std, serde_json,
the canonical PythonJson parser and the existing BehaviorTrace engine.
Providers, child processes and workflow writes are forbidden. The launcher
contains only a thin private dispatch. No dependencies or runtime aliases were
added, and `export_review` retains its original library and alternate-executable
contract.

## Compatibility and failure behavior

- Backend rollback, stale/missing source receipts, different executables,
  non-file records and loaded Python startup customizers retain the original
  implementation before native selection.
- A JSON encoding/parser profile outside the native implementation returns an
  empty status 78. The Python CLI may then reread this read-only input using the
  original function. This includes UTF16/32, unsupported depth and mismatched
  integer limits. A dirty status 78 is an error.
- Other selected-native failures never replay the original function. The CLI
  preserves its fixed error line and status 1, including malformed records,
  receipt mismatches and native failure. Soft-fail settings do not convert the
  private command's failures into success.
- Journal metadata may remain private or contain Python JSON nonfinite values.
  It is never forwarded to the trace, printed, or persisted. Event fields retain
  the existing content-free allowlist and normalizer validation.

## Verification and remaining work

The oracle fixture is the byte-identical Python CLI from commit 272e553f, SHA256
`895f6663af6c4d71713875c3ef3fe2ce1dc299ec4984dfe8790fa302ea34288c`.
The 21 Python checks pass with no skips. They compare exact status/stdout/stderr, use actual native record
IO, observe one native call with no Python record replay, and cover all three
providers/statuses, byte/event/case limits, BOM/duplicates/private nonfinite
metadata, invalid schemas, alternate executables and explicit rollback.
Existing ACP journal/evaluator tests use local fixture workers; no model or
provider turn is submitted.

Eleven focused Rust checks pass, including the normalizer and new journal boundary.
Four relocated empty-PATH checks cover success, privacy rejection, integer-limit
decline and UTF16 decline. The debug candidate binds 617 source inputs; four
actual installed-runtime/configuration hashes remain unchanged. These are local
debug/test and temporary-consumer results, with no timing, CPU, RSS or cost claim.
The manual two-host workflow includes the selector and smoke helper; its
dispatch-only trigger and default-false build input are unchanged.

Unit 58 remains `partial_native`. Python argparse, direct library execution,
alternate executables and unsupported encodings/depth remain compatibility
work. Linux acceptance, release packaging and actual installation/activation
remain unverified and held. This batch does not complete the 62-unit Goal.
