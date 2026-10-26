---
keyflow_id: sys_60c9ad0c6826
status: review
type: ai-generated
---

# iOS State And Concurrency

Use when touching SwiftUI/UIKit state, navigation, async work, or platform permissions.

For SwiftUI `UiState`, ViewModel, screen composition, and preview rules, also use
`platforms/ios/skills/ios-swiftui-ui/SKILL.md`.

For repository/client contracts, adapter packages, local Swift packages, and
target ownership, also use `platforms/ios/skills/ios-module-structure/SKILL.md`.

For shared persistence, cache, sync, migration, and source-of-truth rules, also
use `common/skills/data-persistence-sync/SKILL.md`.

References:

- SwiftData: `https://developer.apple.com/documentation/swiftdata`
- Core Data: `https://developer.apple.com/documentation/coredata`
- UserDefaults: `https://developer.apple.com/documentation/foundation/userdefaults`
- Keychain Services:
  `https://developer.apple.com/documentation/security/keychain-services`

## Defaults

- View owns only local presentation state.
- Data flow is unidirectional: the View renders state, sends an action or
  intent, the state owner performs effects through dependencies, and only the
  state owner publishes the next state.
- For non-trivial SwiftUI features, prefer TCA-style `State -> Action ->
  Reducer -> Effect -> State`. For MVVM features, keep a single
  `send(_:)`, intent method family, or equivalent entry point so mutation stays
  behind the ViewModel.
- View, observable model, ViewModel, store, or reducer owns loading, empty,
  error, and permission states according to the chosen architecture track.
- Prefer typed state models or enums over scattered booleans and nullable data
  when states are mutually exclusive.
- Navigation state is modeled, not hidden in side effects.
- Async work has visible ownership, cancellation, and error handling.
- UI updates respect actor boundaries.
- Long-running tasks define cancellation on disappear, logout, account switch,
  and permission changes.
- Persisted state defines migration, corruption, and app-upgrade behavior.
- Keychain, files, notifications, permissions, and persistence stay behind adapters.

## iOS Local Persistence Selection

iOS does not have one default database equivalent for every use case. Choose by
data shape and product risk:

| Choice | Use When | Avoid When |
| --- | --- | --- |
| SwiftData | Newer SwiftUI-first features need typed local models, relationships, simple queries, previews/tests can use in-memory containers, and the deployment target supports the framework. | Existing Core Data stores, complex legacy migrations, strict SQL control, cross-platform database files, or features that would leak `ModelContext`/`@Model` into domain and UI contracts. |
| Core Data | The app already uses Core Data, needs mature migration tooling, large object graphs, batch/background work, CloudKit integration, or existing model/editor workflows. | A small settings object, a simple cache with no relationships, or a new feature where SwiftData meets the same needs with less integration cost. |
| SQLite or a repo-approved wrapper | The app needs explicit SQL, full-text search, custom indexes, cross-platform schema compatibility, deterministic migrations, imported database files, or performance tuning below object-framework abstractions. | The feature only needs platform-managed typed persistence or a few preferences. |
| UserDefaults / `@AppStorage` | Small non-sensitive preferences, toggles, enum choices, display settings, onboarding flags, or simple feature settings. | Credentials, refresh tokens, personal data, queryable records, histories, relationship data, or values that require migration as product data. |
| Keychain | Access tokens, refresh tokens, private credentials, device-bound secrets, or small sensitive auth material. | Product collections, large blobs, query-heavy data, cache records, or values that must be shown in previews/tests. |
| Files, caches, or documents | User-owned documents, exports/imports, media, attachments, or derived cache with explicit validation and invalidation. | Structured app state that needs transactions or secrets without an encryption and retention model. |

Keep the selected storage behind a repository, data-source, or platform adapter.
SwiftData `ModelContext`, Core Data managed objects/contexts, raw SQLite
handles, `UserDefaults`, and Keychain APIs should not reach SwiftUI views,
reducers, ViewModels, domain policies, or public feature contracts unless the
repo explicitly documents that boundary as the product model.

Storage selection must name:

