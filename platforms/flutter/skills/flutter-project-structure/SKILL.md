---
keyflow_id: sys_platforms_flutter_flutter_project_structure_md_skill
status: review
type: ai-generated
---

# Flutter Project Structure

Use when deciding Flutter feature folders, local Dart packages, pub workspace
or monorepo packages, plugin or federated plugin splits, package exports, or
where Dart and native (Kotlin/Swift) platform code should live.

Do not use for behavior inside an existing owner; use
`platforms/flutter/skills/flutter-architecture/SKILL.md` or the matching
widget/state card.

## Read

- `references/current-guidance.md` for the smallest-owner ladder, file split
  rules, project families, split decision, dependency direction, layouts, and
  migration strategy.
- `platforms/flutter/skills/flutter-architecture/references/reusable-layers.md`
  when the split is motivated by reuse across features or apps.
- `platforms/flutter/skills/flutter-platform-integration/references/mobile-native-bridges.md`
  when native code, generated channel code, or a plugin package is placed.

## Stop If

- A package split has no stable public export surface yet.
- Native setup would be scattered across app and package without a named owner.

## Verification

- Run package-level analyze/test for every moved package and one app-level
  build or smoke path for each affected target.
