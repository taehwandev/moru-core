---
keyflow_id: sys_swift_architecture
status: review
type: human-reviewed-needed
---

# Swift Architecture

Use for Swift app or library architecture across Apple platforms: iOS, macOS,
watchOS, tvOS, widgets, extensions, command-line tools, and local Swift
packages.

Also use:

- `platforms/swift/skills/swift-code-structure/SKILL.md` for Swift Package Manager layout, Xcode targets,
  access control, package boundaries, and file ownership.
- `platforms/swift/skills/swift-design-system/SKILL.md` for SwiftUI/UIKit/AppKit tokens, styles,
  primitives, previews, and reusable component contracts.
- `platforms/ios/skills/ios-architecture/SKILL.md` for iOS-specific navigation, SwiftUI/UIKit app
  structure, permissions, and security follow-up cards.
- `platforms/application/skills/application-architecture/SKILL.md` for macOS desktop shells, menu
  bar/tray apps, windows, commands, IPC, files, shell, clipboard, and native
  packaging.
- `common/skills/architecture-design/SKILL.md` for architecture track selection.

## Boundary Model

Prefer the smallest boundary that keeps state, side effects, and platform APIs
visible:

```text
App/Entry Point -> Feature/Workflow -> State Owner -> Use Case/Policy
-> Repository Protocol -> Adapter/Client -> Platform Framework
```

- App or executable target owns launch, scene/window setup, dependency assembly,
  app lifecycle, entitlements, and top-level routing.
- Feature/workflow owns one user or system behavior and composes views,
  state owners, display models, and use cases.
- State owner owns `UiState`, user intents, async task coordination,
  cancellation, and user-visible errors.
- Use case or policy owns product rules, permission decisions, mutation
  orchestration, and testable business behavior.
- Repository protocol expresses domain needs in Swift terms, not raw transport,
  database row, SDK, or OS framework details.
- Adapter/client owns URLSession, persistence, Keychain, files, notifications,
  StoreKit, HealthKit, Core Location, AppKit, UIKit, SwiftUI, or other platform
  framework calls.

## Architecture Tracks

Choose one track explicitly for non-trivial Swift work:

| Track | Use When | Shape |
| --- | --- | --- |
| Local Swift | One target, local state, no risky side effect, no shared domain rule. | `View/Controller -> local state/helper` |
| State Owner / MVVM | Loading, form submit, async fetch, navigation, permission, or reusable screen logic needs an owner. | `View/Controller -> @MainActor ViewModel/Model -> Client` |
| Use Case Boundary | Product rule, permission, sync, persistence, mutation, or external integration needs focused tests. | `State Owner -> UseCase/Policy -> Repository protocol` |
| Reducer / State Machine | Many events, optimistic updates, replayable transitions, wizard flows, or concurrency races. For non-trivial iOS SwiftUI, prefer TCA as this track. | `State -> Action -> Reducer/Machine -> Effect` |
| Modular Package | Multiple app targets, extensions, widgets, packages, or owners need stable contracts. | `App target -> feature/domain/data/platform packages` |

Do not add use cases, protocols, reducers, packages, or factories only for
ceremony. Add a boundary when it protects a real caller contract, side effect,
test boundary, or dependency edge.

## SwiftUI State Default

For modern SwiftUI targets, start with Model-View before adding MVVM ceremony:

- Keep simple screens as small views with local `@State`, environment-provided
  services, explicit `UiState`, and `.task` or `.onChange` orchestration.
- Promote to TCA/store/reducer before ad hoc MVVM when loading, mutation,
  navigation, permissions, cancellation, reuse, child composition, or product
  rules need deterministic state ownership and reducer tests. Use a
  `@MainActor` observable model or ViewModel when the repo is already MVVM or
  the workflow is simple enough that TCA would add more ceremony than safety.
