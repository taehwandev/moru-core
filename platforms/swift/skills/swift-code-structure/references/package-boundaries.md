---
keyflow_id: sys_swift_package_boundaries
status: review
type: ai-generated
---

# Swift Package And Target Boundary Contracts

Use when designing or refactoring `Package.swift` products and targets, Xcode
targets, `Contract` / `Feature` / `UI` / `TestSupport` splits, `Core<Capability>`
modules, or `Bundle.module` resource ownership.

## `Package.swift` Products Versus Targets

Separate **external linkage (`products`)** from **internal modularization
(`targets`)**:

- Declare a library in `products:` only when an Xcode target (`.xcodeproj`,
  App, WidgetExtension, XPC helper) or an external package depends on it.
- Keep helper, domain, capability, and contract targets that are consumed only
  by sibling targets inside the same `Package.swift` out of `products:`, and
  share symbols across sibling targets with `package` access instead of `public`
  when the repo's Swift tools version supports it (Swift 5.9+).
- Prefer **one local `Package.swift` (or a small family of domain/layer local
  packages)** with focused targets over dozens of single-target `Package.swift`
  manifests, unless independent versioning or separate platform toolchains
  require separate manifests.
- Pin explicit `platforms:` in `Package.swift` and keep target `dependencies:`
  minimal; every declared target dependency must correspond to a real `import`.

## Target Families

Use repo-local naming conventions (`FeatureProfile` / `ProfileFeature`,
`FeatureProfileContract` / `ProfileAPI`) consistently once established. When
creating a new modular Swift layout, separate these families by capability:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| App / Executable target | `@main` entry, scene/window/command setup, entitlements, Info.plist, top-level navigation host, DI composition root. | Feature screens/reducers, reusable UI controls, concrete repositories, raw SQL/network clients. |
| `Feature<Name>Contract` (`api`) | `<Name>Route` destination data, deep-link/result/event values, entry/factory protocols, feature ports, small shared value types. | SwiftUI/UIKit/AppKit screen implementations, `@MainActor` ViewModels/stores, SDK/persistence dependencies. |
| `Feature<Name>` (`impl`) | `<Name>Screen` stateful holder, ViewModel/`@Observable` model/TCA `@Reducer`, `UiState`/`Action`/`Effect`, `<Name>Content` stateless view, mappers, destination binding, platform entry controller/window adapter. | Route identity types that peer navigating features must import, or shared design-system tokens. |
| `Feature<Name>UI` (optional) | Extracted `<Name>Content` (plus holder/state when needed) **only** when a named consumer outside `Feature<Name>` renders the surface (for example Widget, App Clip, macOS inspector, or second host). | Platform entry wrappers, navigation graph registration, concrete network/database implementations. |
| `Core<Capability>` | One concrete capability per target: `CoreDesignSystem`, `CoreNavigation`, `CoreNetworking`, `CorePersistence`, `CoreKeychain`, `CoreProcess`, `CoreNotice`. | Vague catch-all `Core`, `Common`, `Shared`, `Utils`, or `Feedback` buckets; feature copy, routes, or product policy. |
| `Domain<Capability>` / `Model<Capability>` | Capability-grouped entities, value types (`struct`/`enum`), pure policies, use cases, repository protocols. | `SwiftUI`, `UIKit`, `AppKit`, `CoreData`, `SwiftData`, `URLSession`, transport DTOs, or SDK models. |
| `Data<Capability>` | Repository implementations, DTOs, `Codable` wire schemas, database rows/migrations, cache coordination, mappers. | Screen state, views, route decisions, user-facing alert copy. |
| `<Boundary>TestSupport` / `Assertions` | Deterministic fixtures, builders, recording fakes/spies, test clocks/schedulers, assertion helpers compiling against `*Contract` / protocols. | Runtime app behavior or imports of production `*Feature` / `Data*` implementation targets by default. |
| Macro / Plugin / Helper executable | SwiftSyntax compiler plugin (`macro`), build-tool plugin, CLI, or XPC/daemon executable with narrow wire contracts. | App UI frameworks or shared mutable in-process app state. |

Start the data and domain layers coarse: one capability-partitioned `Domain` and
`Data` target pair (or `CoreModel` + `CoreData` with capability folders) before
splitting per-capability targets. Split a separate `Data<Capability>` target
only when heavy SDKs (Firebase, GRPC, SQLite/GRDB, WebKit, ML), extension slice
size, or independent team/test ownership demands it.

## `Contract`, `Feature`, `UI`, And `TestSupport` Ownership

Choose the smallest feature target shape from proven caller need:

