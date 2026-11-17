---
keyflow_id: sys_native_memory_capture
status: review
type: ai-generated
---

# Native capture scalar validation

The private read-only `capture-inputs` operation delegates ordinary scalar
validation to MemoryRecord. Its closed request contains the Unicode version,
today, body, source, scope, review date and the two applicability conditions.
It reuses PythonText whitespace/printability and the existing scope/date owners.
Body and source are stripped before their 500/200-character limits; nonempty
stripped conditions retain the 160-character limit. Counts use Unicode code
points. The response contains normalized values/conditions or a bounded error
code, preserving body, source, scope, review-date and condition error order.

NativeMemoryCapture admits plain strings and decodes the closed response.
The source caller opts in only with its original calendar, scope regex,
applicability fields, condition limit and reference-function binding. Unsupported
profiles and malformed replies retain the Python reference. Invalid or extended
date spellings decline so the current interpreter supplies its own parser result
or exact exception. Native unavailability starts no request; submitted decline
falls back without another capture-validation request.

The probe reads no stores and grants no write permission. Python still checks
replacement/source/analysis evidence, admits the store, creates IDs/timestamps,
computes digests, writes the new record first and retires its predecessor. The
change does not migrate those responsibilities or alter the stored schema.

Local debug verification passed 90 Rust memory tests and 89 Python cases,
including eight capture scenarios. A real native request avoids the Python
validation reference; disabling native validation triggers the replay control.
Boundary lengths, Unicode whitespace, nonprintable text, exact error precedence,
custom profiles, malformed replies and interpreter-specific dates retain their
observed behavior. Temporary-store capture/replacement preserves valid digests
and retirement order; invalid input and denied-store scenarios create no record.
The final debug receipt binds 627 runtime inputs. Existing record-read,
applicability, analysis and migration-ledger checks pass too.

This is local source/debug acceptance only. Unit 16 remains partial; release,
installation, exact Linux execution and performance measurements remain separate.
