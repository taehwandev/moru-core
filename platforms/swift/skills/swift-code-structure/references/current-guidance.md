---
keyflow_id: sys_swift_code_structure
status: review
type: human-reviewed-needed
---

# Swift Code Structure

Use when deciding Swift Package Manager layout, Xcode targets, feature folders,
file ownership, target membership, access control, public contracts, or where
new Swift code should live.

Also use:

- `common/skills/code-structure-ownership/SKILL.md` for generic ownership level,
  module split, and `api`/`impl` decisions.
- `common/skills/reusable-code-design/SKILL.md` before promoting Swift code into a
  shared package or public API.
- `common/skills/component-api-design/SKILL.md` before extracting reusable UI
  components.
- `platforms/swift/skills/swift-architecture/SKILL.md` for Swift app, state, domain, data, and adapter
  boundary choices.
- `platforms/swift/skills/swift-design-system/SKILL.md` for shared SwiftUI/UIKit/AppKit UI packages.

References:

- Swift declarations:
  `https://docs.swift.org/swift-book/documentation/the-swift-programming-language/declarations/`

## Default Boundary

Start with the lowest owner boundary that works:

```text
private/fileprivate helper -> internal file/folder -> target feature
-> local Swift package target -> shared package -> public package/API
```

Do not create a Swift package, target, protocol, or contract module only to
mirror an architecture diagram. Split when another caller, app extension,
widget, package, test target, dependency, build scope, or ownership line needs
the boundary.

## Target And Package Families

Use repo-local names first. Mature Swift apps and libraries commonly separate:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| App/executable target | Entry point, lifecycle, composition root, app route, scene/window setup, entitlements, top-level resources. | Feature internals, reusable UI primitives, repository implementations hidden from callers. |
| Feature target/folder | Screens/controllers, state owners, feature display models, feature-local views, feature commands. | Shared design tokens, app lifecycle, raw SDK clients, global state. |
| Feature contract target | Route contracts, command interfaces, entry factories, small caller-facing models. | Views, state owners, SDK dependencies, repository implementations. |
| Design system package | Theme, tokens, styles, reusable controls, feedback views, preview fixtures, accessibility contracts. | Product routes, analytics names, permissions, repositories, domain policy. |
| Domain package | Entities, product rules, policies, use cases, repository protocols. | SwiftUI/UIKit/AppKit types, DTOs, persistence rows, URLSession, SDK details. |
| Data package | Repository implementations, DTO mapping, persistence, cache, generated clients, network clients. | Screen state, navigation, product UI copy. |
| Platform adapters package | Keychain, files, notifications, permissions, StoreKit, HealthKit, camera, location, Accessibility, shell, clipboard, app extensions. | Feature-specific decisions or hidden global state. |
| Test support package | Fakes, fixtures, deterministic clocks/schedulers, preview/sample data, snapshot helpers. | Production-only behavior that app code must depend on at runtime. |

Prefer local Swift packages when code should compile independently, be reused
across targets, or hide dependencies. Prefer folders or Xcode targets when the
code is app-specific and strongly tied to target settings, resources, or
entitlements.

## File And Type Ownership

- Default to one primary public or internal top-level type per file when the
  type is imported, tested, previewed, or reviewed as a standalone owner. This
  includes classes, structs, enums, protocols, actors, views, view models,
  coordinators, repositories, adapters, fixtures, and assertion helpers.
- Keep tiny private helpers near their only caller. Move helpers out only when
  they gain a stable owner or multiple real callers.
- Use extensions to group protocol conformances, preview helpers, or small
  domain-specific APIs when it improves scanning. Do not scatter one type across
  many files without a clear reason.
- Keep individual Swift `extension` blocks within the 120-line structure review
  budget by splitting distinct private helper concerns into separate extensions,
  and pass `--structure-review-evidence` whenever editing a Swift file over 300 lines.
- Keep generated code, DTOs, persistence rows, fixtures, and production models
  in separate owners.
- Keep resources with the target or package that owns them. Package resources
  should use the package's resource bundle path instead of assuming `Bundle.main`.
- Keep preview data deterministic and separate from production services.
- Avoid catch-all `Utils`, `Common`, or `Extensions` folders unless each file
  has a clear responsibility and owner.

