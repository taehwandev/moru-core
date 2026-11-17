---
keyflow_id: sys_swift_package_layout_and_migration
status: review
type: ai-generated
---

# Swift Target Folder Layout, Edge Verification, And Migration

Use when organizing folders inside a Swift target, auditing a flat `Sources/`
directory, verifying `Package.swift` and `import` edges, or moving Swift code
out of an oversized Xcode `App` target or monolithic package.

## Target-Internal Folder Gate And Root Audit

Because Swift folders do not create compiler namespaces, an undisciplined target
quickly turns `Sources/<Target>/` into either one 40-file flat directory or
horizontal type buckets (`Models/`, `Views/`, `ViewModels/`, `Managers/`,
`Utils/`). Both hide ownership.

Run the **Root Folder Audit** from
`common/nodes/package-module-boundaries.md` when any of these holds:

- `Sources/<Target>/` (or an Xcode target root) holds more than ~20 `.swift`
  files at one level.
- One folder mixes three or more roles: SwiftUI/UIKit/AppKit views, unrelated
  state owners, mappers, repositories/clients/DTOs, parsers, OS framework
  adapters, and string/fixture tables.
- Several root files share a flow prefix (`Checkout*`, `Workspace*`,
  `Onboarding*`) while another flow already has a subfolder.

Keep only the target's public/package entry surface at the target root; organize
internals by **flow first, then role** (for features) or **capability first,
then role** (for domain/data/platform):

### Feature target (`Sources/Feature<Name>/`)

```text
Sources/Feature<Name>/
  <Name>Screen.swift              stateful holder entry
  <Name>ViewModel.swift           state owner (or <Name>Reducer.swift)
  <Name>UiState.swift             UiState, Action, Effect beside state owner
  <Name>DestinationBinding.swift  route-to-screen registration for host
  UI/
    <Name>Content.swift           stateless screen surface
    Sections/                     distinct screen regions when needed
    Components/                   feature-local controls shared by 2+ views
  Mapper/                         domain -> display mapping when unit-tested
  Policy/                         pure feature rules when unit-tested
  <Subflow>/                      for multi-screen features: flow-first split
                                  holding its own state owner + UI/
  PreviewFixtures/                shared deterministic preview fixtures
  Resources/                      target-owned .xcstrings and assets
```

### Data, Domain, And Platform capability targets

```text
Sources/Domain/
  <Capability>/                   entities, value types, policies, ports

Sources/Data/
  <Capability>/
    Repository/                   *RepositoryImpl coordinating sources
    Remote/                       HTTP/WebSocket client + wire DTOs
    Local/                        SwiftData/CoreData/SQLite/file store + rows
    Mapper/                       DTO/row <-> domain entity mapping

Sources/CoreDesignSystem/
  Theme/
  Tokens/
  Components/<Group>/             Buttons, Inputs, Feedback, Navigation, Layout
  PreviewCatalog/
```

Folder rules:

- **Complete every role move**: if you create `UI/`, `Mapper/`, or `Remote/`,
  move **all** existing root files of that role in the same change. Never leave
  a half-split target where two views sit in `UI/` and five remain in root.
- Do not create `State/` or `Contract/` subfolders inside a feature only to
  collect three internal UDF structs; keep them next to their state owner.
- Collapse one-file subfolders that share the parent folder's import rule.
- Encode folder import boundaries in `.agents/structure-rules.json` when a
  single target is intentionally kept unsplit (`Domain/**` forbids `SwiftUI`,
  `UIKit`, `AppKit`; `UI/**` forbids `URLSession`, `SwiftData`, `CoreData`).

## Dependency Edge Verification

Run these checks for every change that edits `Package.swift`, Xcode target
dependencies, or cross-target Swift `import` statements:

1. Inspect the resolved target graph or `Package.swift` `dependencies:` blocks:
   - `*Contract` targets must not depend on `*Feature`, `*Impl`, `*UI`, or
     `Data*` implementation targets.
   - `*UI` targets must not depend on `*Feature`/`*Impl` targets.
   - `Core*` and `DesignSystem` targets must not depend on `Feature*` targets.
   - `*TestSupport` / `*Assertions` targets must depend on `*Contract` / pure
     models, not production `*Feature` or `Data*` implementations.
