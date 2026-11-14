---
name: swift-code-structure
description: "Swift Code Structure: Use when deciding Swift Package Manager layout, Package.swift products and targets, Xcode targets, feature folders, file ownership, access control, Contract/Impl/UI splits, or where new Swift code should live."
keyflow_id: sys_platforms_swift_swift_code_structure_md_skill
status: review
type: ai-generated
metadata:
  internal: true
---

# Swift Code Structure

This card owns where Swift code lives across iOS, macOS, watchOS, tvOS, CLI,
and server/library packages: folder vs SPM target vs Xcode target,
`Package.swift` product/target boundaries, `*Contract`/`*Feature`/`*UI` splits,
access control (`private` through `package` and `public`), and target moves.

## Steps

1. **Detect the repo's convention.** Inspect `Package.swift` manifests, local
   `Packages/`, `.xcodeproj`/`.xcworkspace`, Tuist/XcodeGen manifests
   (`Project.swift`, `project.yml`), and one neighbouring feature. Repo-local
   naming and DI/state style win when already consistent.
2. **Apply Swift's folder-vs-target truth.** Folders inside one Swift target
   share a single `internal` module namespace and enforce **zero** compiler
   import boundary. Use folders for flow/role ownership inside a cohesive
   target, and create `Package.swift` targets when dependency direction,
   visibility, build scope, or extension reuse must be compiler-enforced.
3. **Choose the smallest boundary.** Walk the shared ladder from
   [package-module-boundaries.md](../../../../common/nodes/package-module-boundaries.md)
   and stop at the first rung a named caller needs:
   `private/fileprivate -> flow/role folder -> unsplit feature target
   -> Contract + Feature (api + impl) -> Contract + Feature + UI
   -> Core<Capability> -> public package`. MUST read
   [package-boundaries.md](references/package-boundaries.md) before adding or
   reshaping `Package.swift` products/targets or public/package contracts.

   | Proven need | Smallest Swift shape |
   | --- | --- |
   | Behavior stays inside one app or feature target | flow/role folder in existing target |
   | Peer feature, extension, widget, CLI, or test must compile against contract alone | `Feature<Name>Contract` + `Feature<Name>` |
   | A named outside host renders the same concrete UI without platform entry wiring | `Feature<Name>Contract` + `Feature<Name>` + `Feature<Name>UI` |

4. **Place ownership and access control.** `*Contract` owns `<Name>Route`
   (destination value), route events/results, factory/port protocols, and small
   models; `*Feature` owns `<Name>Screen` (stateful holder), `@MainActor` state
   owner/reducer, `<Name>Content` (stateless view), mappers, `Bundle.module`
   resources, and destination-to-screen binding. Prefer Swift `package` access
   (Swift 5.9+, SE-0386) between sibling targets of one `Package.swift` before
   widening to `public`, and mark implementation imports `internal import` /
   `private import` (Swift 6.0+, SE-0409) so SDK types do not leak.
5. **Audit folders and forbid half-splits.** MUST read
   [package-layout-and-migration.md](references/package-layout-and-migration.md)
   before adding folders, touching a target root with ~20+ files or 3+ roles,
   or moving existing files across targets.
6. **Verify dependency edges.** Forbidden: `*Contract -> *Feature/*UI`,
   `*UI -> *Feature`, navigating caller `-> *Feature/*UI`,
   `Domain -> SwiftUI/UIKit/AppKit/DTO/CoreData/SwiftData`,
   `Core* -> Feature*`, `DesignSystem -> Feature*/Data`, and extension/widget
   `-> App`. Run the `Package.swift` and `import` searches in
   [package-layout-and-migration.md](references/package-layout-and-migration.md).
7. **Split files.** Apply [current-guidance.md](references/current-guidance.md#file-and-type-ownership):
   one primary importable owner per `.swift` file and <=120 lines per block or
   `extension`.

## Source Map

| Need | Reference |
| --- | --- |
| Folder vs target visibility, file/extension split, access control | [current-guidance.md](references/current-guidance.md) |
| `Package.swift` products/targets, `Contract`/`Impl`/`UI`/`TestSupport`, `Route` naming, `Bundle.module` | [package-boundaries.md](references/package-boundaries.md) |
| Target folder layout, root-folder audit, migration end-state, edge verification, review checklist | [package-layout-and-migration.md](references/package-layout-and-migration.md) |
| Cross-platform boundary ladder and root-package audit | [package-module-boundaries.md](../../../../common/nodes/package-module-boundaries.md) |
| Swift state/domain/adapter architecture tracks | [swift-architecture](../swift-architecture/SKILL.md) |

## Do Not

- Treat subfolders (`Models/`, `Views/`, `Managers/`, `Services/`, `Utils/`)
  inside one giant target as package separation; every `internal` declaration
  in that target still sees every other one.
- Export every internal SPM target in `Package.swift` `products:`; expose only
  products that Xcode targets or external packages link directly.
- Name both destination data and a SwiftUI wrapper view `<Name>Route`.
- Widen types to `public` merely for previews, tests, or sibling SPM targets
  that can use `@testable import`, fixture factories, or `package` access.
- Leave a target root half-migrated with some files in `UI/` or `Mapper/` and
  older siblings of the same role still sitting at `Sources/<Target>/`.

## Stop If

- You cannot name the caller/target that needs the new SPM target or folder,
  plus at least one concrete forbidden import.
- Moving code out of the Xcode `App` target leaves the real screen/service in
  `App` behind undocumented glue.
- Widening `private`/`fileprivate` helpers to `internal` or `package` was not
  checked for same-name overload or extension collisions across the target.

## Verification

- Build the contract target alone (`swift build --target <ContractTarget>` or
  equivalent scheme), then build affected implementation/consumer targets and
  run focused `swift test` / `xcodebuild test` suites.
- Run the `Package.swift` dependency and Swift `import` searches from
  [package-layout-and-migration.md](references/package-layout-and-migration.md).

## Report

- Chosen Swift boundary: target folder | unsplit target | `Contract + Feature` |
  `Contract + Feature + UI` | `Core<Capability>` | public package.
- Named caller/extension/test that justifies it, and why a smaller boundary fails.
- `Package.swift` products/target edges added or removed, and access levels used.
- For moves: host/root files deleted vs added, `Bundle.module` ownership, and
  any remaining bridge with its removal condition.
