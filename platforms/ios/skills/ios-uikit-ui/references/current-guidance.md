---
keyflow_id: sys_ios_uikit_ui
status: review
type: human-reviewed-needed
---

# iOS UIKit UI

For auth UI, provider sign-in buttons or brand assets, also read
`common/skills/social-sign-in-buttons/SKILL.md`.

Use when creating, changing, moving, or reviewing UIKit screens, view
controllers, coordinators, view models, table/collection views, diffable data
sources, forms, navigation, or UI tests.

For adaptive/large-screen layouts or iPhone Duo fold transitions, also read
`common/skills/foldable-adaptive-layout/SKILL.md`.

For shared state and async rules, also read `platforms/ios/skills/ios-state-concurrency/SKILL.md`. For
SwiftUI-specific screens, read `platforms/ios/skills/ios-swiftui-ui/SKILL.md` instead.
For targets, local Swift packages, feature contracts, and access-control
boundaries, also read `platforms/ios/skills/ios-module-structure/SKILL.md` and
`platforms/swift/skills/swift-code-structure/SKILL.md`. For shared tokens, styles, reusable
controls, and visual-state contracts, also read
`platforms/swift/skills/swift-design-system/SKILL.md`.

## UIKit Layers

Use this shape unless the repo has a stricter local pattern:

```text
Coordinator/Router -> ViewController -> ViewModel/Presenter
-> Use Case -> Repository/Client -> Platform Adapter
```

- Coordinator/router owns navigation, deep links, modal presentation, and flow
  assembly.
- ViewController owns view lifecycle, UIKit binding, layout, and user intent
  forwarding.
- ViewModel/presenter owns UI state, state transitions, async coordination, and
  display models.
- Use case owns product rules when they are reused, risky, or independently
  testable.
- Repository/client owns API, persistence, cache, keychain, files, notifications,
  permission services, and SDK boundaries through adapters.

## ViewController Rule

ViewControllers should:

- Bind state to UIKit views.
- Forward user actions to the ViewModel or coordinator.
- Own lifecycle-specific UI concerns such as keyboard, focus, scroll, and cell
  reuse.
- Keep table/collection data source updates deterministic.
- Keep layout and view construction separate enough to review.

ViewControllers should not:

- Call API clients, repositories, keychain, filesystem, permission services, or
  analytics directly.
- Own product rules in button handlers or delegate callbacks.
- Transform raw DTOs into UI copy inside cells.
- Decide authorization, billing, tenant, or role policy.

## State Binding

Use an explicit state model, even when UIKit is callback-based:

```swift
enum MembersUiState: Equatable {
    case loading
    case content(MembersViewData)
    case empty
    case permissionDenied
    case offline(MembersViewData?)
    case error(ErrorViewData)
}
```

Rules:

- Loading, content, empty, error, permission denied, offline, disabled, and
  submitted states must be representable when reachable.
- Keep one-off effects such as navigation, alert, toast, focus, file picker,
  share sheet, and permission prompt separate from persistent state.
- Apply state on the main actor or main queue.
- Suppress stale async results from previous requests.
- Make repeated bindings idempotent; rebinding should not duplicate observers,
  timers, notification handlers, or target actions.

## Lists And Forms

- Prefer diffable data sources or a deterministic update model for collection
  and table views.
- Cell view models should contain display-ready data, not DTOs or repositories.
- Cell reuse must reset images, loading indicators, cancellables, and temporary
  state.
- Forms should model validation errors, dirty state, submit pending, success,
  permission denied, and network error.
- Keyboard, focus, safe area, Dynamic Type, and VoiceOver behavior are part of
  the form contract.

## Coordinator And Navigation

- Keep navigation decisions in coordinators or typed ViewModel outputs.
- Revalidate auth, tenant, role, and entitlement before protected navigation.
- Deep links and URL schemes should parse into typed route intents before they
  touch screen logic.
- Modals, sheets, alerts, and child coordinators need explicit ownership and
  dismissal cleanup.

## Do Not

- Do not let a ViewController call API clients, repositories, Keychain,
  filesystem, permission services, analytics, billing, or tenant policy
  directly.
- Do not hide product rules in button handlers, delegate callbacks, cell
  configuration, target/action methods, or diffable data-source closures.
- Do not bind raw DTOs, database rows, or SDK models directly into cells or
  user-facing copy.
- Do not duplicate observers, timers, notification handlers, target actions,
  Combine subscriptions, or async callbacks on repeated binding or cell reuse.
- Do not let coordinators, child view controllers, modals, alerts, or
  completion closures retain each other after dismissal.

## File Layout

A UIKit feature can use:

```text
Features/Members/
  MembersCoordinator.swift
  MembersViewController.swift
  MembersViewModel.swift
  MembersUiState.swift
  MembersViewData.swift
  MembersDataSource.swift
  Cells/
  Views/
  Tests/
```

Keep cells, reusable views, and data sources feature-local until their caller
contract is stable enough for shared UI.

## Tests

Choose the closest checks configured in the repo:

- ViewModel/presenter tests for state transitions, validation, retry,
  permission denial, stale result suppression, and one-off outputs.
- Coordinator tests for route decisions where the repo supports them.
- Snapshot tests only when the repo already uses them and visual regression is
  meaningful.
- XCUITest for navigation, forms, permissions, and critical flows.
- Build or test command for the affected target.

Review the final diff for business rules in view controllers, duplicate
observers, unowned async callbacks, stale cell state, raw DTOs in cells, and
navigation decisions outside the coordinator/state owner.