- Use `@Observable` for shared SwiftUI state on iOS 17 and newer when repo
  deployment targets allow it. Keep legacy `ObservableObject` for older targets
  or existing architecture that already depends on it.
- Treat ViewModel as one possible state-owner name, not a mandatory file for
  every view.

## Swift Ownership Rules

- Keep SwiftUI, UIKit, AppKit, DTOs, persistence rows, and SDK types out of
  domain models and pure policies.
- Keep views and controllers render-focused. They send intent and render
  explicit state; they do not own repository calls, credential access, file I/O,
  permission checks, or product rules.
- Keep SwiftUI data flow unidirectional. Views send actions/intents; stores,
  reducers, observable models, or ViewModels publish the next state; effects
  call use cases, repositories, and adapters.
- Use `@MainActor` for observable state that publishes UI changes. Keep heavy
  work, blocking I/O, and long-running processing off the main actor.
- Prefer value types for immutable state and display models. Use reference types
  for identity, lifecycle, observation, shared mutable state, or platform object
  ownership.
- Add protocols at boundaries that need a fake, alternate implementation,
  dependency isolation, or stable caller contract. Do not create a protocol for
  every concrete type by default.
- Keep dependency assembly at the app, scene, route, command, or feature entry
  point. Avoid hidden global service locators.
- Use SwiftUI `Environment` for framework-level UI capabilities or scoped
  dependencies, not as a hidden channel for broad business services.
- Treat `Task`, async sequences, Combine subscriptions, notifications, timers,
  delegates, and OS handles as owned resources with cancellation or cleanup.

## Data And Platform Boundaries

- Convert DTOs, database rows, generated client models, and SDK payloads before
  they reach views, controllers, or domain policies.
- Put persistence migration, corruption handling, cache invalidation, and app
  upgrade behavior in the data or adapter owner.
- Wrap Keychain, files, notifications, permissions, camera, location, StoreKit,
  WebKit, Accessibility, and other OS APIs behind small adapters when features
  need testable behavior or stable error states.
- Keep user-visible errors typed and safe. Log private platform details only in
  approved diagnostics paths.
- Keep app extension, widget, preview, and test targets importing only the
  contracts they need.

## Navigation And Composition

- Model navigation, sheets, alerts, popovers, deep links, and external launches
  as explicit route state or typed output from the state owner.
- Normalize URL schemes, Universal Links, handoff, command invocations, menu
  actions, and shortcuts at route or command boundaries.
- For UIKit/AppKit, use coordinators or command owners when navigation or
  window lifecycle outgrows one controller.
- For SwiftUI, keep route/container views thin and delegate pure rendering to
  screen and section views.
- Build previews and tests from deterministic fixtures, fakes, or package-local
  test support instead of real network, file, credential, or device services.

## Refactor Signals

- A SwiftUI `body`, view controller, menu handler, or command owns UI, API,
  persistence, permission checks, and state transformation together.
- Domain models import SwiftUI, UIKit, AppKit, Core Data, SwiftData,
  URLSession-specific DTOs, or SDK payloads.
- View models expose raw DTOs, persistence rows, SDK objects, or transport
  errors to views.
- Async work can update stale UI after the view disappears, account changes,
  permission changes, or a newer request starts.
- A package or target split exists but callers cannot use the contract without
  importing the implementation.
- A shared module contains unrelated helpers, feature copy, route decisions,
  analytics names, and platform adapters with no clear owner.

## Verification

For Swift architecture changes, verify the boundary, not only formatting:

- run the repo's `swift build`, `swift test`, `xcodebuild`, or wrapper command
  for affected targets
- run state owner, mapper, use case, reducer, or adapter tests when those
  boundaries changed
- inspect imports for forbidden dependencies into domain, design system,
  contracts, views, and previews
- verify cancellation, stale result suppression, permission denial, and
  user-visible error states when async or platform work changed
- report the chosen track, rejected heavier boundary if relevant, and residual
  risk when automated coverage is missing
