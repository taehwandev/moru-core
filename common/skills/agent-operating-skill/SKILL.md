---
name: agent-operating-skill
description: "Core operating contract: need-driven reading, ownership, and verification."
keyflow_id: sys_common_agent_operating_skill_md_skill
status: stable
type: ai-generated
---

# Agent Operating Skill

## Need-Driven Reading Contract

1. Keep outcome, target and authority; no unrequested redesign. Read instructions,
   required_docs (in full, not a range) and safety/check dependencies. Resolve
   isolation/branch before the first edit, not at commit/PR; reuse a bound worktree.
2. Start unresolved in-scope decisions at the owner/nearest test and adjacent
   sections/pages sharing the same thesis or state flow. Expand for
   missing/conflicting evidence, applicable rules or failures. Empty searches
   need a new lead.
3. Optional reads/tools must answer a decision. Reuse unchanged reads and
   compaction takeaways; read only new/changed/lost guidance. Deduplicate paths.
   Links, spare budget, catalogs, tools, platform names and graph neighbors
   select nothing alone. Stop at the answering entrypoint; report excess
   selection, never waive it.
4. Judge readiness from epistemic state, never prompt keywords: execute settled
   work directly (including coupled in-scope consistency fixes, and Draft-First
   human prose on `writing`/`editorial`); when bounded inspection leaves outcome
   shape, UX flow or incompatible prose genre open—or requires unapproved
   sibling-page expansion—align pre-`start` with findings, a concrete sketch or
   2–3-line sample, full scope and focused questions. Change only the authorized
   outcome; incidental findings grant no cleanup authority. In an active
   writable worktree, canonical skill/rule updates for a verified reusable_gap
   or failure-repair are pre-authorized local_write edits: apply and verify
   without asking. Existing pointers need no edit when they already load the
   changed source.
5. Stop after outcome/checks; extra checks need evidence.

## Live Session Continuity

Status questions, impatience and procedure complaints retain active outcome and
passed evidence. Answer briefly and continue the next missing authorized action;
do not reopen intake, start an audit/retrospective or repair the workflow unless
requested or a concrete failure requires it. Remaining gates are work to close,
not a reason to repeat passed tests or review. Automatic hook checkpoints need
no manual checkpoint; write semantic resume state only for interruption, changed
scope or handoff.

Before a final response, reconcile the full user-requested scope against the
actual result. Continue any authorized, independent work that remains; a passing
hook, completed subset, user question, or pending decision on one item does not
complete the rest. Distinguish uninvestigated work from a verified blocker and
report partial results as partial. Retain earlier authorization unless changed or
revoked; do not narrow the original scope to the last approved subset.

With native support, map multiple outcomes to stable IDs, owners, observing
gates and artifacts in optional `work.requirements`. Keep IDs across action
continuations; advance revisions on change. See
`docs/runtime-performance/native-completion-evidence.md`.
Coverage checks mapped files/gates, not omitted requirements or semantic truth.
Judge outcomes against actual observing results; coverage grants no authority.

The prompt hook delivers this section once per session and on change. It starts
no task, invalidates no passed check and grants no authority; a completed task
stays completed.

## Proportionate Execution

Choose the smallest route covering effect, owner and risk. Content publication
needs external-write authority, safety checks and readback, not unrelated code
tests/builds. Use workspace tools (`read_file`, `write_file`, `edit_file`,
`run_command`) to complete authorized in-scope work from repo evidence; preserve
safety refusals, permission boundaries, and stop conditions.

Prepare repo records before review/finish; later ids, URLs and times belong in
operational evidence unless tracked records are required. A receipt alone never
justifies another start/review/finish. Never create a journal, dummy diff, test,
worktree move or second task just to feed a gate. Report a manifest conflict; do
not fake a pass.

Parallel slices of one request each get their own linked worktree and their own
`start --project <worktree>`; a session's run in one checkout never authorizes
or blocks writes in a sibling. After a slice is merged, remove its clean worktree
from the main checkout and delete its branch with `git branch -d`, never `-D`.

## Execution Round Trips

Batch bounded reads/ready gates; inspect each result and require success before
dependencies. Keep mutations/approvals sequential. Return on decisions,
surprises, failures or pending handles; never hide failed prerequisites. Wait on
handles; no relaunch, short-polling or idle sleeps. Silence is no answer.

Resolved installation/procedural work may use a same-model `low` native worker
when benefit exceeds coordination cost per `references/runtime-collaboration.md`;
short commands stay inline. Hooks own mechanical admission/checks and print
fields; agents own scope, truthful evidence and next action. Do not duplicate
checks or read validators.

## Read

- `references/current-guidance.md` only for unresolved lifecycle/evidence rules:
  hook rejection, goal reuse, isolation setup, adapter contracts, read sizing or
  latency claims.
