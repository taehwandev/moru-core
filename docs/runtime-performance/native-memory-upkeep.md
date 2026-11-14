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
| Startup hints | Exact body/scope groups, source groups, strict ISO date validation/comparison, expired and replacement counts | Status/profile admission, normalization, exceptional date parsing, ordered notice text and shell quoting |
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
profiles retain the original Python algorithms and error order. For an unavailable
or declining startup transport, the fallback reuses the already normalized text
and parsed date ordinals; it does not repeat those callbacks. A forced Python
backend or missing binary bypasses that preparation. No store writes, automatic
merges/retirement, model calls or authority changes are introduced.

## Strict startup dates

Ordinary startup notices send review dates and today's date as ISO strings in
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
