---
keyflow_id: sys_doubt_driven_development
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# Doubt-Driven Development

Use for high-risk or non-obvious decisions where a confident first answer can
hide product, architecture, security, data, reliability, cost, or release risk.

The goal is to challenge the claims that matter before they become code,
documentation, release notes, or a handoff.

## Use When

- The task changes architecture, permissions, data durability, billing, release,
  migration, external state, security, privacy, or observability.
- The solution relies on an assumption that repo context cannot prove.
- A side-effect audit finds a possible meaning or policy change.
- A review says "probably fine" but lacks evidence.
- Multiple reasonable designs exist and the tradeoff changes verification.

For small mechanical edits, do not add this ceremony unless the edit touches a
risky boundary.

## Inspect First

- User request, PRD/ARD, issue, design note, or local source of truth.
- Existing code boundaries, tests, and call sites.
- Verification already run and gaps already known.
- Relevant platform, security, release, data, or product-pattern cards.

## Decision Rule

Use a doubt pass when the cost of a wrong assumption is higher than the cost of
challenging it. The pass must end with one of:

- proceed with evidence;
- narrow the scope;
- ask one blocker question;
- route to a specialist review; or
- stop until the missing source exists.

## Process

1. **Claim**: write the key implementation or review claim in one sentence.
2. **Extract**: list the assumptions that must be true for the claim to hold.
3. **Doubt**: attack the weakest assumption with repo evidence, tests, source
   docs, or a specialist lens.
4. **Reconcile**: change the plan, add verification, or explicitly accept a
   residual risk.
5. **Stop**: if the assumption cannot be verified and can change behavior,
   safety, cost, release, or data handling, stop and ask.

Use a subagent or independent reviewer only when the scope, raw artifacts, and
forbidden edits are clear. Pass the artifact and task, not the expected answer.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "The plan is simple." | Identify whether the risk is simple too; if not, run the doubt pass. |
| "Tests passed." | Check whether the tests cover the risky assumption. |
| "A reviewer would catch this later." | Add the reviewer lens before implementation or handoff when risk is high. |
| "We can fix it after release." | Require a rollback, forward-fix, or monitoring path before accepting that risk. |

## Red Flags

- A major decision is justified only by confidence or convenience.
- The plan changes data, auth, billing, release, or migration behavior without a
  named failure mode.
- A side-effect candidate is noticed but not resolved before editing.
- Verification proves compilation but not the risky assumption.
- A subagent is asked to validate a conclusion instead of inspecting raw
  artifacts independently.

## Do Not

- Do not use doubt-driven review to stall clear low-risk work.
- Do not ask broad open-ended questions when local evidence can answer the
  assumption.
- Do not leak the intended fix to an independent validation agent unless the
  validation explicitly requires it.
- Do not average conflicting reviews; name the tradeoff and choose a path.
- Do not report a doubt pass as complete when the blocking assumption remains
  unresolved.

## Stop If

- The unresolved assumption can change security, data loss, billing, release,
  migration, external state, or user-visible acceptance criteria.
- Independent review finds a blocker and no owner accepts the risk.
- The required source of truth is private, missing, or contradictory.

## Verification

Doubt-driven work is verified by a short record of the claim, weakest
assumption, evidence checked, decision, and added verification or residual risk.

For code changes, the normal route tests still apply; the doubt pass is not a
substitute for tests.

## Report

Report only the useful result: the challenged assumption, the plan change or
accepted risk, and the verification that now covers it.