| Proven Need | Smallest Swift Target Shape |
| --- | --- |
| Feature is entered only from one unsplit target | folder inside that target, or one unsplit `Feature<Name>` target |
| Peer feature, coordinator, widget, or extension navigates to or launches it | `Feature<Name>Contract` + `Feature<Name>` |
| Named outside host renders the concrete SwiftUI/AppKit/UIKit surface without `Feature<Name>` wiring | `Feature<Name>Contract` + `Feature<Name>` + `Feature<Name>UI` |

Dependency rules:

```text
navigating peer feature  -> Feature<Name>Contract only
app composition root     -> Feature<Name>Contract + Feature<Name>
Feature<Name>            -> Feature<Name>Contract + Domain/Repository ports + CoreDesignSystem (+ Feature<Name>UI when extracted)
Feature<Name>UI          -> Feature<Name>Contract + Domain/Repository ports + CoreDesignSystem
Feature<Name>TestSupport -> Feature<Name>Contract (+ pure model targets) only
Feature<Name>Contract   -X-> Feature<Name> or Feature<Name>UI
Feature<Name>UI         -X-> Feature<Name>
```

## Destination And Holder Naming

Keep `Route` strictly a **noun for navigation identity** in `*Contract`, never a
SwiftUI container view:

| Owner | Name | Target |
| --- | --- | --- |
| Destination identity & arguments (`Hashable`, `Codable`, `Sendable`) | `ProfileRoute` | `FeatureProfileContract` |
| Public route events & completion results | `ProfileEvent`, `ProfileResult` | `FeatureProfileContract` |
| Destination-to-view registration / builder | `ProfileDestinationBinding` / `profileDestination(...)` | `FeatureProfile` |
| Stateful holder view (wires store/ViewModel & effects) | `ProfileScreen` | `FeatureProfile` (or `FeatureProfileUI`) |
| Stateless rendering surface (values + closures only) | `ProfileContent` | `FeatureProfile` (or `FeatureProfileUI`) |

Minimal Swift contract and implementation split:

```swift
// Sources/FeatureProfileContract/ProfileID.swift
public struct ProfileID: Hashable, Codable, Sendable {
    public let rawValue: String
    public init(_ rawValue: String) { self.rawValue = rawValue }
}

// Sources/FeatureProfileContract/ProfileRoute.swift
public struct ProfileRoute: Hashable, Codable, Sendable {
    public let id: ProfileID
    public init(id: ProfileID) { self.id = id }
}

// Sources/FeatureProfileContract/ProfileEvent.swift
public enum ProfileEvent: Equatable, Sendable {
    case backRequested
    case openedSettings(ProfileID)
}
```

```swift
// Sources/FeatureProfile/ProfileScreen.swift
import FeatureProfileContract
import SwiftUI

public struct ProfileScreen: View {
    @State private var viewModel: ProfileViewModel
    private let onEvent: (ProfileEvent) -> Void

    public init(
        route: ProfileRoute,
        repository: any ProfileRepository,
        onEvent: @escaping (ProfileEvent) -> Void
    ) {
        _viewModel = State(initialValue: ProfileViewModel(route: route, repository: repository))
        self.onEvent = onEvent
    }

    public var body: some View {
        ProfileContent(
            state: viewModel.state,
            onAction: { action in viewModel.send(action, onEvent: onEvent) }
        )
        .task { await viewModel.load() }
    }
}

// Sources/FeatureProfile/ProfileContent.swift
struct ProfileContent: View {
    let state: ProfileUiState
    let onAction: (ProfileAction) -> Void
    var body: some View { /* pure rendering only */ }
}
```

A peer feature that pushes `ProfileRoute(id: ...)` onto a `NavigationPath` or
emits `.openProfile(id)` imports `FeatureProfileContract` alone and never
recompiles when `ProfileScreen`, `ProfileContent`, or `ProfileViewModel` changes.

## Resources And `Bundle.module`

- Put assets, string catalogs (`.xcstrings`), Fonts, and JSON fixtures in the
  target that owns their contract (`CoreDesignSystem` for shared tokens/icons,
  `Feature<Name>` for feature-only copy/media).
- Access SPM target resources through `Bundle.module` inside that target and
  expose typed Swift symbols or views (`DesignSystemAsset.logo`, localized view
  helpers) rather than leaking `public let moduleBundle = Bundle.module` unless
  callers genuinely need bundle lookup.
- Never call `Bundle.main` inside a library target to load package-owned assets;
  previews, `swift test`, extensions, and CLI hosts have a different main bundle.

## Pre-Code Boundary Packet

Before adding a `Package.swift` target, Xcode target, or cross-target move,
record:

```text
target boundary:
products vs internal targets:
access level (internal / package / public):
allowed imports:
forbidden imports:
first caller or test:
nearest verification:
collapse rule:
```

Stop and keep code in the existing target if you cannot name both a real caller
that compiles against the narrower boundary and a concrete forbidden import.
