---
keyflow_id: sys_flutter_widget_ui
status: review
type: human-reviewed-needed
requires:
  - common/nodes/ui-state-render-boundary.md
---

# Flutter Widget UI

Use when creating, changing, moving, or reviewing Flutter routes, pages,
widgets, design-system components, forms, gestures, navigation UI, golden tests,
or widget tests.

For reusable UI extraction, also read `common/skills/reusable-code-design/SKILL.md`,
`common/skills/component-api-design/SKILL.md`, and `common/skills/design-system/SKILL.md`.
For feature folders, local packages, package exports, and design-system
promotion decisions, also read `platforms/flutter/skills/flutter-project-structure/SKILL.md`.

## Widget Layers

Preserve an established repo convention (`*Page`/`*Root` -> `*Screen`) when one
exists; otherwise use this default shape aligned with
`platforms/flutter/skills/flutter-project-structure/SKILL.md`:

```text
Route (destination args/entry) -> Screen Widget (stateful holder)
-> Content Widget (stateless renderer) -> Section Widget
-> Feature Widget -> Design-System Primitive
```

- Route (`*Route` / `*_route.dart`) defines typed navigation arguments and thin
  router registration, never product state or layout trees.
- Screen widgets (`*Screen` / `*_screen.dart`) wire state owners
  (notifier/bloc/viewModel), one-off effects, permission launchers, and
  navigation callbacks, delegating rendering to `*Content`.
- Content widgets (`*Content` / `*_content.dart`) receive immutable view state,
  explicit callbacks, and slots so widget/golden tests run from fixtures without
  providers, routers, or DI.
- Section widgets receive only the state slice needed for that section.
- Feature widgets may know product UI models but not repositories, platform
  channels, route parsers, or service locators.
- Design-system primitives know visual and interaction contracts, not product
  routes, analytics labels, storage, permissions, or fake data.

## Statefulness

- App-stateful owner vs app-stateless renderer (`ui-state-render-boundary.md`)
  is a dependency boundary, not a `StatefulWidget` vs `StatelessWidget` class
  test: a `StatelessWidget` reading a global provider is app-stateful, while an
  app-stateless `*Content` renderer may subclass `StatefulWidget` (or hooks)
  solely for local UI controllers.
- Use `StatelessWidget` for pure rendering when no local controller is needed.
- Use `StatefulWidget`, hooks, controllers, or local notifiers in renderers only
  for local UI state such as focus, scroll, animation, text editing, selection,
  tabs, expansion, and gesture state.
- Keep product state in the repo's state owner, not in a widget subtree that can
  be rebuilt, disposed, or duplicated unexpectedly.
- Dispose controllers, subscriptions, animation controllers, focus nodes,
  streams, timers, and platform listeners in the owning widget or service.

## UI Contract

- Make long text, narrow screens, large text scale, keyboard focus, reduced
  motion, loading, empty, error, disabled, and permission-denied states explicit
  when they are reachable.
- Use semantic labels, roles, focus order, hit targets, and localization as part
  of the component contract.
- Use keys intentionally for lists, forms, animations, test selectors, and
  state preservation.
- Do not read global providers or routers from leaf widgets when explicit
  values and callbacks keep the component reusable.
- Keep target-specific interaction differences visible, such as desktop
  keyboard shortcuts and hover, mobile touch, and web browser constraints.

## Verification

- Run analyzer or compile checks for changed packages.
- Use widget tests for state rendering, callbacks, forms, focus, semantics, and
  navigation outputs.
- Use golden tests or screenshots for visual component changes when configured.
- Use integration or target smoke checks when platform services, plugins,
  lifecycle, permissions, or routing changed.
