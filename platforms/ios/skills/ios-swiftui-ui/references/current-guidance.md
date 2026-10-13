---
keyflow_id: sys_ios_swiftui_ui
status: review
type: human-reviewed-needed
---

# iOS SwiftUI UI

Use when creating, changing, moving, or reviewing SwiftUI screens, view models,
state models, reusable views, previews, navigation, or UI tests.

For architecture choice, also read `../../common/skills/architecture-design/SKILL.md` and
`../swift/swift-architecture.md`. For Swift design-system tokens, styles,
primitives, and reusable component contracts, also read
`../swift/swift-design-system.md`. For
state lifetimes, async work, cancellation, persistence, and actor boundaries,
also read `ios-state-concurrency.md`. For reusable UI extraction, also read
`../../common/skills/reusable-code-design/SKILL.md` and `../../common/skills/design-system/SKILL.md`.
For targets, local Swift packages, feature contracts, and access-control
boundaries, also read `ios-module-structure.md` and
`../swift/swift-code-structure.md`.

## SwiftUI Layers

Use this shape unless the repo has a stricter local pattern:

```text
Route/Coordinator -> Screen View -> Section View -> Feature View
-> Design-System Primitive
```

- Route/coordinator owns navigation wiring, dependency entry points, sheets,
  alerts that cross screen boundaries, and platform handoff.
- Screen view renders one workflow. It observes state, sends user intent, and
  delegates complex areas to section views.
- Section views render one part of the screen and receive only the state they
  need.
- Feature views may know feature display models but not repositories, API
  clients, keychain, files, permission services, or analytics dispatch.
- Design-system primitives own visual and interaction contracts, not product
  policy, routing, or domain rules.

## Mandatory View Split

SwiftUI screens must be split into named views instead of placing the full
screen hierarchy in one `body` or one file. A screen may own the top-level state
switch, but headers, forms, filter bars, list regions, rows, cards, dialogs,
empty states, error states, permission states, and bottom actions must become
section or feature views as soon as they have a distinct visual or interaction
responsibility.

Use a feature-local `Components/` folder for reusable views inside a feature,
and split it by role from the start with folders such as `Inputs`, `Feedback`,
`Cards`, `Lists`, `Dialogs`, `Navigation`, or `DataDisplay`. Promote only
stable, domain-free controls into the Swift design-system package.

Do not:

- Do not approve SwiftUI that keeps distinct sections, rows, cards, dialogs,
  feedback states, and actions in one `body`, one screen view, or one file.
- Do not put every view, row, card, dialog, empty/error/loading state, and
  footer action into one `Screen.swift`.
- Do not hide a large UI behind one `var body: some View` with many nested
  stacks, builders, and conditionals.
- Do not keep many named SwiftUI views in one file once they can be previewed,
  tested, imported, or reviewed independently.
- Do not use private nested view types to avoid creating files for real
  sections or reusable controls.
- Do not pass whole screen state into every section when a smaller display model
  or binding makes ownership clearer.
- Do not use raw SwiftUI/UIKit/AppKit controls across feature screens when a
  product-prefixed design-system wrapper must own tokens and states.
- Do not expose a platform control unchanged as the product component. The
  wrapper must define semantic variants, slots, accessibility, loading/disabled
  behavior, and token ownership.

## Architecture Tracks

Choose the smallest track that makes ownership and testing clear:

| Track | Use When | Shape |
| --- | --- | --- |
| Simple SwiftUI | Local screen state, no domain workflow, no persistence, no external service. | `View -> local @State` |
| TCA / Unidirectional State | Default for non-trivial SwiftUI: API effects, navigation, shared state, optimistic updates, replayable actions, reducer tests, or composed child features. | `View -> Store -> Reducer -> Effects/UseCases -> Repositories` |
| MVVM | Simple or legacy-constrained loading, form submission, async fetch, navigation state, permission state, or reusable screen logic. | `View -> Action/Intent -> @MainActor ViewModel -> Repository/Client -> State` |
| Clean Architecture | Domain policy, offline/sync, auth/tenant/billing, multiple clients, multiple callers, or complex test boundary. | `View -> Store/ViewModel -> UseCase -> Repository protocol -> Adapter/Client` |

Do not add use cases, repositories, reducers, or protocols only for ceremony.
Add them when they isolate a real product rule, side effect, or test boundary.

