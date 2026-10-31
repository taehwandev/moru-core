---
keyflow_id: sys_operating_request_continuation
status: stable
type: ai-generated
---

# Request And Continuation Safety Details

Read only the section needed for an in-scope decision named by
[AGENTS.md](../../../../AGENTS.md); this is not another startup reading list.
Paths in code spans are relative to <MORU_ROOT>. Current user authority and
project instructions prevail.

## Request And Continuation Safety

Separate work identity, action authority, and verification validity. The runtime
judges whether a follow-up belongs to the same requested outcome; neither its
wording nor a route name decides this. Keep an unchanged active action. When a
new action requires admission, use `start --continue-from <previous run id>`:
the action retains the original work id and immutable predecessor evidence,
while its current scope and authority are independently checked. Omit this
option for unrelated work. Cancelled or foreign-session work is not inherited.

For matching verification scope, toolchain, retained artifacts and external
inputs, supply one bounded `--reuse-inputs` attestation with that start. Valid
local gates carry automatically; act on the returned remaining gates rather
than reconstructing passed records. Unknown or changed inputs omit the
attestation and retain history without passing gates. This never transfers
approval, current external results, review, or completion. Do not invent new
phrase-specific continuation exceptions.

Local gate records may declare `input_paths` only when the check is independent
of commit metadata and the complete file dependency set is known. An empty
list covers all non-ignored project files; explicit paths cover exactly those
files. Rules are always covered. Content changes invalidate the dependent
record; committing identical contents does not. Omit this optional field for
revision-sensitive or uncertain checks. Ignored artifacts and environment
remain part of the runtime's input attestation, never inferred from Git bytes.

Keep the user's requested outcome across follow-ups. Before asking a question,
reuse confirmed targets, constraints and acceptance criteria from the current
conversation, then inspect bounded evidence for facts the agent can determine.
Missing agent-generated intake evidence is not a missing user requirement.
`prepare_intent` and `resolve_context` are advisory preparation states, never
work authorization; they do not waive an envelope, risk checks or fresh approval.
Ask only for a remaining material ambiguity, conflicting instruction or missing
authority. Do not ask the user to repeat a settled requirement or approve the
same authorized action again. Current scope changes override prior context.

The runtime owns contextual intent, sequence, scope and authority judgment;
Moru checks its bound declaration and the proposed action's safety, not whether
the user's wording matches a phrase recognizer. Separate authority to act from
how fully the intended result is shaped, judging from epistemic state after
bounded inspection rather than prompt keywords or grammatical mood:

- **Settled target and outcome (`request:<quote>`, `conversation:<quote>`, `repo:<path[:line]>`)**:
  When every user-visible choice is backed by a verbatim `--request` quote,
  confirmed `--continuation-scope` exchange, or existing repository file/line
  (for example, user-supplied exact wording, a typo or fact fix, an
  already-approved sample, or a specified thesis update where directly coupled
  in-scope passages on the same page can be reconciled in the same pass), an
  authorized execution request is actionable when first made, including ordered
  work: perform the authorized steps in order rather than treating an
  acknowledgement or plan as completion. Do not require another confirmation
  merely because the agent announced its plan.
- **Unshaped design, UX flow, or authorial prose/thesis (`--open-choice` / `assumed:<choice>`)**:
  Do not mistake an agent-invented plausible completion for a settled
  requirement. Even when the user authorizes edits or uses imperative phrasing,
  if bounded inspection (covering the named target, adjacent sections on the
  same page/screen, and sibling pages or coupled flows that repeat the same
  premise) leaves a user-visible design, UX flow, or voice/thesis choice
  `assumed`—or shows that reconciling a contradiction would require expanding
  edits to a separate sibling page or surface outside the authorized target—do
  not auto-fill or start a writable route (`start` rejects writable runs with
  `--open-choice` or `assumed:` sources, and rejects fabricated `request:`
  quotes not present in `--request`). When no tracked run is active yet, respond
  statelessly before `start` (or start read-only `triage`/`ambiguity`) with:
  (1) what bounded inspection found, including coupled adjacent sections or
  sibling pages, (2) a concrete design sketch or 2–3-line copy sample with the
  full coherent edit scope, and (3) the focused Grill-Me decision questions that
  materially change the result. Once aligned, pass the user's answer in
  `--continuation-scope` with `--decision-source conversation:<quote>` and
  `--target-summary`, and reuse that visible exchange as `alignment brief`
  evidence without re-asking settled questions. If an open decision surfaces
  inside an already-active tracked run (`triage`, `ambiguity`, or a work route),
  retain that run and use its `alignment brief` or blocker-question checkpoint.

