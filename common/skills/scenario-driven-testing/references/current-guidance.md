---
keyflow_id: sys_scenario_driven_testing
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# Scenario-Driven Testing

Use this before writing or reviewing test code. Tests should prove the workflow a
user, operator, API caller, or downstream component depends on, not only that a
single data shape was accepted.

This card complements `common/skills/testing/SKILL.md` and `common/skills/verification-policy/SKILL.md`.
Open all three when the task creates, rewrites, or meaningfully reviews tests.

## Use When

- A task asks for tests, regression coverage, QA scenarios, UI flow coverage, or
  test strategy.
- A behavior change needs success, failure, exception, retry, empty, permission,
  loading, validation, or recovery evidence.
- A UI, ViewModel, reducer, store, hook, API route, command, workflow, or adapter
  reacts to user or caller action.
- A test currently checks only "given data A, returns B" but the product risk is
  actually in a sequence of actions, responses, and visible outcomes.

## Decision Rule

Start every non-trivial test from a scenario statement:

```text
Given <actor/context/precondition>
When <user or caller action>
And <system/API/platform response or state transition>
Then <observable success, failure, exception, or recovery result>
```

If the test cannot name the actor, action, response condition, and observable
outcome, it is not yet a scenario test. Split pure policy tests from workflow
tests when that makes the behavior clearer, but do not replace workflow evidence
with isolated data assertions when the risk crosses UI, state, API, persistence,
permission, or platform boundaries.

Prefer user-observable assertions: visible text, role, label, focus,
navigation, emitted command, saved state, API response, persisted record, retry
decision, or error state. Use implementation details only when the tested
boundary is itself an implementation contract.

## Scenario Frame

For each scenario, define:

| Field | What to write |
| --- | --- |
| Actor | user role, API caller, operator, background worker, or downstream consumer |
| Goal | the intent the actor is trying to complete |
| Entry point | screen, command, API route, workflow step, event, or adapter method |
| Preconditions | auth, permissions, existing records, flags, clock, network, cache, or device state |
| Action | click, type, submit, navigate, call, retry, cancel, refresh, or background trigger |
| Response condition | success payload, validation error, server failure, timeout, empty data, conflict, stale state, or permission denial |
| Expected outcome | visible UI, state/effect, returned value, persisted change, emitted event, retry/rollback, or user-facing error |
| Evidence | test command, fixture/fake used, and what boundary the test proves |

## Scenario Matrix

Cover the smallest matrix that can fail for the changed behavior:

| Scenario type | Required question |
| --- | --- |
| Happy path | When the user performs the intended action and the system succeeds, what visible or persisted result proves completion? |
| Validation failure | When the user input is missing, malformed, duplicated, too small, too large, stale, or unavailable, what blocks progress and what stays unchanged? |
| API or service failure | When the response is an error, conflict, unavailable service, or malformed payload, what error state, retry option, rollback, or preserved input appears? |
| Timeout or cancellation | When the action is cancelled, slow, interrupted, or retried, what loading, disabled, idempotency, or cleanup behavior is expected? |
| Empty or first-run state | When no records, no permission, no cache, or no prior setup exists, what default path is shown? |
| Permission or auth boundary | When the actor is denied, expired, revoked, cross-tenant, or partially authorized, what path is blocked and what data remains hidden? |
| Recovery | After failure, when the actor retries, edits input, refreshes, goes back, or dismisses an error, what returns to a usable state? |
| Regression | Which previously broken scenario is now impossible to miss? |

Do not force every row into every unit test. Use the matrix to choose the
nearest reliable level: unit for pure policy, state test for transitions,
component/UI test for visible behavior, contract/integration test for API and
persistence boundaries, and E2E only for high-value cross-boundary paths.

## UI Flow Tests

When a test touches UI:

- Drive the flow through user actions rather than directly mutating internal
  state.
- Assert on what a user can perceive or what the UI contract emits: role, label,
  visible text, disabled/loading state, focus, navigation, persisted output, or
  command/event sent to the next boundary.
- Include the response variant that matters for the behavior: success, loading,
  empty, validation error, server/network failure, permission denial, timeout,
  or retry.
- Keep a11y and interaction selectors stable: prefer role, label, text, and
  semantic names over brittle DOM/class/test-id assertions unless the test id is
  the repo's explicit testing contract.
- For responsive or visual risk, pair the scenario test with screenshot,
  geometry, or manual browser evidence from `common/skills/ui-visual-verification/SKILL.md`
  or `common/skills/browser-runtime-testing/SKILL.md`.

