---
keyflow_id: sys_flutter_widget_ui
status: review
type: human-reviewed-needed
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

Use this shape unless the repo has a stricter local pattern:

```text
Route/Page -> Screen Widget -> Section Widget -> Feature Widget
-> Design-System Primitive
```

- Route/page widgets wire navigation, state owners, effects, permission
  launchers, and dependency entry points.
- Screen widgets receive immutable view state and explicit callbacks.
- Section widgets receive only the state needed for that section.
- Feature widgets may know product UI models but not repositories, platform
  channels, route parsers, or service locators.
- Design-system primitives know visual and interaction contracts, not product
  routes, analytics labels, storage, permissions, or fake data.

## Statefulness

- Use `StatelessWidget` for pure rendering.
- Use `StatefulWidget`, hooks, controllers, or local notifiers only for local UI
  state such as focus, scroll, animation, text editing, selection, tabs,
  expansion, and gesture state.
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
