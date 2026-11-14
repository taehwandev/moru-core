---
keyflow_id: sys_ios_module_structure
status: review
type: human-reviewed-needed
---

# iOS Module Structure

Use when deciding iOS targets, local Swift packages, feature folders, package
layout, access control, public contracts, or where new SwiftUI/UIKit code should
live.

For Swift-wide package, file ownership, access control, public API, and target
split rules, also use `platforms/swift/skills/swift-code-structure/SKILL.md`
(`platforms/swift/skills/swift-code-structure/references/package-boundaries.md`
and `platforms/swift/skills/swift-code-structure/references/package-layout-and-migration.md`)
together with `common/nodes/package-module-boundaries.md`.
For Swift app architecture and design-system ownership, also use
`platforms/swift/skills/swift-architecture/SKILL.md` and `platforms/swift/skills/swift-design-system/SKILL.md`.

This card follows current Apple guidance: local Swift packages and targets can
improve modularity, reuse, and maintenance, but they are useful only when they
protect real ownership and dependency boundaries.

References:

- Organizing code with local packages:
  `https://developer.apple.com/documentation/xcode/organizing-your-code-with-local-packages`
- Swift PackageDescription:
  `https://developer.apple.com/documentation/packagedescription`
- SwiftUI model data:
  `https://developer.apple.com/documentation/swiftui/managing-model-data-in-your-app`
- Xcode previews:
  `https://developer.apple.com/documentation/xcode/previewing-your-apps-interface-in-xcode`

## Default Rule

Start with the smallest owner boundary that works:

```text
private/fileprivate type -> internal feature folder -> feature target
-> local Swift package target -> shared package -> public package/API
```

Use a folder or target until another caller, app extension, dependency, build,
test, or release boundary needs a module. Do not create Swift packages only to
mirror an architecture diagram.

## Module Families

Use repo-local names first. A mature iOS app commonly separates these families:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| App target | App entry point, scene setup, app lifecycle, dependency assembly, top-level navigation, entitlements. | Feature implementation details, repositories, reusable UI primitives. |
| Feature folder/target | SwiftUI screens, UIKit controllers, coordinators, ViewModels, feature display models, feature-local views. | Shared design primitives, API clients, persistence internals, global app state. |
| Feature contract target | Route contracts, coordinator interfaces, small caller-facing models, feature entry factory. | Views, ViewModels, API clients, heavy SDK dependencies. |
| Design system package | Theme, tokens, reusable controls, feedback views, accessibility contracts, preview fixtures. | Product routes, analytics names, permission policy, repository calls. |
| Domain package | Product rules, use cases, entities, policies that are reused or risky enough to test independently. | SwiftUI/UIKit types, DTOs, URLSession/Core Data details, app navigation. |
| Data package | Repository protocols, repository implementations, DTO mapping, persistence, cache, network clients. | Screen state, coordinators, product UI copy. |
| Platform/adapters package | Keychain, files, notifications, permissions, StoreKit, HealthKit, camera, location, WebKit, app extensions. | Feature-specific decisions or hidden global state. |
| Test support package | Fakes, fixtures, preview/sample data, snapshot helpers, deterministic schedulers/clocks. | Production-only behavior that app code must depend on at runtime. |

Prefer local Swift packages for code that should compile independently, be
shared across targets, or hide dependencies. Prefer app or feature targets when
the code is app-specific and strongly tied to Xcode target settings.

## Split Decision

Keep a feature as folders in the app target when:

- only one app target owns it
- no extension, widget, test helper, or other feature needs the contract
- implementation dependencies are already acceptable to the app target
- the feature boundary is still changing quickly
- previews and tests can run without extra target wiring

Create a feature target or local package when:

- another feature, app extension, widget, watch target, or test target must
  compile against a stable contract
- the feature has heavy SDKs or platform frameworks that should not leak to
  callers
- the split shortens compile scope or isolates generated resources
- the feature can be reused or replaced by a fake/dev implementation
- target membership is becoming error-prone

