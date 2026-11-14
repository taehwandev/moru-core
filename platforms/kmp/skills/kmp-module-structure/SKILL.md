---
name: kmp-module-structure
description: "KMP Module Structure: Use when deciding Kotlin Multiplatform shared modules, source sets, Gradle module boundaries, umbrella frameworks, expect/actual placement, or package layout."
keyflow_id: sys_platforms_kmp_kmp_module_structure_md_skill
status: review
type: ai-generated
metadata:
  internal: true
---

# KMP Module Structure

Use for multiplatform modules, source sets, Gradle edges, `api`/`impl`/`ui`
module splits, build logic, `expect`/`actual` placement, or package layout,
including desktop JVM and Compose Multiplatform targets. Not for Android-only
projects.

## Steps

1. **Detect repo conventions.** Read `settings.gradle(.kts)`, `build-logic`,
   shared module families, source-set hierarchy, iOS umbrella framework config,
   and one neighbouring feature.
2. **Choose the smallest boundary.** Read
   [package-module-boundaries.md](../../../../common/nodes/package-module-boundaries.md)
   and [current-guidance.md](references/current-guidance.md) before creating or
   splitting modules (`single shared module -> feature module -> api + impl ->
   api + impl + ui -> core:<capability> -> iOS umbrella`).
3. **Keep navigation contracts separate from holders.** When splitting a shared
   feature into `api` + `impl`, keep pure serializable `*Route` contracts in
   `api`, stateful `*Screen` / `*Entry` + `*StateHolder` / `*ViewModel` in
   `impl`, and stateless `*Content` in `impl` (or `ui` only for a named external
   consumer).
4. **Audit package layout across source sets.** MUST read
   [package-layout.md](references/package-layout.md) before adding or moving
   packages. Mirror one package tree across `commonMain` and target source sets
   with `actual` beside `expect`.
5. **Verify dependency edges.** Check Gradle `dependencies` blocks and Kotlin
   imports so no caller depends on `impl` when `api` suffices and no unused
   project edge remains.

## Do Not

- Invent `android/`, `ios/`, `desktop/`, or `common/`, `shared/`, `utils/`
  packages inside source sets.
- Add a role subpackage without moving all existing root files of that role.
- Introduce Kotlin `typealias` in shared or target source sets instead of named
  value classes, interfaces, or data classes.

## Stop If

- You cannot name the caller, target slice, or iOS export boundary that
  justifies a new module or source set.
- Moving packages breaks `internal` visibility, `expect`/`actual` package
  matching, or exported Swift framework types without a migration plan.

## Verification

- Compile every affected target (`commonMain` + platform targets) and confirm
  each declared Gradle `project(...)` dependency has a matching import and zero
  forbidden `impl` imports remain.

## Report

- Chosen module/source-set shape, named caller or target boundary, Gradle edges
  added/removed, and root-package audit result.
