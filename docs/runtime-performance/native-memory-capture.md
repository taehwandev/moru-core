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
computes remaining digests, writes the new record first and retires its predecessor. The
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

## Digest in the same validation request

A literal `digest: true` opts into a digest alongside the normalized scalar
values. MemoryRecord reuses MemoryJson's existing canonical JSON and SHA-256
implementation; it does not introduce another hashing algorithm or request.
The original eight-key request and three-key success result remain unchanged.
False, nonboolean or extra fields decline; malformed digest replies defer to
the reference without another capture request.

The caller opts in for ordinary captures without source or analysis metadata,
and only with canonical digest, input-validation, analysis-binding, JSON encoder
and hash-constructor bindings. Before using the returned digest it rechecks
those bindings after store admission. A custom callback changing hashing during
that interval therefore retains its original behavior. Metadata and customized
paths still use the original Python digest. Replacement and source-evidence
reads keep their existing work; this fuses only validation and digest calculation.

Local debug verification passed 93 Rust memory tests and 96 Python cases.
An independent captured Python digest and real Unicode/quoted-text/condition
captures match native output. Profiling observes zero Python digest calls in an
ordinary capture, with one real request; disabling fusion exposes the replay.
The actual capture CLI emits a record accepted by the existing reader. Malformed
digests, custom digest/hash/JSON handling, metadata and post-validation callback
changes retain their tested behavior. After the unrelated main review-tool
update, the rebuilt debug candidate binds 628 inputs. The Rust capture logic
is unchanged; rebuilding refreshes the compiled source contract.

All writes, permission checks, IDs/timestamps and retirement stay in Python.
Unit 16 remains partial; no release, installation, Linux or timing claim is added.

## Analysis binding in the same validation request

An optional closed `analysis` object contains question/context strings and is
exclusive with the digest opt-in. MemoryRecord composes the existing pure
MemoryAnalysis binding operation after scalar validation. The response adds its
binding or invalid marker without introducing another normalization algorithm.
The caller consumes that result after replacement/source checks, preserving
their precedence over analysis errors. Empty analysis keeps the existing path.

Canonical captures avoid a separate analysis-binding request and Python binding
replay. A malformed or declined fused response uses the original Python reference
without a second analysis request. Custom source functions, native binding/
request functions and their module globals retain the original owner path;
those bindings are rechecked after source callbacks. Original native bindings
are recorded by the analysis module itself, so customization before the first
capture import also declines fusion. Decoding copies the binding before Python
adds provenance, leaving the probe response unchanged.

Tracked source validation, EvidenceInputs capture, metadata digest, permissions,
IDs/timestamps and writes remain Python-owned. This combines two pure checks;
it does not reduce or bypass source evidence and store admission.

Local debug verification passed 96 Rust memory tests and 122 Python cases,
including 25 native capture cases. A real capture observes one validation
request and zero Python binding calls; disabling fusion restores the second
request. Actual CLI capture retains tracked-file blobs, input evidence and
reader-valid records. Error precedence, raw Unicode lengths, malformed replies,
custom and late callbacks, first-import customization and response immutability
pass. The test-only debug receipt binds 628 inputs. Unit 16 stays partial; no
release, installation, Linux or measured performance claim is added.
