---
keyflow_id: sys_native_overhead_report
status: review
type: ai-generated
---

# Native overhead report computation

Unit 46 remains `partial_native`. The Python report now submits its collected
session counters and hook durations to one private native analysis request.
Rust owns `all`, `moru_core` and `other_projects` statistics, stable Counter ranking, shares and
hook latency summaries. The standalone `aggregate` helper uses the same owner.
Only required numeric counters and tool/subcommand names cross this adapter;
session paths, timestamps, working directories and prompt text are omitted.

Timing JSONL is read separately by the existing source-bound, regular-file
reader. It preserves replacement UTF-8 decoding, universal newlines, skipped
malformed entries, numeric/boolean/string coercions, insertion order and empty
hook keys created before a failed float conversion. Missing files return the
original empty result. No transcript, timing file or Moru state is written.

`OverheadStats` uses the builder-profile sum engine also used by Figma coverage.
Its move to `PythonSum` changes ownership, not arithmetic. Finite float means
accumulate exact binary rationals and divide before a single ties-to-even
binary64 rounding. Decimal rounding formats the binary value directly; it
never rounds a multiplied-by-100 intermediate. Integer statistics retain the
reference integer/float result types. Native aggregate integers and totals are
bounded by exact binary64 integer representation; percentage numerators have
the same bound after multiplication by 100. Unsupported or nonfinite results
decline the whole request before the Python caller uses any result.
Numeric requests are parsed directly from their original bytes by the lossless
JSON owner, preserving a large integer's type until the bounds check.

`NativeOverheadReport` validates each complete response before returning it.
Malformed responses or unsupported caller objects use the retained original
functions. Private requests inherit source/environment checks and bounded
transport, file size and output limits; descriptors, FIFOs, symlinks and
unstable reads are declined. No stream is consumed and replayed.

The direct CLI, file collection/window grammar, report serialization and
Markdown/output writers still need native ownership. Nonfinite statistics,
large integers, unsupported JSON/text shapes and direct Python callers also
remain in the ledger. This increment creates no completed inventory unit.
Current distributed bundle targets remain macOS ARM64 and Linux x86_64;
other-host acceptance is pending until a matching manual build actually runs.

Verification uses `test_native_overhead_report`, existing report/session tests,
Figma sum regression tests and the transported consumer smoke. Fixtures are
synthetic; no personal transcript, real provider or user timing file is used.
Local acceptance observed 9 new report tests, 39 related existing checks (two
builder-specific skips), 147 Rust tests and 156 transported checks. The tests
compare numeric types, signed zero, dictionary order and rendered Markdown as
well as values. Independent code review and executable negative cases repaired
malformed response overflow and premature input integer-to-float conversion.