Review must fail when a Swift runtime file keeps multiple independently
importable owners in one file: classes, structs, enums, protocols, actors,
views, view models, coordinators, repositories, adapters, DTOs, mappers,
fixtures, or assertion helpers.

Do not keep multiple importable Swift types in one file because they are small,
created together, or used by the same feature. Exceptions should be narrow:
private helper types, a sealed-style enum/value family, or a tiny protocol
conformance extension that cannot be imported or reviewed independently.

## Type Aliases

Swift `typealias` is allowed when it makes a real Swift API easier to read
without hiding ownership:

- long generic shapes, closure signatures, and dictionary/result forms that
  would otherwise dominate call sites
- protocol-associated type conveniences inside protocol declarations
- package or public compatibility surfaces where callers already understand the
  underlying type

Do not use a Swift type alias when the concept needs a new nominal type,
stored invariants, validation, identity, access-controlled data, protocol
conformance, or security-sensitive separation. Use a `struct`, `enum`,
protocol, actor, or wrapper type for those cases.

## Access Control

Use Swift access control as part of the architecture:

- `private` for unstable helpers inside one declaration.
- `fileprivate` only when neighboring declarations in the same file need shared
  access.
- `internal` for collaborators inside one target or package target.
- `package` for package-internal APIs when the repo uses Swift package access
  control and the API should not escape the package.
- `public` for app-facing package contracts, cross-target APIs, or SDK-like
  surfaces.
- `open` only when subclassing outside the module is an intentional contract.

Do not make a type `public` only to satisfy previews or tests. Prefer moving
tests closer, using `@testable import`, providing public fixture factories, or
introducing a smaller public contract.

## Dependency Direction

Protect acyclic dependencies:

```text
App target
  -> feature contracts and selected feature implementations
Feature implementation
  -> own contract, design system, domain, data protocols, platform adapters
Feature contract
  -> stable route/data contracts and lightweight value types
Domain
  -> repository protocols and pure policies
Data implementation
  -> repository protocols, DTOs, generated clients, persistence, network
Design system
  -> visual primitives, resources, tokens, accessibility contracts
Platform adapters
  -> OS frameworks and SDK-specific implementations
```

Forbidden edges:

- feature contract -> feature implementation
- domain -> SwiftUI, UIKit, AppKit, DTO, persistence row, SDK, or route type
- design system -> feature, repository, app route, analytics, or permission
  policy
- repository protocol -> repository implementation
- shared utility -> feature implementation
- app extension/widget -> app-only implementation dependency when a smaller
  contract can express the need

## API / Implementation Split

Create a contract or `api` target only when at least one caller benefits from
avoiding implementation dependencies:

- route, command, factory, or repository contracts cross a target boundary
- multiple implementations can exist, such as fake/real, local/remote,
  app/extension, paid/free, or test/prod
- implementation dependencies are heavy, optional, platform-specific, or risky
  to leak to all callers
- the split removes a cycle, shortens build scope, or lets owners change
  independently

If no caller can use the contract without the implementation, keep the feature
local and revisit the split when pressure appears.

## Migration Recipe

When restructuring Swift code:

1. Inventory imports, target membership, package products, resources,
   entitlements, generated files, previews, and tests.
2. Name the current owner and intended owner before moving files.
3. Extract the smallest stable contract first: route, command, repository
   protocol, display model, use case, or adapter.
4. Compile or test the contract boundary before moving implementation.
5. Move one feature, target, package target, or resource owner at a time.
6. Keep behavior changes separate unless they are required to make the
   boundary correct.
7. Remove duplicate resources, old target membership, and compatibility shims
   only after the new owner is verified.

## Verification

For Swift structure changes:

- run the nearest Swift build, test, or Xcode wrapper for affected targets
- verify package products and target membership compile
- run focused tests for mappers, route resolution, repository contracts, or
  command wiring
- inspect final imports for forbidden dependencies
- verify resources, previews, localization, fixtures, and generated files are
  owned by the moved target or package
- report whether the chosen boundary is file-local, feature-local, target,
  package, contract, or public API, and why
