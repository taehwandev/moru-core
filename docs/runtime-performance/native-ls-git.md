---
keyflow_id: sys_runtime_native_ls_git
status: review
type: ai-generated
---

# Native ls and Git inspection extension

## Changed boundary

Extend the existing Claude/Codex pretool classifier, without executing the
requested shell command. Literal `ls` accepts no option or one of
`-l`, `-a`, `-la`, `-al`, `-lh`, `-lah`, `-alh`, followed by optional literal
paths. Existing quoting, Unicode, path resolution, local-executable, transcript,
environment and exact-source checks remain in force. Recursive listing,
multiple option groups, expansion, chains, redirection and uncertain paths
continue to the Python policy owner.

Git accepts exactly `remote -v`, and `status` with `--branch` before or after
one of `--short`, `--porcelain`, `--porcelain=v1`. Other argument combinations
retain Python handling. Fallback is not a new denial: the original policy
still decides the result. No policy mutation, cache, dependency or extra service
is introduced. Both changes extend existing inventory coverage.

## Verification and measurement scope

The focused Python checks compare both adapters against the actual Python
policy and run accepted forms without Python on PATH. Negative cases retain
Python handling for unsupported flags, missing/escaping paths, local executable
shadowing, redirection and command substitution. Rust grammar tests cover
accepted and adjacent unsupported forms. The transported consumer smoke adds
the three new command forms for both adapters, for 42 checks total.

The merged main base passed the 54 workflow/completion tests. The added
classifier behavior passed four focused Python tests and the Rust test suite;
the archive passed all 42 consumer checks from a fresh temporary installation.
Full regression and other-host jobs belong to the push-triggered CI run.
Local success does not establish those remote results.

The user confirmed that earlier comparisons already establish the migration
direction. This extension adds no accepted wall/CPU/RSS comparison or cost
calculation. The attempted measurement stopped before timing because of a
utility-path error; its ignored log and frozen source snapshots are retained.
The unneeded new benchmark mode was removed. There is no new numerical speed,
token-saving or whole-agent claim. Future measurements follow the
[selective policy](prd.md#behavior-acceptance-and-selective-measurement).

## Integration and distribution boundary

The six previously reviewed performance commits were rebased onto committed
main `59ff42bcf27d59187d5799b90cb7a14767dbe62a`. All six patches are identical
under `git range-diff`. The original tip is retained by the local
`taehwandev/perf/runtime-before-main-20261101` backup branch. The resulting
six-commit tip before this extension is
`5afc52dd860674e377f775c47964b464f458a3ef`.

The authorized delivery is an exact-commit fast-forward of local main followed
by a non-force push to origin/main. Preserve the main checkout's unrelated
uncommitted guide byte-for-byte. Keep the implementation, review and artifact
checks in the linked worktree. Read back both refs and the preserved file after
delivery. This document records the integration plan and local checks; the
closeout reports the actual delivered SHA and remote CI result.

The existing four-host workflow builds and tests portable archives. Consumers
need no Rust/Cargo installation for a matching bundle; Python remains required
for compatibility paths. This delivery does not create a tag or release and
does not replace the globally installed launcher.
