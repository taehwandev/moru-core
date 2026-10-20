---
keyflow_id: sys_8c200d3027b7
status: stable
type: ai-generated
---

# Architecture Selection

Use when choosing or changing architecture for an app, service, or major feature.

## Default

Prefer the repo's existing architecture. For new work, start with shared common rules, then choose one execution track: Android, iOS, Web, Server, or Application.

Do not start by creating layers, modules, packages, repositories, services,
stores, or use cases. Start by naming the behavior, state owner, data owner,
side-effect owner, and risk. Add architecture only where it protects one of
those decisions.

## Fit By Shape

- SaaS/admin UI: feature modules, route/data boundaries, server-state cache, reusable form/table patterns.
- Real-time/collab: event model, sync boundary, optimistic updates, conflict rules.
- iOS/Android: MVVM or unidirectional state, repositories, platform adapters.
  When one codebase must target both, choose the stack with
  `cross-platform-mobile-selection.md` in this folder.
- Application: commands/use cases, window/menu state, local persistence, system adapters.
- Backend API: route/controller, use case/service, repository/client, explicit auth/tenant boundary.

## Required Decisions

Before choosing an architecture for non-trivial work, answer these questions:

- Product behavior: what user or system outcome must be preserved?
- Source of truth: which layer owns the durable state, visible state, derived
  state, draft state, cache state, and one-off effects?
- Data boundary: where are external, persisted, generated, cached, or
  user-provided values parsed, validated, normalized, and mapped?
- Side effects: which layer owns network calls, storage, filesystem, platform
  APIs, shell/browser/OS calls, background work, analytics, logs, and retries?
- Failure contract: where are raw errors converted into typed failures, and what
  user-visible states or safe diagnostics result?
- Dependency direction: which imports are allowed, and what must never depend on
  UI, framework, transport, persistence, or platform implementation details?
- Verification boundary: what is the smallest test, preview, smoke path, or
  contract check that proves the risky behavior?

If these answers are unknown, do not add architecture to compensate. Clarify the
behavior or keep the change local until pressure is real.

## Escalate When

Permissions, billing, offline sync, background jobs, multi-client reuse, or complex domain rules make simple feature structure hard to reason about.

Escalate one level at a time:

```text
local code -> named state owner -> use case/domain policy -> repository/client
boundary -> platform/external adapter -> shared contract/package
```

Move upward only when the lower level no longer protects state, side effects,
tests, dependency direction, or caller ownership. Do not skip directly to clean
architecture, shared packages, or `api`/`impl` modules for one unstable caller.

## Architecture Red Flags

Stop and simplify when:

- a layer only forwards one method and adds no rule, test, mapping, or risk
  isolation
- a use case, service, repository, or store exists only because a template
  expects it
- UI owns transport, database, filesystem, SDK, permission, or platform payloads
- domain/model code imports UI, transport, persistence, platform, or framework
  implementation types
- shared code needs feature-specific copy, analytics names, permissions, routes,
  billing rules, tenant rules, or mode flags
- tests must boot an unrelated app shell, server process, renderer, or external
  service to verify one product rule
- one product change requires touching many unrelated files because boundaries
  are too ceremonial or too hidden

## Check

What changes together? Who owns state? Where do platform APIs live? What boundary should tests target?