Planning-only requests remain planning-only. Never infer approval from
silence or extend permission to a deferred, prohibited or unrelated action.
Before ending an execution turn, continue the next authorized step unless the
outcome is complete or a concrete blocker, required user decision, approval
boundary or interruption prevents it. In that case report actual partial work
and what remains; do not end with only a promise. This is an agent execution
responsibility, not a new classifier, gate, receipt or Stop auto-resume rule.

For an authorized correction, continue into the correction rather than ending
with an apology, explanation of what should have happened, or another offer to
do the same work. Check the requested observable outcome, not just test totals:
reproduce the reported case before a fix and verify it afterward. When intake
or routing changes, include the actual follow-up wording and prior scope in
tests, not only a preselected route. Preserve negative authority and ambiguity
controls. Report any unmet requirement explicitly; passing unrelated tests or
completing gates is not proof the requested result works. This adds no new gate
or mandatory document read.

For terse follow-ups, keep `--request` equal to the user's current words and
put bounded prior target context in `--continuation-scope`. The fingerprint
must cover both plus classification flags exactly. Continuation scope never
opens a work route or authorizes mutation. `--request-classified` is only for
a delegated worker holding a ready, valid capsule bound to the same intake.

When a tracked run is already active, evidence that still says the request is
vague, direct-question-first, ambiguous, unresolved, or blocker-open stays on
`triage` or `ambiguity` rather than opening a writable work route. Weak markers
such as “classified”, “done”, or generic “clarified” do not prove scope
resolution.

Every route whose minimum effect is `read` is intrinsically non-mutating.
Before a writing action, start a matching writable route with current scope
and authority; a higher declared or tool effect does not upgrade a read route's
frozen gate manifest. Finish rejects workspace drift on all read-floor routes,
including legacy evidence without an explicit read-only flag. `start --read-only`
on another route makes the same whole-run claim. Do not bypass VibeGuard.
`retrospective` has a `local_write` floor because its existing repair and
same-closeout maintenance contract includes canonical document edits. Use
`analysis` for reflection without edits; an explicit `--read-only` claim still
prevents writes even on `retrospective`.

For merged-branch and worktree removal, select `cleanup`, not `task` or
`code-simplify`. For a terse follow-up such as "정리도해줘", resolve the exact
Git targets from the current conversation before selecting `cleanup`; the bare
phrase or continuation scope alone grants no deletion authority. Mixed code
changes and cleanup are separate action scopes, not a shortcut into cleanup.
The Claude PreToolUse adapter rejects mutating tools for an active read-only
run before worktree-entry waivers; read-only commands retain their fast path
and workflow start remains available for a legitimate route transition. This
adapter does not imply native pre-tool enforcement in other runtimes.

Compatibility `start --command analysis` without existing evidence validates its
read-only intake and returns stateless guidance. Explicit legacy evidence retains
its original lifecycle. Newly routed work carries lifecycle version 2: the Stop
boundary retains unknown or blocked work as `blocked` or `interrupted` without
demanding another model turn. A bound writable run with explicitly recorded
executable `remaining_work` may receive one continuation per turn. User stops,
pending approvals, global waits and unresolved operations prevent it. A blocker
on one item does not erase separately recorded executable work. Finish rejects
recorded remaining outcomes or blockers even when every route gate passed.
An admitted writable run carrying only the runtime's default workflow label
also requires one scope-reconciliation pass; a pending finish keeps that run
active rather than recording a failed check or a completion receipt.
This checks declared scope, not the semantic truth of an unrecorded requirement.
A run that records no action is not evidence the work was
skipped: the agent may be waiting on a question or declined approval, or may have
acted without recording it, so Stop never forces a resume on that basis. These
outcomes are resumable, never completion, verification, or commit readiness.
Preserve partial changes and unresolved effects; revalidate ownership, scope, and
authority before resuming. Never reinterpret an unknown lifecycle version as a
legacy run.
