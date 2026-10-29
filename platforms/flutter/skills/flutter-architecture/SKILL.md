---
name: flutter-architecture
description: "Flutter Architecture: Use for Flutter apps, Dart packages, widgets, navigation, state management, repositories, platform channels, plugins, mobile/desktop/web targets, and shared UI/data architecture."
keyflow_id: sys_platforms_flutter_flutter_architecture_md_skill
status: review
type: ai-generated
metadata:
  internal: true
---

# Flutter Architecture

Use when a Flutter change creates or moves a layer, feature slice, state owner,
repository, use case, platform service, composition root, or navigation shell,
or when shared Dart code must stay reusable across features, apps, or targets.

Do not use for a widget-only visual change (start with
`platforms/flutter/skills/flutter-widget-ui/SKILL.md`) or for pure
package/folder placement (start with
`platforms/flutter/skills/flutter-project-structure/SKILL.md`).

## Read

- `references/current-guidance.md` for the layer direction, rules, refactor
  signals, and verification.
- `references/reusable-layers.md` before adding a repository, service, use
  case, result/failure type, command, dependency wiring, or test fake, or when
  the request asks for reusable code.
- For native APIs, permissions, or channels, also read
  `platforms/flutter/skills/flutter-platform-integration/SKILL.md`.
- For choosing between Flutter and another stack, read
  `common/skills/architecture-selection/SKILL.md`.

## Stop If

- The change needs a second state-management or DI style without a repo-level
  decision.
- A new layer only forwards calls and adds no rule, mapping, test seam, or risk
  isolation.

## Verification

- Run the narrowest `flutter analyze` and `flutter test` scope for the affected
  package, plus unit tests for changed state transitions and adapter mappings.
