---
keyflow_id: sys_flutter_state_data
status: review
type: human-reviewed-needed
---

# Flutter State And Data

Use when touching Flutter state owners, Riverpod, BLoC, Provider,
ChangeNotifier, ValueNotifier, streams, repositories, storage, sync, isolates,
or async effects.

For general state-shape guidance, also use `common/skills/state-modeling/SKILL.md` and
`common/skills/error-modeling/SKILL.md`.
For repository package boundaries, local packages, and plugin/service ownership,
also use `platforms/flutter/skills/flutter-project-structure/SKILL.md`.

## Defaults

- State owners expose immutable view state and explicit user events.
- Model loading, content, empty, error, permission denied, offline, refreshing,
  and unsupported target states explicitly.
- Keep one-off navigation, snackbars, dialogs, file pickers, permission prompts,
  and platform effects separate from persistent view state.
- Repositories coordinate data sources and map platform, storage, network, and
  parsing failures into typed failures.
- Keep plugin models, database rows, platform-channel maps, and DTOs out of
  domain models unless the repo intentionally owns that contract.
- Cancel streams, subscriptions, timers, isolates, and in-flight work at the
  owner boundary.
- Define state reset behavior for logout, account switch, permission revoke,
  locale change, route disposal, app resume, and offline startup when affected.

## State Tool Rules

- Follow the repo's existing state management tool before introducing a new one.
- For Riverpod, keep providers small, dependency-aware, and testable without UI.
- For BLoC/Cubit, keep events, states, side effects, and repository calls typed
  and covered by transition tests.
- For Provider/ChangeNotifier, avoid mutable state leaks and notify only after
  consistent state transitions.
- For streams and isolates, define cancellation, backpressure, error mapping,
  and lifecycle ownership.

## Check

- Can the same state transition be tested without pumping the whole app?
- Are async errors represented in user-visible state and safe logs?
- Does route disposal or provider invalidation cancel work cleanly?
- Do persistence and cache changes handle versioning, migration, logout, and
  permission changes?
- Are target-specific unsupported paths visible instead of silently ignored?

## Do Not

- Do not put repository calls, plugin handles, route decisions, file pickers,
  permission prompts, dialogs, snackbars, or one-off navigation inside
  persistent view state.
- Do not expose mutable collections, database rows, platform-channel maps, DTOs,
  or plugin models as app/domain state unless the repo owns that public
  contract.
- Do not let streams, timers, isolates, subscriptions, or in-flight futures keep
  running after route disposal, provider invalidation, logout, or account
  switch.
- Do not collapse loading, refreshing, empty, offline, permission denied,
  unsupported target, and error states into nullable data plus a boolean.
- Do not introduce a second state-management tool or package-local state style
  only for one feature without a repo-level migration decision.
