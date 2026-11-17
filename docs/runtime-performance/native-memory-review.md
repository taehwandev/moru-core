---
keyflow_id: sys_native_memory_review
status: review
type: ai-generated
---

# Native review dates and fused report inputs

`MemoryReview` delegates two related read-only decisions to Rust:

| Operation | Behavior |
| --- | --- |
| `review-partition` | Preserve supplied record order and divide strict ISO dates into expired and upcoming buckets |
| `review-findings` | Reuse the existing native live-status/stable-ID selector inside the same process, then produce the date buckets |

Both operations preserve the last review date for every duplicate ID, including
earlier records with that ID. Expired dates include today; upcoming dates exclude
today and include the horizon. The existing `MemoryRecord` Gregorian validator
admits exact ASCII `YYYY-MM-DD`, leap centuries and years 1 through 9999. Raw
requests reject unsupported dates rather than returning a partial result.

The typed adapter transports only IDs, statuses and review dates. Rust returns
indices and Python retains the original record objects, reason text and full
report projection. Ordinary report input needs one live/date request; no Python
live prefix or date parser is replayed. This does not claim fewer requests for
the other report sections or a measured speed improvement.

Extended date formats retain the current interpreter's original behavior through
fallback. Customized date/delta bindings and nonordinary records also defer.
Calendar overflow remains after original live-input errors and before date
parsing, including for an empty store. The fallback keeps date comparisons lazy
so an expired record's projection still precedes later upcoming comparisons.
The projection/error ordering was confirmed against the pre-edit source.

Pre-edit report values, key order and exception priorities were captured before
extraction. Verification covers native-only negative controls, one-request
fusion, seeded parity, duplicate-ID rules, Unicode metadata, calendar/profile
errors and a real temporary-store CLI that leaves bytes unchanged. Empty inputs
start no native process. No store, provider or authority changes are introduced.
The macOS ARM64 batch covers 226 distinct Python cases. The first run passed
225 and exposed a malformed-ID fixture construction error; the corrected
20-case review module passed, including root-selector repair verification.
The fixture keeps invalid IDs while giving unrelated body/source fields valid
strings. Runtime inputs did not change after the 51 Rust memory tests and 230
transported bundle checks passed. Actual installed acceptance is separate.
Unit 16 remains partial; exact Linux execution and performance measurements
remain open. Push, hosted builds and deployment remain on hold.
