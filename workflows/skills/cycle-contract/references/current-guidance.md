---
keyflow_id: sys_cycle_contract_workflow
status: stable
type: human-reviewed-needed
---

# Cycle Contract Workflow

Use when a routed task produces durable work: code, docs, tests, workflow
policy, release artifacts, or product requirements. The goal is not to create
an endless autonomous loop. The goal is to make one useful cycle explicit
enough that another agent or human can verify whether it actually completed.

This card adapts the Loop Library idea of repeatable agent loops: define the
input scope, run one meaningful cycle, verify it with concrete checks, and stop
at a named condition instead of drifting into unbounded work.

## Required Contract

Before implementation, editing, release work, or workflow setup, record a
compact cycle contract:

```text
cycle_type: implementation | docs_sweep | refactor | bugfix | release | prd | workflow_setup | review_response
input_scope: <source of truth, user request, PRD/spec/ARD, issue, or local doc class>
allowed_changes: <files, docs, modules, behavior, or artifact classes that may change>
forbidden_changes: <unrelated files, public contracts, dependencies, migrations, deploys, or review-only work excluded>
acceptance_criteria: <what must be true when the cycle is complete>
verification: <tests, smoke checks, route validation, manual scenario, or explicit not-applicable reason>
stop_condition: <the exact condition that ends this cycle>
checkpoint: <handoff, commit readiness, review request, next cycle, or rollback point>
```

Keep values reusable and content-safe. Do not encode prompts, private task text,
ticket ids, branch names, customer names, secrets, file contents, logs, diffs,
or source snippets in the contract.

## Cycle Types

- `implementation`: turn an actionable request or accepted spec into a scoped
  code/docs/test change, verify the changed behavior, then hand off with the
  next recommended cycle.
- `bugfix`: reproduce or isolate enough to define the failing behavior, make
  the smallest fix, add or run a regression check, then stop at verified
  behavior or a stated blocker.
- `refactor`: establish a behavior baseline, make one meaningful structural
  improvement, prove equivalence, and stop at a checkpoint before the next
  refactor slice.
- `docs_sweep`: compare source-of-truth docs and linked docs, update only the
  stale or missing durable guidance, check links or route coverage, then stop.
- `release`: verify package, config, smoke, rollback, and release notes or
  handoff evidence. Do not hide deployment or credential decisions inside this
  cycle.
- `prd`: ask or research only blocker unknowns, produce requirements and
  acceptance criteria, and stop before architecture or implementation unless the
  user explicitly moves to that next cycle.
- `workflow_setup`: install or repair workflow mechanics, verify route/hook/gate
  behavior, and stop with recovery instructions for any runtime that still
  cannot be proven locally.
- `review_response`: consume known review findings, implement accepted fixes,
  verify those fixes, and stop. New review findings become a separate review or
  response cycle.

## Review Is Separate

Code review is its own cycle. A review cycle produces findings, risk calls, and
verification notes. It does not implement fixes unless the user explicitly asks
for review-response work.

Implementation cycles may prepare for review by keeping changes small, running
checks, and naming residual risk, but they should not claim a separate review
cycle has happened only because the agent looked at its own diff.

## Stop Conditions

Choose one stop condition before editing:

- Acceptance criteria satisfied and verification passed.
- A required blocker question, permission, source-of-truth doc, or environment
  dependency is missing.
- Verification fails twice for the same scoped reason and retrospective recovery
  is required.
- The next needed work is a different cycle type, such as review,
  review-response, release, PRD, or a new implementation slice.
- The change would cross the declared forbidden boundary.

When the stop condition is reached, stop the cycle and hand off. Do not expand
scope just because there is adjacent work.

## Verification

Cycle evidence must include the contract fields above and the check that proved
the stop condition. For routed Moru Core work, the finish-check evidence for
`cycle contract` must name cycle type, input/source scope, allowed or forbidden
change boundary, acceptance or verification method, stop condition, and next
cycle/checkpoint or handoff.
