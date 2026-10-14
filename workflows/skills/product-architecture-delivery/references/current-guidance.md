---
keyflow_id: sys_product_architecture_delivery_workflow
status: stable
type: human-reviewed-needed
---

# Product Architecture Delivery Workflow

Use when a task should move from product intent to implementation through a full
delivery gate:

```text
PRD -> ARD -> Review -> Code Work -> Review -> Tests -> UI Tests -> Commit Readiness
```

Use this route by default when the user asks to build an app, start a product
feature, create a multi-screen flow, or "show how implementation works" by doing
real product work. Those requests need front matter before code unless they are
explicitly trivial and already scoped by an existing PRD/ARD.

This is a common workflow. Platform-specific cards decide how to implement and
verify each phase.

For agent execution, run the canonical start once before PRD, ARD, or implementation:

```text
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> --command product --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

Open every route `required_docs` entry directly and use that output as the
command manifest before writing PRD or ARD. Run the review hook after meaningful
changes and the finish hook before handoff. Direct `workflow.py route`,
`agent-preflight.py`, and `agent-finish-check.py` calls are lower-level
diagnostic fallbacks when the hook is unavailable.

When the requested deliverable is only a PRD or product requirements note, use
`workflows/skills/prd-creation/SKILL.md` through the PRD route instead:

```text
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> --command prd --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

Use the full `product` route when the task continues from PRD into ARD and code.

## Scaled Use

Use the full PRD and ARD gates for non-trivial behavior, architecture, data,
security, contract, release, billing, or user-visible workflow changes.

For trivial changes, use a lightweight note instead of forcing full PRD/ARD.
A change is trivial only when all of these are true:

- no behavior, API, schema, auth, permission, billing, data, release, or
  dependency boundary changes
- no new user state, error path, persistence, external service, or background
  behavior
- no ambiguity that could change implementation or verification
- verification is obvious and narrow

The lightweight note should still name intent, touched boundary, and
verification. If any condition is false, use the full workflow.
Do not treat a broad "app-making" or feature-delivery request as trivial just
because the first implementation slice is small.

## Read

- `workflows/skills/agent-task-lifecycle/SKILL.md`
- `workflows/skills/ambiguity-gate/SKILL.md` when product behavior, risk, scope, or verification is unclear
- `workflows/skills/development-cycle/SKILL.md`
- `common/skills/product-spec-to-implementation/SKILL.md`
- `common/skills/architecture-selection/SKILL.md`
- `common/skills/architecture-design/SKILL.md`
- `common/skills/api-contract-compatibility/SKILL.md` when contracts, DTOs, routes, events, or
  shared fixtures are touched
- `common/skills/security-privacy-review/SKILL.md` and `common/skills/secure-development-baseline/SKILL.md`
  when auth, permissions, user data, secrets, logs, external services, or public
  repositories are touched
- matching platform architecture, state/data, security, and review cards from
  `index.md`

## Platform Card Selection

Select platform cards from the affected surface before writing the ARD:

- Android app, Compose, ViewModel, Flow, Gradle, Android storage, permissions,
  background work, release build: Android cards.
- iOS app, SwiftUI/UIKit, actors/tasks, Keychain, app links, entitlements, signing:
  iOS cards.
- Web/React UI, routes, forms, browser storage, accessibility, i18n: Web cards.
- Server/API, database, jobs, webhooks, auth enforcement, queues: Server cards.
- Desktop/native shell, IPC, files, shell, clipboard, updates, signing:
  Application cards.

If multiple platforms are affected, load each matching platform architecture card
and one shared contract card. Do not load unrelated platforms just because the
repo is a monorepo.

## 1. PRD

Produce or update a product requirements note before coding when behavior is
non-trivial.

Before writing the PRD, give the user a compact alignment brief:

- same understanding: explicit goals and facts confirmed from the request or
  repo context
- may differ: scope, actor, success criteria, policy, or verification points
  where the agent may be assuming differently than the user
- unsupported assumptions or unknowns: defaults the agent would use if no
  blocker answer is needed
- minimal questions: one to three blocker questions only when the answer changes
  behavior, risk, architecture, or verification

PRD must answer:

- Who is the user or system actor?
- What outcome should change?
- What states must exist: success, loading, empty, error, permission denied,
  offline, conflict, rollback?
