---
keyflow_id: sys_retrospective_learning_workflow
status: stable
type: human-reviewed-needed
---

# Retrospective Learning Decision Boundary

This document owns the separation between failure recovery and successful-task
skill learning. They share a desire to prevent repeated mistakes, but they do
not share a trigger, completion effect, or automation budget.

## Choose One Flow

| Event | Flow | Completion effect | Detailed reference |
| --- | --- | --- | --- |
| A required hook, gate, or finish check fails | Failure repair | Blocking | `failure-repair.md` |
| The user explicitly reports that a previously completed result was wrong and asks to correct that same result | Failure repair | Blocking | `failure-repair.md` |
| A tracked work route requires a closeout check | Short retrospective check | Required before finish | Entry point; `skill-feedback.md` only for a reusable gap |
| The check reveals a reusable gap in a skill actually used | Skill-document maintenance | Same-closeout follow-up blocks finish until terminal | `skill-feedback.md` |

Failure repair protects the current task. It diagnoses the failed checkpoint,
improves a durable enforcement surface, verifies the repair, and resumes once.
A user-confirmed wrong completion is failure evidence even when every earlier
gate said success: the completion decision itself is the failed checkpoint.
This trigger does not require two occurrences.

The closeout check first traces agreement through the delivered result using
the existing Q&A, ticket/plan, work artifacts and verification evidence, even on
success. It explains why the chain held or where it first diverged and why later
steps failed to catch it. Only then does it ask whether a used skill should
change. The check is required so a route cannot finish without that assessment. When
it finds a reusable gap, the same closeout runs observation, deterministic
curation, bounded review, staging, and verified canonical maintenance. The
runtime still keeps those authority boundaries separate: the agent authors the
skill-document change and the maintenance recorder verifies the changed target.
Successful work emits at most one content-free observation tied to a skill
actually used. No gap leaves the canonical document unchanged.

## Ordering

1. Run the task work, verification, and required review.
2. If one fails, or if the user explicitly corrects a previously completed
   result, stop and use failure repair. Do not also treat that failure as
   ordinary successful-task feedback.
3. Before finish, inspect the skills actually loaded and applied, then record
   `no_reusable_gap`, `reusable_gap`, or `no_skill_used` on the required
   `retrospective check` gate.
   Record the exact fields `skills_checked`, `outcome`, and `observation`.
   For `retrospective_contract: causal_v1`, also record `alignment_evidence`,
   `causal_assessment`, and `learning_decision` as defined in the entrypoint.
   Never derive a clean assessment from silence. Legacy unversioned manifests
   keep their previous contract; no migration or reconstructed history is needed.
   `observation` is an enum, not a free-form summary: pair
   `no_reusable_gap` or `no_skill_used` with `not_needed`, and pair
   `reusable_gap` with `recorded`. Put task-specific correction details in the
   gate evidence text rather than inventing another observation value.
4. When the outcome is `reusable_gap`, run the feedback hook immediately (passing
   `--draft-proposal` or `--draft-proposal-file` auto-stages the candidate in
   one step). Skip provably `confounded` environmental, network, or timeout noise
   (backed by an evidenced external error or passing rerun) as `no_reusable_gap`
   with `efficiency: unmeasured`, without waiving any failed gate checkpoint.
5. Write the bounded proposal, curate the current occurrence, and run bounded
   review in this closeout. `stage_patch` requires a usable draft and binds its
   digest.
6. In an active writable worktree, apply the canonical skill-document change
   directly under standing `local_write` self-evolution authority (do not ask
   the user for permission; never override `--read-only`/`analysis` or
   protected-checkout isolation), run fixed verification via `skill-maintenance`,
   and record `applied` or `rejected` before finish. Verified `skill-maintenance`
   automatically re-seals the active run's review attestation when no other file
   drifted. Finish refuses the current occurrence while any of these states is
   pending.

## User-Correction Boundary

Classify a follow-up as blocking failure repair only when the available
conversation context establishes all three facts:

1. the referenced result and its prior completion are established,
2. comparison with the agreed requirements establishes an unmet condition,
3. the current user request authorizes correcting that same result.

An optional improvement, an unrelated new request, a question without a
correction action, or a bare preference change remains an ordinary follow-up.
The runtime makes this contextual judgment from the discussion, agreed
decisions, task records and observed result. No particular completion phrase,
failure word or correction verb is necessary or sufficient. A terse follow-up
can rely on an established result; mentioning an error in a hypothetical
example proves no failure. Do not infer failure from multiple turns or retries.
For a terse runtime follow-up, the runtime adapter must keep the user's actual
correction verbatim in `--request` and pass the already-established target in
the separate bounded `--continuation-scope`. Moru Core must not concatenate prior
conversation prose into the current request or guess an earlier run from
whichever project run happens to be newest. Scope words provide target identity
only and grant no authority. Resolve the current action and authority from the
whole conversation; do not require the user to repeat already settled facts.

