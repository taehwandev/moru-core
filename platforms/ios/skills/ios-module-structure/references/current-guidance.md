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
split rules, also use `platforms/swift/skills/swift-code-structure/SKILL.md`.
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

For SwiftUI features:

```text
Features/Profile/
  ProfileRoute.swift          dependency and navigation wiring
  ProfileScreen.swift         pure rendering
  ProfileViewModel.swift      state owner and intents
  ProfileUiState.swift        state, actions, effects, display models
  Components/                 feature-local views
  PreviewData/                deterministic preview fixtures
  Tests/
```

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

For local Swift packages, keep the package manifest explicit:

```text
Package.swift
Sources/
  FeatureProfile/
  FeatureProfileContract/
  DesignSystem/
Tests/
  FeatureProfileTests/
```

## Migration Strategy

When modernizing an old iOS feature:

1. Record target membership, imports, resources, entitlements, and package
   dependencies before moving files.
2. Extract stable route, state, repository, or adapter protocols before moving
   implementation.
3. Make previews or tests pass against the new contract first.
4. Move implementation in the smallest reviewable slice.
5. Keep behavior changes out of the module move unless they are required to make
   the boundary correct.
6. Remove old target membership and duplicate resources only after the new owner
   compiles and previews/tests run.

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