For modern SwiftUI, simple screens can stay Model-View: a small view owns
presentation `@State`, reads services or shared models from the environment,
models reachable states explicitly, and uses `.task` for lifecycle-bound async
work. Add TCA before ad hoc MVVM when the screen needs reusable state ownership,
complex transitions, cancellation, navigation output, product rules, child
composition, or focused reducer tests. Use MVVM only when it stays
UDF-constrained and the repo already has that pattern or the feature is small.
Do not create a ViewModel only because a view file exists.

TCA is the preferred iOS SwiftUI implementation track in Moru Core. A
repo-local TCA skill may add commands and examples, but this card remains the
shared source of truth for when TCA should be used.

## ViewModel Rule

View models or observable state owners should:

- Be `@MainActor` when they publish UI state.
- Own screen-level `UiState`, user actions, async task coordination, and
  user-visible errors.
- Keep mutation behind a single UDF entry path, such as `send(_:)`, typed
  action handlers, or intent methods that all update the same state model.
- Depend on protocols or small client interfaces for API, persistence, keychain,
  files, permissions, notifications, and external SDKs.
- Convert DTO/domain models into display models before the view renders them.
- Expose methods named by user intent, such as `onAppear()`, `refresh()`,
  `submit()`, `retry()`, `selectItem(_:)`, or `dismissError()`.

Views should not:

- Call repositories, URLSession, Keychain, file APIs, permission APIs, or
  analytics directly.
- Own business rules in `body`, `.task`, `.onAppear`, or button handlers.
- Store server state in `@State` when a ViewModel should own the lifecycle.
- Switch on raw API errors or transport DTOs.

## TCA Feature Shape

When using TCA, keep the feature shape explicit:

```text
ProfileFeature.State      loading/content/empty/error/navigation state
ProfileFeature.Action     appeared, retryTapped, response, child actions
ProfileFeature.Reducer    pure state transitions plus effect requests
ProfileFeature.Dependency API, persistence, clock, uuid, analytics, crash hooks
ProfileScreen             observes store state and sends actions only
```

Use child reducers for independently testable child workflows. Keep product
copy, analytics names, permission policy, and navigation contracts at the
feature or route boundary, not inside design-system primitives. Do not use TCA
as permission to put every feature in one reducer file; split state, actions,
dependencies, views, fixtures, and reducer tests when they are independently
reviewable.

## UiState Shape

Use explicit state instead of scattered booleans and optional data.

For mutually exclusive screen states, prefer an enum:

```swift
enum ProfileUiState: Equatable {
    case loading
    case content(ProfileViewData)
    case empty
    case permissionDenied
    case offline(ProfileViewData?)
    case error(ProfileErrorViewData)
}
```

For content with independent sub-states, prefer a struct with typed fields:

```swift
struct CheckoutUiState: Equatable {
    var form: CheckoutFormState
    var submit: SubmitState
    var entitlement: EntitlementState
    var banner: BannerState?
}
```

Rules:

- Loading, empty, error, permission denied, offline, disabled, and submitted
  states must be representable.
- API-backed loading should preserve the current page shape when possible:
  render stable navigation, toolbar, card/list density, and section positions
  with skeleton or redacted placeholders before replacing them with content.
- Keep one-off events separate from persistent state. Use navigation state,
  callback output, or a typed effect channel instead of hiding navigation inside
  random booleans.
- Do not represent state with unrelated pairs such as `isLoading`, `items?`,
  `error?`, and `isEmpty` when impossible combinations can occur.
- Do not put SwiftUI types such as `Color`, `Font`, `Image`, or `View` inside
  domain models. Keep those at the UI/display boundary.

## Observation And UiState Split

SwiftUI invalidates views through observed state. Treat `UiState` as an
observation contract, not as a mandate to pass one screen state or observable
object into every section. Split state by owner, update cadence, render cost,
and the smallest view that needs to change.

Use coarse screen `UiState` for top-level loading, content, empty, error,
permission, selected ids, stable summaries, and workflow capabilities. Keep
high-churn state closer to the view that observes it:

- chat or conversation messages, list windows, row delivery state, read
  receipts, typing indicators, and presence
- text drafts before commit, focus, scroll, drag, animation, timers, playback
  progress, live metrics, and cursor-like state
- row, badge, or indicator state where only one repeated view should update

For conversation UI, a screen ViewModel can own thread metadata, connection
status, permissions, composer availability, and top-level failure states.
Messages should use stable `Identifiable` item models and a list/window owner
that updates rows without invalidating unrelated sections. Typing, presence,
delivery, and draft state should be held by the smallest ViewModel, observable
slice, binding, or local `@State` that owns their lifecycle.

Do not split for ceremony. A simple profile, read-only settings page, or small
form can keep one enum or struct when all values update together. When a split
is justified as performance work, name which observed object, binding, or view
subtree avoids extra invalidation.