2. Search Swift imports across changed and consumer targets (`rg`):
   - `rg "^(\s*@\w+\s+)*(\s*(public|package|internal|fileprivate|private)\s+)?import\s+" Sources App`
   - Verify `Domain` files contain zero imports of `SwiftUI`, `UIKit`, `AppKit`,
     `CoreData`, `SwiftData`, `WebKit`, or transport SDKs.
   - Verify navigating peer features import `Feature<Name>Contract` only.
   - Verify every target dependency declared in `Package.swift` is backed by a
     matching `import <Target>`, `#externalMacro(module: "<Target>", ...)`, C
     umbrella/modulemap usage, or build-tool `plugins:` reference in
     `Sources/<Target>/` before pruning unused target edges.
3. Verify access leakage: `public` APIs in `*Feature` or `Core*` should use
   `internal import` / `private import` (Swift 6.0+, SE-0409) for internal SDK
   dependencies rather than `public import` of implementation modules.

## Migration Recipe And End-State Gate

When extracting local Swift packages or splitting an oversized Xcode `App` /
monolithic target:

1. **Search first**: check existing targets for an equivalent route, protocol,
   model, or component; converge callers instead of creating duplicates.
2. **Record the pre-edit gate**: baseline target/files, destination target,
   switching callers, why folder-only fails, and parity check.
3. **Extract `*Contract` or pure `Domain` types first** and compile
   `swift build --target <ContractTarget>` before moving UI or adapters.
4. **Apply Copy-First parity for UI moves**: move SwiftUI/UIKit/AppKit views
   with zero visual or behavioral edits first (changing only `import`, access
   modifiers, and `Bundle.module`), then verify previews/tests before refactoring.
5. **Check the End-State Gate**:
   - The host `App` target (or monolith root) must **lose** the moved files and
     target membership in `.xcodeproj` / `Package.swift`.
   - Count host files deleted vs added. If `App` net-grew by adding glue/wrapper
     types while screens/services stayed in `App`, report a **partial migration**
     and annotate every bridge file with what still moves and when it is deleted.

## Swift Split Hazards

- **Widening `private`/`fileprivate` to `internal` or `package`**: because every
  file in a Swift target shares one namespace, widening two `private func
  formatted(...)` helpers or `private extension View` modifiers in different
  files causes immediate redeclaration or overload ambiguity across the target.
  Search `Sources/<Target>/` (`rg "func <name>\b|extension .*<name>"`) and
  deduplicate before widening visibility.
- **Synthesized `init` and member visibility**: moving a `struct` to another
  target requires explicit `package init` or `public init` and matching property
  visibility; Swift's synthesized memberwise `init` is `internal` at most.
- **Swift 6 strict concurrency across target boundaries**: cross-target route
  values, models, events, and repository ports must explicitly conform to
  `Sendable` where async/actor boundaries cross targets, and UI-bound protocols
  should declare `@MainActor` at the protocol or method contract rather than
  forcing `nonisolated(unsafe)` workarounds in callers.
- **Silent `Bundle.main` and `@objc` / Storyboard / SwiftData lookup breaks**:
  moving resources, `.xcstrings`, CoreData `.xcdatamodeld`, or nibs into an SPM
  target changes their runtime bundle (`Bundle.module`) and module-qualified
  class names. Update bundle lookups and test resource loading explicitly.
- **Duplicate Xcode target membership**: when moving a file from `App` into a
  local package under `Packages/`, remove its `PBXBuildFile` entry from the
  Xcode target so the type is not compiled into both binaries.

## Review Checklist

- Does every new `Package.swift` target have a named caller/extension/test that
  cannot be served by a folder inside an existing target?
- Are internal modularization targets kept out of `Package.swift` `products:`
  and using `package` access where external linkage is unnecessary?
- Can a navigating peer feature compile against `Feature<Name>Contract` alone?
- Does `<Name>Route` name only the destination value in `*Contract`, never a
  SwiftUI/UIKit holder view?
- Does `Sources/<Target>/` root hold only the entry surface once 3+ roles or
  ~20+ files exist, with zero half-applied role folders?
- Were `Package.swift` target edges and Swift `import` directions verified with
  search output, and are unused target dependencies removed?
- Are package resources loaded through `Bundle.module`, and did the host `App`
  target shrink on a module extraction?
