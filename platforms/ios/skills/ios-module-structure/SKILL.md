---
name: ios-module-structure
description: "iOS Module Structure: Use when deciding iOS targets, local Swift packages, feature folders, package layout, access control, public contracts, or where new SwiftUI/UIKit code should live."
keyflow_id: sys_platforms_ios_ios_module_structure_md_skill
status: review
type: ai-generated
metadata:
  internal: true
---

# iOS Module Structure

This card owns iOS target vs local Swift package selection, App Extension /
Widget / App Clip / Watch target slices, Xcode target membership, and SwiftUI or
UIKit feature layout. It refines
[swift-code-structure](../../../swift/skills/swift-code-structure/SKILL.md) and
[package-module-boundaries.md](../../../../common/nodes/package-module-boundaries.md)
for Apple app projects.

## Steps

1. **Inspect the Xcode / package topology.** Read the workspace or `.xcodeproj`
   targets, `Project.swift` / `project.yml` if Tuist or XcodeGen is used, local
   `Packages/*/Package.swift` manifests, and one existing feature slice.
   Repo-local target names and conventions win.
2. **Apply the Swift visibility truth.** Folders or Xcode groups inside one app
   or framework target share `internal` visibility and enforce no compiler
   boundary. Promote to a separate target or local Swift package target when an
   App Extension, Widget, App Clip, Watch target, sibling feature, or test suite
   needs an enforced contract or dependency isolation.
3. **Choose the smallest boundary.** Read
   [current-guidance.md](references/current-guidance.md) and
   [package-boundaries.md](../../../swift/skills/swift-code-structure/references/package-boundaries.md)
   before splitting targets (`Feature<Name>Contract` + `Feature<Name>` +
   optional `Feature<Name>UI` + `Feature<Name>TestSupport`).
4. **Separate destination data from holder and view.** Keep `*Route` as pure
   `Hashable` / `Codable` / `Sendable` navigation value data (in `*Contract`
   when split), `*Screen` (SwiftUI) or `*ViewController` + `*Coordinator`
   (UIKit) as the stateful holder in the implementation target, and `*Content`
   as the stateless rendering view.
5. **Audit root folders and target membership.** Read
   [package-layout-and-migration.md](../../../swift/skills/swift-code-structure/references/package-layout-and-migration.md)
   before adding folders or moving files. Keep root folders to the entry surface
   and remove duplicate Xcode target memberships in the same slice.

## Do Not

- Compile Widgets, App Extensions, App Clips, or Watch targets against the `App`
  target or heavy UIKit/SDK feature implementations instead of narrow
  `*Contract`, `DesignSystem`, and capability targets.
- Call the stateful SwiftUI holder `ProfileRoute.swift` while also defining a
  `ProfileRoute` navigation value.
- Leave moved `.swift` files or resources compiled into two Xcode/SPM targets,
  or leave a root folder half-migrated after adding a role folder.

## Stop If

- You cannot name the caller, extension target, build boundary, or SDK leak that
  justifies a new Xcode or local Swift package target.
- Moving files changes bundle lookup (`Bundle.main` vs `Bundle.module`),
  entitlements, or `@MainActor` isolation without a migration plan.

## Verification

- Build each touched app, extension, and Swift package target plus at least one
  consumer; compile navigating or extension callers against `*Contract` alone
  when a contract target changed.
- Run forbidden-import and duplicate target-membership checks from
  [current-guidance.md](references/current-guidance.md).

## Report

- Chosen boundary (app folder | local Swift package target | `Contract` + impl |
  `Contract` + impl + `UI` | capability package) and the caller or extension
  target that justifies it.
- Added/removed target dependencies, Xcode membership cleanups, and root-folder
  audit outcome.

When changing routing, confirm it selects this entrypoint. When changing
guidance, validate links and frontmatter.