- What data, auth, permission, billing, privacy, or external-service surfaces are
  touched?
- What are the acceptance criteria?
- What is explicitly out of scope?
- What open decisions block implementation?

Stop before ARD when product behavior is ambiguous enough to change architecture,
security, data, or verification.

## 2. ARD

ARD means architecture requirements and decision note. It translates the PRD into
implementation boundaries.

ARD must answer:

- Which platform cards were loaded and why?
- What owns UI, state, domain, data, platform, and integration responsibilities?
- What modules, packages, routes, endpoints, screens, or services are touched?
- What contracts change: API, DTO, event, route, schema, fixture, storage format,
  generated client, or deep link?
- Where are auth, permission, tenant, billing, secret, logging, and privacy
  boundaries enforced?
- What dependency, generated-file, migration, release, or compatibility risk
  exists?
- What is the smallest implementation slice?
- What verification proves the slice and what UI test or manual UI smoke is
  required if UI changes?

ARD should be short. Use repo-local ADR or design-doc format when it exists.
Otherwise leave a concise note in the task, PR, issue, TODO, or changed docs.

## 3. Pre-Code Review

Review PRD and ARD before implementation:

- Acceptance criteria are testable.
- Platform cards and concern cards match the affected surface.
- The implementation slice is narrow enough to review and revert.
- Security, data, contract, and release risks are visible.
- Verification and UI test paths are known or explicitly unavailable.

Do not start code work when this review finds a blocking product or architecture
decision.

For broad or high-risk changes, use `workflows/skills/multi-perspective-review/SKILL.md` to
check product, UX, architecture, reliability, security, release, and QA risk
before implementation.

## 4. Code Work

Use `workflows/skills/development-cycle/SKILL.md` for implementation.

Rules:

- Change only the ARD-scoped files.
- Keep dependency, generated, formatting, migration, and release churn separate
  when possible.
- Update docs, fixtures, or generated clients only when they are part of the
  scoped contract.
- Preserve user-owned changes.

## 5. Review

Inspect the final diff against PRD, ARD, repo-local rules, platform cards, and
`workflows/skills/development-cycle/SKILL.md` side-effect audit.

Review must confirm:

- The code satisfies the PRD acceptance criteria.
- The implementation follows the ARD boundaries or records why it changed.
- No unrelated behavior, refactor, dependency, generated, release, or formatting
  churn is mixed in.
- Security, privacy, contract, persistence, observability, and accessibility
  impacts were checked when touched.

## 6. Tests

Run the minimum verification that proves the changed boundary first. Then broaden
only when the side-effect audit or risk surface requires it.

Use `common/skills/verification-policy/SKILL.md` and the matching platform review card for the
exact command style.

## 7. UI Tests

Run UI verification when user-visible UI, navigation, layout, text, accessibility,
or interaction behavior changed.

UI verification can be automated or manual, but it must name the checked state:

- primary success path
- loading, empty, error, permission denied, or offline state when affected
- navigation or deep-link path when affected
- accessibility, long text, localization, responsive layout, or focus behavior
  when affected

If no UI changed, record UI test as not applicable.

## 8. Commit Readiness

Before commit or handoff, answer:

- Is the diff one reviewable intent?
- Does every changed line trace to PRD, ARD, verification, or required generated
  output?
- Are secrets, local config, debug logs, private data, build outputs, and
  unrelated artifacts absent from the diff?
- Did required tests pass, fail with understood cause, or get explicitly skipped
  with residual risk?
- Is rollback or forward-fix clear for migrations, release config, and contract
  changes?
- Can the commit message state what changed, why, and how it was verified without
  hiding uncertainty?

Output one of:

```text
Commit-ready: yes
Commit-ready: no - blockers: ...
Commit-ready: partial - safe subset: ... / remaining risk: ...
```

If PRD, ARD, verification, UI test, handoff, or commit-readiness gaps revealed a
repeatable lesson, run `workflows/skills/retrospective-learning/SKILL.md` after handoff.

## Stop If

- PRD acceptance criteria are missing for a non-trivial behavior change.
- ARD cannot identify platform cards, ownership boundaries, or verification.
- The task requires product, security, billing, legal, release, or data policy not
  present in the repo.
- UI changed but no UI verification or acceptable manual smoke path exists.
- Commit readiness would require hiding skipped checks, unrelated changes, or
  unresolved risk.
