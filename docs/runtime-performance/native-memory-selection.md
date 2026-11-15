---
keyflow_id: sys_native_memory_selection
status: review
type: ai-generated
---

# Native analysis recall selection

Analysis reuse previously requested context-free recall ranking and exact
analysis candidate filtering separately. The ordinary path now reuses
MemoryRecall and MemoryAnalysis in one private `analysis-recall` request.
It maps ranked candidate positions back to original input indices; Python
returns the original record objects, including duplicate-ID instances.

The fusion selects only. Existing workspace-input capture, sequential source
checks, compatible JSON rendering and output budgets retain their original
ordering and authority. Empty selections never capture workspace inputs.
Unsupported records or custom callbacks keep the legacy path. A declined
attempt uses the pure selection references without another native request.

Local macOS ARM64 debug verification passed 95 distinct Python cases: the
initial 94-case suite plus the final 12 affected cases after adding an
availability-before-preparation guard (11 selection cases and one existing
real-store CLI case). It also passed 67 Rust memory tests, 43 empty-PATH
transported checks and 24 complete analysis-recall scenarios against immutable
source revision `7ef6f907`. The original-source comparison checks output and
source-check order under varied freshness and output budgets. Observing tests
require one selection request and zero Python ranking/filter calls; a disabled
native path supplies the negative control. Missing native availability skips
record preparation before taking the legacy path.

AGY received only immutable public reference functions. Its initial invocation
failed during process cleanup. A scoped session listing recovered the original
session, and canonical history loading recovered six reference findings without
resending the prompt. The lead checked those findings against the code and
tests. Ranked original indices, duplicate multiplicity, global replacement
tombstones and no-candidate/freshness ordering were retained. Examples treating
an `all`-scope record as a final analysis candidate were rejected: final
analysis matching requires the exact requested scope.

The recovered transport status remains `needs_inspection`; history is reference
evidence, not a fresh `end_turn`, execution proof or unpublished-patch approval.
The temporary non-Git observation workspace cannot attest a write-floor Git
diff check; that separate verification-run limitation changes no source or
product-test result. No Git repository was initialized to satisfy it.

Unit 16 remains partial. No complete migration, timing, release build/archive,
installed-runtime or Linux acceptance is claimed. See
[the migration contract](full-migration.md).
