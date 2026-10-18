---
keyflow_id: bounded_loop_runs_prd
status: review
type: ai-generated
---

# Bounded Loop Runs

An agent with an authorized Moru task can opt into repeated, measured attempts
without losing the task's authority, accepted work, or stopping conditions.
This implements the loop discipline discussed with the user; it does not install
Pstack, launch models, schedule wakeups, commit, publish, or edit source itself.

## Acceptance

1. Enrollment requires the current session's exact active writable run. A read
   route, foreign owner, completed run or second live enrollment is refused.
2. Enrollment fixes owned files, verifier files, unittest selections, iteration
   and elapsed-time ceilings, and a model-call reservation ceiling. The runtime
   reserves calls before launching them; this is admission accounting, not a
   claim that Moru can meter calls made outside the protocol.
3. Each attempt records one bounded hypothesis, consumed reservations, actual
   verification results and optional measured value. Existing unittest execution
   supplies typed exit/count results with at least one genuinely passing test;
   skipped or expected-failure-only suites and agent-written gate prose are not proof.
4. A separate regression selection must pass before accepting any candidate.
   The goal selection alone decides success. For measured improvement, freeze a
   direction and minimum delta; accept only a better finite value and green
   regressions. The goal test expresses the final numerical target.
5. Inputs must stay unchanged while checks execute. Verifiers, HEAD, index and
   tracked/non-ignored files outside the owned scope must not drift from
   enrollment. No stale or manually claimed result may complete an attempt.
6. Rejected candidates remain visible. The controller refuses another attempt
   until the owned files match the last accepted checkpoint. It never uses
   reset, clean, automatic deletion or automatic commits to discard work.
7. Pausing, interruption and ordinary Moru resume preserve budgets and accepted
   fingerprints. A pending attempt is reconciled before new work. A terminal
   budget outcome is not success; no limit or goal silently resets.
8. Status remains inspectable after completion. Loop success never finishes the
   Moru task or bypasses its required tests, review, finish or publication checks.

## States And Verification

Ready, attempting, checking, evaluated, paused, succeeded, exhausted and cancelled are
explicit. Invalid inputs, missing measurements, changed files and lost ownership
refuse progress while preserving state and source. Temporary Git repositories
and subprocess tests cover success, rejection, restoration, budgets, stale
results, mutation during verification and permission denial. There is no UI.

## Sources And Corrections

Pstack's [autonomous run](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/autonomous-run.md)
and [hillclimb](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/hillclimb.md)
motivate fixed goals and one measured change at a time. Its
[session pickup](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/session-pickup.md)
does describe recovery; the supplied assessment's claim of no recovery procedure
is too broad. Moru adds machine-checked ownership and drift boundaries.
Skill counts and third-party security-scan claims are not requirements.

The [portable fork](https://github.com/michael-denyer/pstack-claude) confirms
runtime-specific wake mechanisms. No provider-specific wake API is assumed here.
Sources checked 2026-10-16. General app-verification generation, multi-model
panels and blinded harness evaluation are separate capabilities, not implicit
authority for this loop implementation.