Create a contract target/package only when:

- callers need route or entrypoint contracts without implementation dependencies
- the implementation can change, move, or be replaced without changing callers
- the public surface can stay much smaller than the feature implementation

## Dependency Direction

Keep dependencies acyclic:

```text
App target
  -> feature contracts and selected feature implementations
Feature implementation
  -> own contract, design system, domain, repository protocols, platform adapters
Feature contract
  -> stable route/data contracts and lightweight shared types only
Domain
  -> repository protocols and pure policies
Data implementation
  -> repository protocols, URLSession/Core Data/SwiftData/Keychain adapters, DTOs
Design system
  -> visual primitives, resources, tokens, accessibility contracts
```

Forbidden edges:

- feature contract -> feature implementation
- domain -> SwiftUI, UIKit, AppKit, DTO, persistence row, or SDK type
- design system -> feature, repository, app route, analytics, or permission policy
- repository protocol -> repository implementation
- feature implementation -> another feature implementation when a contract can
  express the dependency

## Swift Access Control

Use Swift access control as part of the boundary:

- `private` and `fileprivate` for unstable implementation helpers.
- `internal` for feature-local collaborators inside one target.
- `package` for package-internal collaboration when the repo uses Swift package
  access control and the API should not escape the package.
- `public` only for app-facing package APIs, cross-target contracts, or SDK-like
  surfaces.
- `open` only when subclassing outside the module is an intentional contract.

Do not make a type `public` just to fix a preview or test. Prefer testable
imports, fixture targets, public factory functions, or moving the test closer to
the owner boundary.

## Feature Layout

Use `platforms/swift/skills/swift-code-structure/SKILL.md` for cross-platform Swift file and type
ownership. These iOS examples show common target-local shapes.

Apply the Swift file baseline strictly in iOS features: one primary screen,
view model, coordinator, state type, repository contract, adapter, fixture, or
assertion owner per file by default.

Review must fail when an iOS runtime file keeps independently importable or
reviewable owners together: SwiftUI views, UIKit view controllers, coordinators,
data sources, cells, state owners, repositories, services, adapters, preview
fixtures, or assertion helpers.

Do not:

- Put a SwiftUI screen, ViewModel, UiState, route, repository call, mapper, and
  preview fixture in one file because they belong to one feature.
- Keep UIKit coordinator, view controller, data source, cell, service, and
  adapter declarations in one file when they can be tested or reviewed
  independently.
- Use extensions, nested types, or broad `Common`/`Helpers` files to hide mixed
  UI, state, data, platform, and testing responsibilities.

For SwiftUI features (keep `*Route` as pure destination data in `*Contract` when
split, `*Screen` as stateful holder, and `*Content` as pure rendering):

```text
Sources/FeatureProfileContract/
  ProfileRoute.swift          pure Hashable/Codable/Sendable destination + args
Sources/FeatureProfile/
  ProfileScreen.swift         stateful SwiftUI holder + ViewModel/store binding
  ProfileContent.swift        pure stateless rendering view
  ProfileViewModel.swift      @MainActor state owner (or TCA @Reducer)
  ProfileUiState.swift        state, actions, effects, display models
  ProfileDestinationBinding.swift  navigationDestination registration for App
  Components/                 feature-local subviews (2+ callers inside feature)
  PreviewData/                deterministic preview fixtures
Tests/FeatureProfileTests/
```

When the feature stays inside a single app target before any split is earned,
keep the same file-naming separation (`ProfileRoute.swift` value vs
`ProfileScreen.swift` holder vs `ProfileContent.swift` view) so later extraction
into `FeatureProfileContract` + `FeatureProfile` requires zero type renames.

For UIKit features:

```text
Features/Members/
  MembersCoordinator.swift
  MembersViewController.swift
  MembersViewModel.swift
  MembersUiState.swift
  MembersDataSource.swift
  Cells/
  Views/
  Tests/
```

