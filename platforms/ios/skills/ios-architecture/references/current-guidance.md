---
keyflow_id: sys_e5ada2ab6483
status: review
type: ai-generated
---

# iOS Architecture

Use for iOS SwiftUI/UIKit app structure, state, navigation, async work,
permissions, and app target behavior.

For Swift-wide app architecture, package, state owner, domain/data/platform
boundary, and design-system rules, also use
`platforms/swift/skills/swift-architecture/SKILL.md`, `platforms/swift/skills/swift-code-structure/SKILL.md`, and
`platforms/swift/skills/swift-design-system/SKILL.md`.

For SwiftUI screen/component structure, ViewModel contracts, `UiState`, previews,
or clean-architecture implementation details, also use `platforms/ios/skills/ios-swiftui-ui/SKILL.md`.

For UIKit screens, coordinators, view controllers, presenters, table/collection
views, diffable data sources, forms, or UIKit navigation, also use
`platforms/ios/skills/ios-uikit-ui/SKILL.md`.

For targets, local Swift packages, feature folders, access control, and
contract/module splits, also use `platforms/ios/skills/ios-module-structure/SKILL.md`.

For navigation, async work, persistence, permissions, or actor boundaries, also use `platforms/ios/skills/ios-state-concurrency/SKILL.md`.

For credentials, Keychain, local storage, Universal Links, URL schemes,
entitlements, WebViews, or release builds, also use `platforms/ios/skills/ios-security/SKILL.md`.

For iOS SwiftUI features, the default state architecture is unidirectional data
flow. Prefer The Composable Architecture (TCA) for non-trivial SwiftUI features
with async effects, navigation, shared state, replayable transitions, or reducer
tests. Use MVVM + clean boundaries only when the feature is simple,
legacy-constrained, or already owns a repo-approved ViewModel track, and keep it
UDF-constrained through a single state/action entry point.

There is no separate Moru Core TCA skill card. Route TCA work through this
iOS architecture card, `platforms/ios/skills/ios-state-concurrency/SKILL.md`, `platforms/ios/skills/ios-swiftui-ui/SKILL.md`, and the
Swift cards. If a target repo has its own TCA skill, keep it as a thin
repo-local pointer to these rules plus repo-specific commands and examples.

Reference:

- The Composable Architecture:
  `https://github.com/pointfreeco/swift-composable-architecture`

## Boundaries

```text
View/ViewController -> Action/Intent -> Store/Reducer or ViewModel
  -> Effect/Use Case -> Repository/Client -> Platform Adapter
```

Targets and Swift packages should support this direction. Feature
implementations depend on contracts, domain, data protocols, design system, and
platform adapters; shared design/domain modules do not import feature
implementations.

## TCA-First Decision Rule

Use TCA by default when a SwiftUI feature has any of these pressures:

- API loading, retry, refresh, cancellation, stale result suppression, or
  optimistic updates.
- Navigation, sheets, alerts, deep links, or cross-feature outputs that should
  be explicit state.
- Shared state, child feature composition, wizard flows, or many user/system
  events.
- Product rules or permission decisions that need deterministic reducer tests.
- Crash-prone or hard-to-debug side effects that must be isolated behind
  dependencies.

Use MVVM + clean architecture when the repo is already MVVM, the workflow is
small, or adopting TCA would be a larger migration than the behavior requires.
That MVVM must still be unidirectional:

```text
View -> Action/Intent -> @MainActor ViewModel -> Use Case/Client -> State
```

Do not let Views mutate server state, call repositories, switch on raw
transport errors, or trigger navigation as hidden side effects.

## Rules

- View renders state and sends intent.
- Keep ViewModel-backed containers thin and delegate rendering to explicit
  screen/section views when SwiftUI is used.
- Model loading, empty, error, permission states explicitly.
- Choose simple SwiftUI only for local presentation state. Choose TCA/reducer
  state for non-trivial SwiftUI workflows. Choose MVVM + clean boundaries only
  when it remains UDF-constrained and has a clear reason.
- Keep async task ownership and cancellation visible.
- Keep UI updates on the correct actor boundary.
- Wrap API, persistence, keychain, file, notification, permission APIs.
- Keep DTOs out of Views when they carry transport details.

## SwiftUI Navigation Rules

- Use `NavigationStack` or `NavigationSplitView` for modern SwiftUI navigation;
  do not add new `NavigationView` code.
- Store lightweight `Hashable` route values, stable identifiers, or typed route
  enums in navigation state. Do not store view instances in `NavigationPath`.
- Give each tab its own `NavigationStack` and path. A shared path across tabs
  creates cross-tab back-stack bugs.
- Centralize route-to-destination mapping at the route, coordinator, or router
  boundary when navigation becomes more than one local push.
- Use `.sheet(item:)` when sheet state represents a selected model or
  destination. Let the sheet own its dismiss action when possible.
- Use `NavigationSplitView` for standard iPad or Mac sidebar-detail layouts.
  Use a manual split only when the product needs nonstandard columns.
- Centralize deep-link parsing and validation in the router or coordinator.
  Prefer Universal Links for public links and keep custom URL schemes scoped to
  app-owned use cases.

## Refactor Signals

- SwiftUI body owns side effects and business rules.
- ViewModel exposes raw API DTOs.
- Permission checks repeat in Views.
- ViewController owns UI, API, and state transformation together.
- SwiftUI feature with async loading, navigation, and retry grows ad hoc
  booleans instead of TCA state/actions or a UDF-constrained ViewModel.
