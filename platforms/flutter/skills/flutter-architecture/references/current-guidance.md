---
keyflow_id: sys_flutter_architecture
status: review
type: human-reviewed-needed
---

# Flutter Architecture

Use for Flutter apps, Dart packages, widgets, navigation, state management,
repositories, platform channels, plugins, mobile/desktop/web targets, and
shared UI/data architecture.

For widget implementation, also use `platforms/flutter/skills/flutter-widget-ui/SKILL.md`. For state,
async data, repositories, storage, and streams, also use
`platforms/flutter/skills/flutter-state-data/SKILL.md`. For platform channels, plugins, lifecycle,
permissions, isolates, or target-specific behavior, also use
`platforms/flutter/skills/flutter-platform-integration/SKILL.md`.
For feature folders, local packages, monorepo package boundaries, package
exports, plugins, or federated plugin splits, also use
`platforms/flutter/skills/flutter-project-structure/SKILL.md`.

## Boundaries

```text
Route/Page -> State Owner -> Use Case/Controller -> Repository
-> Data Source/Platform Service
```

Adapt names to the repo's state management choice, such as Riverpod, BLoC,
Provider, ChangeNotifier, ValueNotifier, Redux, or a local architecture.

Package and folder boundaries should preserve this direction. Widgets depend on
state owners and contracts; domain/data packages do not depend on widgets,
routes, `BuildContext`, or plugin implementation packages.

## Rules

- Widgets render state and emit user intent. They should not own business rules,
  repository calls, platform channel payloads, or persistence policy.
- Keep `BuildContext`, widgets, controllers, and Flutter framework types out of
  domain models and repositories.
- Keep platform channels, plugins, permissions, native callbacks, and lifecycle
  APIs behind services or adapters.
- Model loading, content, empty, error, permission denied, offline, and
  unsupported target states explicitly.
- Keep navigation parsing separate from business rules and data fetching.
- Follow the repo's existing state management pattern before introducing a new
  package or architecture.
- Keep mobile, desktop, and web differences explicit through capability checks,
  target adapters, or disabled states.

## Refactor Signals

- Business logic or async orchestration lives inside `build`.
- Leaf widgets read global providers, routers, repositories, or platform
  channels when callbacks or smaller models would suffice.
- Platform channel strings and dynamic maps are scattered across widgets.
- State is nullable values plus unrelated booleans instead of a typed state.
- Web, desktop, Android, and iOS behavior differs without a named capability or
  fallback path.

## Verification

- Run the narrowest configured Dart/Flutter analyzer, test, build, or target
  smoke check for the affected package or app.
- Add unit tests for state transitions and adapter behavior when logic changes.
- Add widget, golden, integration, or manual target checks when UI,
  navigation, platform services, permissions, or lifecycle behavior changed.