For local Swift packages, keep `Package.swift` `products:` narrower than
internal `targets:`, use `package` access across sibling targets inside the same
package when supported, and only extract `Feature<Name>UI` when a named consumer
outside `Feature<Name>` (for example a Widget, App Clip, or sibling feature)
renders the concrete SwiftUI view without its ViewModel:

```text
Packages/AppModules/Package.swift
Packages/AppModules/Sources/
  FeatureProfileContract/     exported product for navigating/extension callers
  FeatureProfile/             implementation target wired by App composition root
  FeatureProfileUI/           optional: only when Widget/AppClip/sibling renders it
  DesignSystem/
  FeatureProfileTestSupport/  fakes/fixtures for consumer tests
Packages/AppModules/Tests/
  FeatureProfileTests/
```

## Extension, Widget, App Clip, And Watch Slices

Apple extension targets have strict binary size, memory, entitlement, and API
constraints (`UIApplication.shared` unavailable in extensions):

- Compile Widgets, Live Activities, Intents, Share Extensions, App Clips, and
  Watch targets against narrow `*Contract`, `Core<Capability>`, `DesignSystem`,
  and optional `*UI` targets — never against the main `App` target or full
  UIKit/SDK-heavy feature implementation targets.
- Share Keychain, App Group `UserDefaults`, or SwiftData/SQLite container paths
  through a small `CoreStorage` or `CoreSession` capability target rather than
  duplicating entitlement strings across targets.
- When Xcode 16+ file-system synchronized groups, Tuist (`Project.swift`), or
  XcodeGen (`project.yml`) manage target membership, verify that moving a file
  into a local Swift package removes it from the app/extension synchronized
  folder so the symbol is never compiled into two modules.

## Root Folder Audit And Complete Role Moves

Apply `common/nodes/package-module-boundaries.md` when a target or feature root
accumulates ~20+ `.swift` files or mixes three or more roles (views, state
owners, mappers, repositories/clients, platform adapters):

- Keep only the public entry surface and compact flow root in the target root.
- Split large features **by user flow first** (`Checkout/`, `OrderHistory/`),
  then by role; split data/domain targets **by capability first** (`Auth/`,
  `Catalog/`), then by role.
- When introducing a role subfolder (`Components/`, `Mappers/`, `Policy/`), move
  **all** existing root files of that role in the same change — never leave a
  half-applied split.
- Ban `Common/`, `Shared/`, `Utils/`, `Helpers/`, and `Misc/` targets or folders.

## Migration Strategy

When modernizing an old iOS feature:

1. Record target membership, imports, `Bundle.main` vs `Bundle.module` resource
   lookups, entitlements, and package dependencies before moving files.
2. Extract stable `*Route` contract, repository protocol, or adapter protocol
   targets before moving implementation, and verify navigating or extension
   callers compile against `*Contract` alone.
3. Make previews and unit tests pass against the new contract first.
4. Move implementation in a complete role/slice move so the host target shrinks
   rather than gaining permanent forwarding shims.
5. Keep behavior changes out of the module move unless required for Swift
   concurrency (`Sendable` / `@MainActor`) or bundle correctness.
6. Remove old Xcode target membership, duplicate resources, and unused
   `Package.swift` target dependencies in the same slice, and run `rg` import
   checks for forbidden cross-feature implementation imports.

## Review Checklist

- Is a folder, target, or Swift package the lowest boundary that protects the
  real owner?
- Does every contract target/package have at least one caller that benefits from
  avoiding the implementation dependency?
- Are `public` and `open` APIs intentionally part of the caller contract?
- Are SwiftUI/UIKit, DTO, persistence, SDK, and app-route types kept out of
  domain and repository contracts?
- Are resources, bundle lookup, localization, previews, and test fixtures owned
  by the module that uses them?
- Are app extensions, widgets, watch targets, and previews importing only the
  contracts they need?