- source of truth and whether data is local-first, server-first, or cache-only
- schema or key ownership, migration path, and rollback/corruption behavior
- cleanup behavior on logout, account switch, permission revoke, entitlement
  downgrade, and remote deletion
- test strategy, such as in-memory stores, temporary files, fakes, or adapter
  contract tests

## SwiftUI Observation And Task Rules

- UI-bound `@Observable` classes must be `@MainActor` unless the repo has a
  stronger actor model and proves UI updates cross actors safely.
- Use `@State` when a view owns an observable object or value. Use `let` for
  read-only observable inputs, `@Bindable` for two-way bindings, and
  `@Environment(Type.self)` for scoped shared observable state.
- Keep `@AppStorage` in views or wrap `UserDefaults` explicitly inside the
  observable owner. Do not hide `@AppStorage` inside an `@Observable` class and
  expect observation to refresh views.
- Prefer `.task` for async loading because SwiftUI cancels it with the view
  lifecycle. Use `.task(id:)` when a dependency should restart the work.
- Create manual `Task` values in `onAppear` only when the owner stores and
  cancels the task explicitly. `Task {}` in a synchronous button or menu action
  is acceptable when the action immediately hands off to an async owner.
- Large lists and grids need stable `Identifiable` IDs and lazy containers when
  the collection is not trivially small. Do not use array indices as identity
  when reordering, animation, selection, or local row state matters.

## Async API Errors

For `async throws` repository or client calls, do not make `Result<Success,
Failure>` or a custom `success/failure` response enum the default shape only to
re-wrap thrown errors. Let successful async calls return the decoded value or an
internal response type, and throw typed transport, protocol, or domain errors
for failure.

Network adapters should hide `URLSession`, provider SDK, and transport-library
details by normalizing only the small response boundary the app owns, such as
status, selected headers, body, safe server error code, retry metadata, and
correlation id. ViewModels, stores, reducers, or coordinators catch those typed
errors and map them into `UiState`, alert/sheet/navigation state, or one-off
effects.

If a server error envelope carries presentation hints such as inline, banner,
alert, full-page, retry, or a deep-link action, treat them as stable contract
hints. The iOS state owner decides how to render supported hints in SwiftUI or
UIKit and defines a safe fallback for unsupported hints.

## Loading And Placeholder States

API-backed screens need a first-class loading state. The preferred default is a
skeleton or placeholder layout that mirrors the final page structure closely
enough that the transition from loading to content feels stable. Use a spinner
only for small inline actions, blocking modal waits, or flows where the final
layout is unknown.

Rules:

- Render the same navigation chrome, toolbar, primary regions, list/card
  density, and safe-area shape during loading when those elements are stable.
- Reserve final layout space with skeleton rows, cards, thumbnails, text
  blocks, or redacted SwiftUI placeholders instead of showing a blank page that
  jumps on success.
- Keep pull-to-refresh or background refresh separate from initial loading when
  stale content can remain visible.
- Map transport, permission, offline, empty, and domain errors into typed
  persistent state or explicit one-off effects. Do not collapse them into a
  generic `errorMessage`.
- Make retry actions explicit actions/intents. A retry should re-enter the same
  reducer/ViewModel path as the original load.

Do not claim an API feature is complete unless loading, content, empty, error,
permission denied, offline, retry, and cancellation behavior are either
implemented or explicitly out of scope.

## Check

- Can stale async results update the UI?
- What happens when the view disappears?
- What cancels or restarts work after logout, account switch, app backgrounding,
  or process termination?
- Does permission denial have a user-visible state?
- Is sensitive data outside plain UserDefaults and logs?
- Does the chosen iOS storage match the data shape: SwiftData/Core Data/SQLite
  for durable models, UserDefaults for non-sensitive preferences, Keychain for
  secrets, and files/caches for document or derived data?
- Are Task, async sequence, Combine, and observation lifetimes chosen
  intentionally?

## Tests

Cover loading-to-content transition, error-to-retry transition, cancellation,
stale result suppression, permission denial, persistence migration, process
relaunch, storage corruption/defaulting, logout/account-switch cleanup, and
actor-boundary behavior when applicable.
