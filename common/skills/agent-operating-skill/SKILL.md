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
   human prose on `writing`/`editorial`, started by you even if the route
   says `triage`); when bounded inspection leaves outcome shape, UX flow or incompatible prose genre open—or requires unapproved
   sibling-page expansion—align pre-`start` with findings, a concrete sketch or
   2–3-line sample, full scope and focused questions. Change only the authorized
   outcome; incidental findings grant no cleanup authority. In an active
   linked worktree, verified Moru Core defect/`reusable_gap` fixes (false-positive
   gate bugs: keep negative controls, note in report) carry standing `local_write`
   authority without asking. Unchanged pointers need no edit.
5. Stop after outcome/checks; extra checks need evidence.

## Live Session Continuity

On a follow-up, keep the active objective, authority and valid results. Answer
status questions briefly and take the next authorized action. A completed task
stays completed unless the user reopens it or new evidence changes the result.
Reuse passed checks while their relevant inputs and acceptance criteria still
match.
Recheck only the affected part when those inputs change, evidence is missing
or stale, or the user requests a fresh check. A required gate can reuse valid
evidence where its contract permits. Use automatic checkpoints for routine
progress and write resume state for interruption, changed scope or handoff.

While a tool runs or an answer is pending, continue independent authorized
work. Wait on the existing handle only when its result is needed to proceed.

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

The prompt hook delivers this once per session and on change; it grants no authority.

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

Parallel slices: one worktree and `start` each; when merged, remove it and
`git branch -d`.

## Execution Round Trips

Batch independent reads and ready gates. Start the next bounded action as soon
as its prerequisites pass. Surface blockers when they change the next action.
Keep dependent mutations and approvals sequential.

Resolved installation/procedural work may use a same-model `low` native worker
when benefit exceeds coordination cost per `references/runtime-collaboration.md`;
short commands stay inline. Hooks own mechanical admission/checks and print
fields; agents own scope, truthful evidence and next action. Do not duplicate
checks or read validators.

## Read

- `references/current-guidance.md` only for unresolved lifecycle/evidence rules:
  hook rejection, goal reuse, isolation setup, adapter contracts, read sizing or
  latency claims.
