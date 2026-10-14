---
keyflow_id: sys_incremental_implementation
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# Incremental Implementation

Use when building, refactoring, or repairing non-trivial behavior. The goal is
to deliver one thin, verified slice at a time instead of creating broad
speculative scaffolding.

## Use When

- A task touches multiple files, modules, UI states, APIs, or storage surfaces.
- The implementation could grow into a large unreviewable diff.
- The contract is not stable enough for parallel writers.
- A feature needs both code and verification.

For a one-line mechanical edit, keep the change direct and verify the touched
surface.

## Inspect First

- Existing owner boundary and call sites.
- PRD/ARD or acceptance criteria when behavior is product-visible.
- Current tests and the nearest verification command.
- Change-size, code-structure, state, API, data, or platform cards that match
  the touched boundary.

## Decision Rule

Choose the next slice that proves the highest-risk useful behavior with the
least code. Do not expand to the next slice until the current slice has a
passing check or an explicit residual-risk note.

## Slice Patterns

- **Vertical slice**: one user or caller path from input to observable output.
- **Contract-first slice**: public type, API, route, or module contract plus
  the smallest fake or implementation proving callers can use it.
- **Risk-first slice**: the risky parser, permission rule, state transition,
  migration, or external adapter before polish.
- **Test-first slice**: a failing or missing regression check before changing
  behavior.
- **UI-state slice**: success/loading/error/empty state for one owner before
  broad visual polish.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "Scaffolding now will make later work faster." | Add only scaffolding used by the current verified slice. |
| "The rest is obvious." | Stop after the verified slice or write the next acceptance check first. |
| "This needs one big refactor." | Identify the smallest boundary that can be moved with equivalence evidence. |
| "Tests can wait until the feature is complete." | Add the nearest useful check before broadening the implementation. |

## Red Flags

- A diff adds many files before any behavior is exercised.
- UI, state, API, persistence, and release work land in the same unchecked step.
- A helper, package, or shared module has no caller contract yet.
- The agent starts parallel work while the shared contract is still moving.
- Verification is postponed because the slice is "not done yet".

## Do Not

- Do not create empty layers, generic helpers, feature folders, or managers for
  future use only.
- Do not batch unrelated refactor, formatting, generated files, dependencies,
  and behavior into one slice.
- Do not use commits as the only slicing mechanism. The reviewable boundary is
  the behavior, files, and verification, not merely the commit count.
- Do not continue adding behavior after the first slice fails verification.

## Stop If

- The acceptance criteria for the slice are unclear and local context cannot
  answer them.
- The slice crosses auth, data, release, migration, billing, or external state
  without a boundary plan.
- The nearest meaningful verification cannot run and the risk is too high to
  report as residual.

## Verification

For each slice, record:

- requested outcome
- owned files or boundary
- nearest check run
- what the check proved
- next slice or stop condition

Use `common/skills/verification-policy/SKILL.md` to broaden checks when the slice touches a
shared contract or high-risk boundary.

## Report

Report the completed slice, verification evidence, skipped broader checks, and
whether any remaining work is a new slice rather than hidden incomplete work.
