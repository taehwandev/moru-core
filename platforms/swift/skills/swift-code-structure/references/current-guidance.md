---
keyflow_id: sys_swift_code_structure
status: review
type: human-reviewed-needed
---

# Swift Code Structure

Use when deciding Swift Package Manager (`Package.swift`) layout, Xcode targets,
feature folders, file ownership, target membership, access control, public
contracts, or where new Swift code should live.

Also use:

- `common/nodes/package-module-boundaries.md` and
  `common/skills/code-structure-ownership/SKILL.md` for the shared boundary
  ladder, `api`/`impl`/`ui`/`assertions` contract, and root-folder audit.
- `common/skills/reusable-code-design/SKILL.md` before promoting Swift code into
  a shared target or public package API.
- `common/skills/component-api-design/SKILL.md` before extracting reusable UI.
- `platforms/swift/skills/swift-architecture/SKILL.md` for Swift state, domain,
  data, and platform-adapter architecture tracks.
- `platforms/swift/skills/swift-design-system/SKILL.md` for shared
  SwiftUI/UIKit/AppKit design-system packages.

References:

- Swift declarations and access control:
  `https://docs.swift.org/swift-book/documentation/the-swift-programming-language/declarations/`
- Swift PackageDescription:
  `https://developer.apple.com/documentation/packagedescription`

## Swift Folder Versus Target Contract

Unlike Kotlin/Java packages or TypeScript/Python file modules, **folders inside
a single Swift target create no compiler namespace or import boundary**: every
`internal` symbol in `Sources/MyTarget/**` is directly visible to every other
file in `MyTarget` without an `import`.

Apply both levels intentionally:

- **Folders inside one target** organize flows and owner roles for navigation,
  review scope, and `.agents/structure-rules.json` path gates when compile-time
  isolation is unnecessary. Never create repo-wide horizontal `Models/`,
  `Views/`, `ViewModels/`, `Managers/`, `Services/`, or `Utils/` folders.
- **SPM targets in `Package.swift`** (or distinct Xcode targets when target
  build settings/entitlements require them) are the unit of **compiler-enforced
  package separation** in Swift. Adding a target inside an existing local
  `Package.swift` is cheap; prefer a new target inside the workspace's local
  `Package.swift` over creating another standalone `Package.swift` repository.

## Default Boundary

Start with the lowest boundary that protects the real owner:

```text
private/fileprivate helper -> flow/role folder in target -> unsplit feature target
-> Feature<Name>Contract + Feature<Name> -> + Feature<Name>UI
-> Core<Capability> target -> public package product
```

Do not create an SPM target, protocol, or `*Contract` module only to mirror an
architecture diagram. Split targets when another feature, app extension, widget,
helper process, CLI, test target, heavy SDK dependency, or build scope needs a
compiler-enforced boundary. Canonical target contracts live in
[`package-boundaries.md`](package-boundaries.md).

## File And Type Ownership

- Default to **one primary `public`, `package`, or `internal` top-level owner
  per `.swift` file** when imported, tested, previewed, or reviewed on its own:
  `struct`, `class`, `actor`, `enum`, `protocol`, `@MainActor` model/ViewModel,
  `@Observable` model, `@Reducer` feature, SwiftUI `View`, `UIViewController`,
  `NSViewController`, coordinator, repository, adapter, DTO, mapper, fixture, or
  assertion helper.
- Leading attributes (`@MainActor`, `@Observable`, `@Reducer`, `@objc`,
  `@available`) do not merge separate owners; an `@MainActor final class
  ProfileViewModel` and `struct ProfileScreen: View` belong in separate files.
- Keep tiny `private` helpers near their single caller; use `fileprivate` only
  when same-file extensions or a sealed-style value family genuinely need it.
- Use `extension` blocks to group protocol conformances or focused private
  concern clusters, keeping each `extension` block within the 120-line review
  budget. Pass `--structure-review-evidence` whenever editing a Swift file over
  300 lines.
- Keep generated code, DTOs, persistence rows (`@Model`, `NSManagedObject`),
  production domain models, and preview/test fixtures in separate owners.
- Keep resources with the owning target and load package resources via
  `Bundle.module` (or a typed target-owned accessor), never assuming
  `Bundle.main` inside a Swift package target.
- Avoid catch-all `Utils`, `Common`, `Shared`, `Helpers`, `Managers`, or
  `Extensions` folders and files. Name extension files after the receiver and
  capability (`URLRequest+RetryHeaders.swift`, not `Extensions.swift`).

Review fails when a Swift runtime file keeps multiple independently importable
owners together because they are small or belong to the same feature.

## Type Aliases

Swift `typealias` is allowed for long generic/closure signatures, associated-type
conveniences, or documented compatibility shims where callers already intend the
same nominal type. Do not use `typealias` when the concept needs nominal
identity, invariants, validation, protocol conformance, or security separation
(for example `ProfileID` vs `WorkspaceID`); use a `struct`, `enum`, `actor`, or
`protocol`.

## Access Control And Import Visibility

Use Swift access levels and SE-0409 import modifiers to enforce boundaries:

- `private`: helpers inside one declaration and its same-file extensions.
- `fileprivate`: tightly coupled helpers shared only within one file.
- `internal` (default): collaborators inside a single target.
- `package` (Swift 5.9+, SE-0386): APIs shared across sibling targets declared
  in the same `Package.swift` without exposing them outside the package. Prefer
  `package` over `public` for local modularization inside one `Package.swift`.
- `public`: cross-package contracts, Xcode-app-facing library products, or
  published SDK APIs (requires explicit `public init` and member visibility).
- `open`: only when cross-module subclassing/overriding is an intentional API.
- Access-level on imports (Swift 6.0+, SE-0409; requires experimental flag
  `AccessLevelOnImports` on Swift 5.9): use `private import` or `internal import`
  for implementation SDKs, persistence, and transport modules so `public`
  contracts cannot accidentally expose transitive types; use `public import` only
  for contract modules whose types appear in `public` APIs.

Do not widen declarations to `public` only for SwiftUI `#Preview` or unit tests.
Keep `#Preview` in the owning UI target with deterministic fixtures, use
`package` access for sibling test/support targets, or use `@testable import` for
focused white-box unit tests.

## Topic References

- [`package-boundaries.md`](package-boundaries.md) — `Package.swift` products vs
  targets, `Contract`/`Feature`/`UI`/`TestSupport` split, `Route` vs `Screen`
  naming, `Core<Capability>` targets, `Bundle.module`, and pre-code packets.
- [`package-layout-and-migration.md`](package-layout-and-migration.md) — target
  folder trees, root-folder audit, complete role moves, dependency-edge searches,
  Xcode-to-SPM migration hazards, and the Swift structure review checklist.