## API And State Tests

When a test touches API, state, or workflow logic:

- Name the caller action and downstream response condition, even if the test is
  a unit test.
- Test transitions, not only final values: action -> loading/effect -> response
  -> success/failure/recovery state.
- Assert compatibility at the boundary that can break: request shape, response
  shape, serialization, persistence, cache invalidation, idempotency, retry, or
  rollback.
- Use fakes/builders that make the scenario obvious. Avoid copied production
  payloads or fixture blobs where the behavior under test is hard to see.

## Example Shape

Use this shape as a starting point, adapting names to the local test framework:

```text
Scenario: user submits a form and the save API fails
Given an authenticated user is on the edit screen with valid existing data
When the user changes the required field and submits
And the save API returns a retryable server error
Then the screen keeps the edited input
And shows a retryable error message
And does not navigate away or mark the item saved
And a retry action can resubmit the same intent
```

The automated test can still be Arrange/Act/Assert internally. The scenario
language is the design aid that keeps the test tied to user intent and response
handling.

## Common Rationalizations

| Rationalization | Required response |
| --- | --- |
| "This is just a mapper test." | If the mapper feeds a user-visible or API boundary, include missing, invalid, stale, duplicate, and unavailable cases that the caller can observe. |
| "The happy path proves the flow works." | Add the closest failure or recovery scenario for the boundary that changed. |
| "The UI is hard to test." | Test the state owner and one visible interaction path, then record manual/browser evidence for the UI gap. |
| "Mocks make it simpler." | Mock only external boundaries; keep the workflow under test real enough that the product rule can fail. |
| "E2E will cover it later." | Add the smallest scenario test now; reserve E2E for cross-boundary paths that smaller tests cannot see. |

## Red Flags

- The test name describes data only, not actor intent or behavior.
- The test never performs the user/caller action that triggers the behavior.
- Success is covered but validation, failure, empty, permission, timeout, or
  recovery behavior is absent for the changed boundary.
- The assertion only checks that a mock was called, without proving the
  user-visible, API-visible, persisted, or emitted outcome.
- The test bypasses the state owner, reducer, hook, ViewModel, command, or route
  that production uses.
- Broad snapshots hide the scenario instead of explaining the expected outcome.
- A manual QA note names "tested locally" but not scenario, environment, action,
  expected result, and observed result.

## Do Not

- Do not write tests that only assert raw input/output data when the risk is a
  user flow, state transition, API boundary, permission path, or recovery path.
- Do not infer scenario coverage from typecheck, build, lint, or snapshot
  updates.
- Do not weaken assertions to make flaky workflow tests pass; isolate the
  unstable boundary first.
- Do not encode private production data, prompts, secrets, account names, branch
  names, file paths, or task text in scenario names or fixtures.
- Do not make one massive E2E test responsible for every branch when focused
  unit/state/component/contract tests can prove the branches more clearly.

## Stop If

- The scenario depends on a product decision, permission rule, data-loss rule,
  billing rule, migration behavior, or user-facing error copy that is not in the
  request or source docs.
- The test would require real credentials, production data, external writes, or
  paid service calls without explicit approval and a sandbox plan.
- No reliable local boundary exists to exercise the behavior; record the gap and
  add the smallest test seam or manual evidence plan before claiming coverage.
- The implementation must be changed only to satisfy an unrealistic test shape;
  revise the scenario to match the product boundary instead.

## Verification

Before reporting tests complete:

- Name the scenario matrix covered and the rows intentionally omitted.
- Run the nearest reliable command that exercises the changed boundary.
- For automated tests, report command, result, and what actor/action/response
  path it proves.
- For manual checks, report scenario, environment, action, expected result, and
  observed result.
- If scenario coverage is incomplete, state the missing row and residual risk
  instead of calling the test suite comprehensive.

Useful source anchors:

- [Testing Library Guiding Principles](https://testing-library.com/docs/guiding-principles)
  emphasizes tests that resemble real software usage.
- [Playwright Best Practices](https://playwright.dev/docs/best-practices)
  emphasizes user-visible behavior over implementation details.
- [Cypress Best Practices](https://docs.cypress.io/app/core-concepts/best-practices)
  gives practical guidance for maintainable browser-flow tests.
- [Gherkin Reference](https://cucumber.io/docs/gherkin/reference/)
  gives the Given/When/Then vocabulary used to express scenarios.