During active work, a mismatch found by the user, the agent or review is also
causal evidence. Correct it within current authority and preserve the reason in
the existing task records; do not wait for a wrong completion or self-retry.
When requirements legitimately evolve, retain the earlier baseline and the
authorized decision that superseded it, rather than labelling the earlier work
wrong. If evidence cannot distinguish evolution from lost agreement, mark the
uncertainty and resolve a material acceptance question before completion.

Once wrong completion is established, use blocking failure repair rather than
claiming ordinary successful closeout. `triage`, `ambiguity`, and read-only
`analysis` remain available for uncertain diagnosis. Natural-language intake
does not establish this boundary or authorize a repair route; the runtime's
bound scope and authority still govern executable work.

## Automation Boundary

- Required gates and failure repair remain fail-closed.
- Ordinary code and small-change routes retain one `retrospective check` at
  closeout. Stateless lookup and unchanged commit follow-ups add no learning
  cycle. Do not expand a no-gap check into a search for new work or a mandatory
  skill edit; use evidence already gathered during the task.
- Skill observation is a required same-closeout step when the retrospective
  outcome is `reusable_gap`; no gap remains a no-op for canonical documents.
- Observation hooks only append allowlisted content-free facts; they never
  decide recurrence, queue review directly, or edit canonical guidance.
- Curation is deterministic over structured identities and distinct opaque
  observation ids. It must not infer truth from prose, prompt text, keyword
  matches, or persuasive model output.
- A same-closeout curator queues review after the current opaque occurrence
  shares the exact `skill_id + signal` identity. It must not draft or apply a
  skill edit.
- New observations must use one schema-owned signal from
  `missing_rule`, `unclear_ownership`, `weak_verification`, `stale_guidance`,
  `missing_platform_guidance`, `ambiguous_decision`, or `execution_error`.
  Reject other values; do not merge signals by prose similarity.
- Historical observations created before the closed vocabulary remain
  immutable input. The curator may translate one only through the explicit
  versioned legacy table owned by the signal catalog. It must retain and count
  an unmapped record instead of dropping, rewriting, or similarity-merging it.
- Curation and retention enforce explicit caps for observations, review-ready,
  staged, and completed records. Terminal pruning also removes the matching
  passive observations so completed decisions cannot be re-queued.
- The reviewer is a separate bounded step and emits only `no_change` or
  `staged_patch`. Reviewer or token unavailability keeps the current closeout
  pending. Unrelated historical candidates remain non-blocking.
- A staged patch is not canonical guidance. Canonical writes happen only in the
  same closeout's bounded maintenance step with required verification and the
  applicable approval policy.
- `applied` is an observed state, not reviewer prose: it requires an actually
  changed canonical target linked to the staged promotion target and a zero
  exit status from an allowlisted verification kind.
- Project-local canonical writes are allowlisted only under
  `.agents/shared/llm-skills/<skill>/**` and
  `.agents/local/skills/<skill>/**`. Adapter paths such as `.codex/skills` and
  `.claude/skills`, and vendored runtime copies, are not maintenance targets.
- No observation, curation, or review hook may bypass canonical maintenance.
  Same-closeout automation requires the active agent to author the staged
  change, then the maintenance recorder accepts it only after live verification.
- Prefer a focused test, validator, or clearer decision rule over an
  ever-growing list of natural-language exceptions.

## Lesson Candidate Lifecycle

A failed finish queues a content-free lesson candidate under `lessons/inbox`,
keyed by its failure signature and carrying the opaque occurrence key of every
run that produced it. The candidate is a recurrence counter, not a repair.

- A candidate leaves the inbox only through a verified repair. A successful
  repair receipt promotes the candidates carrying that run's occurrence key to
  `lessons/promoted` with `promotion_status: repair_verified` and the receipt id.
  Nothing else retires a candidate: recording gate evidence until finish passes
  leaves the signature queued and it will recur.
- Promotion is scoped to the repairing run. Candidates from unrelated earlier
  runs stay queued, so one repair cannot silently clear another failure's
  history.
- A promoted record keeps its occurrence keys and count. A signature that
  returns after a repair resumes counting from that baseline instead of
  restarting, so an ineffective repair stays visible.
- Report a recurring signature rather than a bare candidate total. A count alone
  reads as bookkeeping, which lets a repeatedly unrepaired signature accompany a
  clean finish without contradiction.

## Source Ownership

This skill bundle is the canonical shared owner. Keep `AGENTS.md`, workflow
routes, hooks, and README files as thin consumers of this contract rather than
parallel policy owners. Repo-specific lessons stay in the target repo's local
instructions or source-of-truth docs.