## View Composition

Screen views should be easy to preview and test:

```swift
struct ProfileScreen: View {
    let state: ProfileUiState
    let onRetry: () -> Void
    let onEdit: () -> Void

    var body: some View {
        switch state {
        case .loading:
            ProfileSkeleton()
        case .content(let data):
            ProfileContent(data: data, onEdit: onEdit)
        case .empty:
            EmptyStateView(...)
        case .permissionDenied:
            PermissionDeniedView(...)
        case .offline(let cached):
            OfflineProfileView(cached: cached, onRetry: onRetry)
        case .error(let error):
            ErrorStateView(error: error, onRetry: onRetry)
        }
    }
}
```

- Keep ViewModel-backed containers thin and delegate rendering to pure views.
- Pass callbacks, bindings, and small display models, not full service objects.
- Keep `@State` local to presentation details such as focus, expansion, scroll,
  tab selection, text-field drafts before commit, and animation flags.
- Use `@Binding` only when the parent owns the value and two-way editing is the
  intended contract.
- For `@Observable`, use `@State` when the view owns the object, plain `let`
  when the view only reads it, `@Bindable` when two-way bindings are needed, and
  `@Environment(Type.self)` for scoped shared observable state.
- Use environment values for framework-level UI concerns and deliberately scoped
  dependencies. Do not turn the environment into a hidden global business
  service locator.
- Keep heavy filtering, sorting, formatting, or data shaping out of `body`.
  Move it to a computed property, mapper, state owner, or model.
- Prefer `@ViewBuilder`, `Group`, generics, or small subviews over `AnyView`.
  Use type erasure only for a real public API or storage boundary.
- Omit hard-coded stack `spacing:` unless the value is intentional. Let platform
  defaults handle adaptive spacing when they fit the design.

## Navigation And Effects

- Model navigation as explicit state or typed output from the screen owner.
- Keep deep link, URL scheme, tab, sheet, popover, and alert decisions at route
  or coordinator boundaries.
- Keep `.task` and `.onAppear` idempotent. They should call a ViewModel intent
  rather than embedding fetch logic.
- Prefer `.task` for lifecycle-bound async loading and `.task(id:)` for work
  that should restart when an input changes.
- Ensure async work cancels on disappear, logout, account switch, permission
  changes, or task replacement when those events matter.
- Suppress stale async results when a newer request has replaced the old one.

## File Layout

A feature can use:

```text
Features/Profile/
  ProfileRoute.swift          navigation and dependency wiring
  ProfileScreen.swift         pure screen rendering
  ProfileFeature.swift        TCA state, actions, reducer, effects
  ProfileViewModel.swift      only for MVVM tracks
  ProfileUiState.swift        display state for non-TCA tracks
  Components/                 feature-local views
  PreviewData/                deterministic preview fixtures
  ProfileFeatureTests.swift   or ProfileViewModelTests.swift
```

Shared UI can use:

```text
DesignSystem/
  Theme/
  Components/
  Components/Inputs/
  Components/Feedback/
```

Promote a view to shared UI only when its caller contract is stable and product
copy, routing, analytics, permissions, and domain policy stay outside it.

## Preview Rule

Every new or meaningfully changed screen, section, or reusable view needs a
SwiftUI preview unless the repo has a stronger snapshot or UI test that covers
the same visual states.

Previews should:

- Target pure screen/section/component views, not dependency-heavy route views.
- Use deterministic sample state from `PreviewData`, fixtures, or static
  factory methods.
- Cover changed states such as content, skeleton loading, refreshing with stale
  content, empty, error, permission denied, offline, disabled, retry, long
  text, Dynamic Type, and dark mode when affected.
- Avoid network, persistence, keychain, random data, current time, real
  credentials, and device-only services.

If a preview cannot be added, name the replacement verification path.

## Tests

Choose the closest checks configured in the repo:

- ViewModel tests for state transitions, user intents, loading, error, retry,
  permission denial, and cancellation.
- Reducer tests for TCA state transitions, effect output, dependency failures,
  navigation state, retry, cancellation, and stale response suppression.
- Mapper tests for DTO/domain to display-state conversion.
- Use case tests when product rules move out of the ViewModel.
- XCUITest for navigation, forms, permissions, and critical flows.
- Snapshot tests only when the repo already supports them and visual regression
  is meaningful.
- Build or test command for the affected target.

Review the final diff for business rules in views, direct platform API calls
from UI, impossible UI state combinations, missing previews, and shared views
that absorbed product-specific behavior.
