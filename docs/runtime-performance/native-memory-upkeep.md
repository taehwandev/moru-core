---
keyflow_id: sys_native_memory_upkeep
status: review
type: ai-generated
---

# Native memory upkeep kernels

This batch moves three related decisions into the pure `MemoryUpkeep` owner.
It continues unit 16; three kernels do not count as three completed units.

| Decision | Rust owns | Python retains |
| --- | --- | --- |
| Startup hints | Ordinary text normalization, exact body/scope groups, source groups, strict ISO date validation/comparison, expired and replacement counts | Status/profile admission, custom/exceptional normalization and date parsing, ordered notice text and shell quoting |
| Unfinished replacements | Ordered target lookup and sorted replacement indices | Original record metadata, reason text and report projection |
| Live report inputs | Status membership and stable ID sorting | Profile admission and original objects |

[Review-date kernels](native-memory-review.md) reuse live selection in a fused
request for strict report date buckets; exceptional calendar behavior stays local.

Startup body groups preserve `all` bridges and separate disjoint scopes without
fuzzy pair comparisons. Empty normalized bodies do not create duplicate hints;
empty normalized sources still group. Startup replacement membership includes
an empty string, while explicit unfinished findings ignore falsey replacement
links. Duplicate IDs and equal sort keys keep their original insertion order.

The typed adapter sends only required scalar fields and returns original records
or bounded count/index packets. Empty inputs start no native process. Custom
profiles retain the original Python algorithms and error order. Prepared
callback/date-only requests reuse normalized fields on decline; fused raw-text
requests prepare reference fields only after decline. Neither path repeats the
callbacks. A forced Python backend or missing binary bypasses native preparation.
No store writes, automatic
merges/retirement, model calls or authority changes are introduced.

## Strict startup dates

Date-only startup callers send review dates and today's date as ISO strings in
the existing count request (`upkeep-startup-dates`). The Rust owner reuses the
record calendar validator and computes all four counts atomically. This removes
per-record Python `fromisoformat`/`toordinal` calls without an extra process.
Unlike report-date buckets, startup expiry counts each duplicate-ID row using
its own date; a later duplicate never replaces an earlier row's startup date.

The optimization requires the original source calendar, a plain `date` today,
and the genuine built-in parser. Custom parsers retain `upkeep-startup` and its
ordinal contract. On a declined request or unsupported date grammar, Python
parses dates once and reuses the normalized fields for the reference counts.
Missing binaries bypass preparation; empty live inputs start no request.
Normalization still precedes date errors, and interpreter-specific extended
date formats retain their existing values or exceptions.

The startup-date tests observe C-level parser/ordinal calls, require the native
path, compare seeded calendar/scope counts with the reference, and exercise
decline, custom-parser, malformed-calendar and no-Python/Git protocol cases.
These are behavior checks; no timing improvement or Linux execution is claimed.

The follow-up passes 67 affected Python cases, including eight startup-date
cases, and 54 Rust memory tests. An initial temporary `git init` setup exceeded
its five-second limit; the affected 19-case module passed in isolation, and the
final 67-case suite passed after compilation was serialized. Fixture timeouts
were not raised. A later unrelated main update preserved the exact unit patch
and test hashes; broader bundle source bindings are refreshed separately.
The regenerated macOS ARM64 bundle passes 234 transported checks, including
strict-date success, empty, invalid-calendar and cross-schema protocol cases.
Actual local installation remains a separate source/binary-matching acceptance.

Pre-edit startup text and replacement report values/order were captured before
reference extraction. Verification covers seeded three-kernel parity, native-only
negative controls, date/Unicode/status boundaries, original opaque metadata,
malformed responses and read-only temporary-store CLI output. Pure transported
requests require neither Python nor Git. The macOS ARM64 batch passes 206
distinct Python cases: the initial 205-case suite plus the final 36 affected
cases after adding the unavailable-binary guard and its regression (19 upkeep
cases in total). The unchanged Rust kernel passes 43 memory tests, and the final
source-bound bundle passes 226 transported checks. Actual installed acceptance
uses a separate source/binary-matching check. Unit 16 stays partial; exact Linux
execution and performance measurements remain open. Push, hosted builds and
external deployment remain on hold.


## Fused startup text: local test acceptance

Ordinary source startup sends original body/source text in the existing
upkeep-startup-text request. The pure MemoryTerms owner applies the builder
Python Unicode lowercase contract, removes punctuation and collapses Python
whitespace before MemoryUpkeep groups/counts the records. Lowercase deliberately
differs from casefold; contextual Greek sigma is resolved before punctuation or
combining-mark removal. Build-time tables come from the existing builder
Unicode oracle; consumers do not generate tables or start Python for the
native operation. See the [CPython lowercase implementation](https://github.com/python/cpython/blob/v3.9.6/Objects/unicodeobject.c).

The new NativeMemoryStartup adapter only admits plain supported profiles,
sends required scalar fields and validates closed bounded counts. It performs
no text normalization or store IO. Custom normalizers, changed normalizer code
or punctuation rules and custom calendars keep the reference/custom path.
Unavailable or declined native transport runs the reference normalization once.
Empty live inputs start no request; original record objects remain unchanged.

Local verification passes 69 affected Python behavior cases, three ledger
cases, 58 Rust memory tests and 35 protocol checks on a copied native consumer,
including four new raw-text scenarios. The native consumer runs in a disposable
test home with Python, Git and compilers absent from PATH. Profiling observes
zero Python normalization/date-parser/ordinal calls and one existing request for
the ordinary path. Unicode/context, callback/code/regex overrides,
fallback/error priority, malformed packets and preserved record/store bytes are
covered. In-place code-override tests restore the function in a finally block;
Python 3.9 mock cleanup cannot delete the function's code descriptor.

The user approved local debug/test compilation only. These checks used the
debug profile and temporary test fixtures; no release profile, distribution
archive, hosted build or actual user installation was performed. Earlier
transported-bundle counts above cover previous increments, not this one. Exact
Linux and installed-runtime acceptance remain pending, no timing improvement
is claimed, and unit 16 remains partial.

## Startup record selection

An optional `statuses` array extends only `upkeep-startup-text`. Its closed
seven-field rows include status, and the Rust kernel selects records before
normalizing text, parsing dates or counting links. Every original input slot is
represented, including inactive rows. The adapter replaces inactive values with
null placeholders, so their bodies, malformed dates and arbitrary metadata never
enter the request. The existing three-key startup protocols retain six-field
rows and their original results.

Python retains compatibility admission and a live cardinality bound for the
response, plus the no-request path when no records are live. It no longer
constructs the selected record list for the calculation. This is not full
retirement of Python status checks or rendering. Unavailable or declined native
execution keeps the reference path; malformed counts use one submitted attempt
before reference normalization. Custom normalizers and calendars remain supported.

Local debug verification passed 87 Rust memory tests and 60 Python cases. A real
mixed-status request contains all input slots and produces the exact reference
notice once; removing the status opt-in triggers the reference-replay control.
Eight seeded 37-row corpora include active, pending, approved, retired and
case-mismatched statuses. Existing Unicode, date, custom-callback, empty-input and
temporary-store byte checks pass. Counts exceeding the live cardinality decline
even when the total input count is larger. The debug receipt binds 625 inputs.

The ledger also accounts for four Python sources introduced by the preceding
main change; they remain unmigrated. Unit 16 stays partial. No release build,
actual installation, exact Linux acceptance or performance claim is added.
