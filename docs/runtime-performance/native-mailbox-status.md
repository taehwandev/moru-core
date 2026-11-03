---
keyflow_id: sys_runtime_native_mailbox_status
status: review
type: ai-generated
---

# Native mailbox status for empty inboxes

The generated auto launcher now admits `agent-mailbox` to native ingress.
Supported `status` calls with an explicit runtime prove that both canonical
inboxes contain no JSON entries, then count existing acknowledgements without
starting Python. This upgrades the existing mailbox CLI inventory unit 6 from
an import optimization to a partial native path; it adds no inventory unit.

## Behavior and ownership

`mailbox_status_process.rs` owns the closed status grammar, project/state
selection and exact text/JSON output. `mailbox_status_state.rs` owns read-only
legacy/reference traversal. Reuse the source/environment guard, filesystem
resolver and the existing Git-backed repository identity helper also used by
work cards. Linked worktrees share reference counts and retain their own
project-local legacy counts. Missing Git retains Python's project-path identity.

Accept an explicit `claude`, `codex`, `agy` or `antigravity` runtime, normalizing
`agy` to `antigravity`. Optional project selection uses the explicit expanded
directory or the nearest repository from cwd. Supported options may be ordered
freely; duplicate flags, alternate grammar and implicit runtime/session inference
retain Python.

Add acknowledgement counts from project-local `runs/<id>/acked/<runtime>` and
repository-shared `acked/<runtime>`. Preserve the 64-run and 128-JSON-entry
limits, including the aggregate legacy acknowledgement limit. Count the same
suffix-matching entries as Python: acknowledgement bodies are not parsed, and
an entry named `directory.json` counts too. Unrelated suffixes, other runtimes,
leases and historical rejection/task records do not affect this status path.

Any inbox JSON entry delegates to Python before output, including valid,
expired, malformed or directory-shaped entries. Python still owns packet
validation, rejected/expired/pending classification, send, receive and delivery.
Symlinks, scan limits, invalid runs, unavailable filesystem state, source drift
and unusual environment inputs also replay Python. Do not turn uncertainty or
an error into a successful empty status. Relative or tilde-prefixed state-home
overrides retain the shared guard's existing Python fallback.

Status creates no mailbox, lock, receipt or directory, consumes/quarantines no
message and updates no guidance. It remains a read-only observation rather than
a transactional delivery claim; the Python status reader also takes no lock.
Forced-Python rollback, missing-native fallback, stdio and soft-fail behavior
remain with the existing launcher contract. No crate, service, daemon, model
call or installer schema is added.

## Verification and delivery

All 30 locked offline Rust tests pass. The focused status, stable-launcher,
mailbox/store/reference and repository-identity suites cover 70 distinct Python
tests. The initial command passed 69 and exposed two subcases in one new test
that expected native execution for relative/tilde state-home overrides. Those
overrides deliberately fail the unchanged shared native environment guard.
Correct the test to require Python replay and the same count, then rerun that
one selector: it passes. Reuse the unchanged 69 results without a full rerun or
production guard change; retain the original failure log.

Checks cover exact text/JSON and exit parity through generated ingress, both
stores/runtime isolation, linked/non-Git and missing-Git identity, explicit/
default project selection, state-home fallback, suffix rules, pending/expired/
invalid packet replay, symlinks and exact scan limits. Fixture bytes and paths
remain unchanged across status. Python-free PATH proves supported native calls
actually run and unsupported calls really replay rather than hiding errors.

A fresh archive transported to an isolated source root/home passes 61 checks.
Four new consumer cases compare positive acknowledgement counts against actual
Python for text and JSON, including `agy` normalization, with Git alone on native
PATH. Existing consumer checks remain intact. Build/pack, formatting and diff
checks pass. The four-host CI selector includes the new suite; no remote run or
other-host result is attested here.

No latency, CPU/RSS or cost experiment is repeated and no new numerical speed
claim is made. Source and report remain on the local performance branch for
the next authorized integration step. Main integration, remote publication,
release and global activation remain separate actions; other-host CI results
need their own evidence.
