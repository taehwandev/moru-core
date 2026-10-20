---
keyflow_id: sys_platforms_flutter_flutter_widget_ui_md_skill
status: review
type: ai-generated
---

# Flutter Widget UI

Use when creating, changing, moving, or reviewing Flutter routes, pages,
screens, widgets, design-system components, themes or tokens, forms, gestures,
navigation UI, accessibility, golden tests, or widget tests.

Do not use for state-owner or repository logic without a UI change (use
`platforms/flutter/skills/flutter-state-data/SKILL.md`).

## Read

- `references/current-guidance.md` for widget layers, statefulness, the UI
  contract, and verification.
- `platforms/flutter/skills/flutter-architecture/references/reusable-layers.md`
  before promoting a widget into a shared design-system or component package.
- `common/skills/design-system/SKILL.md` and
  `common/skills/component-api-design/SKILL.md` when tokens or component APIs
  change.

## Stop If

- A leaf widget needs a repository, platform channel, service locator, or
  global router to render.

## Verification

- Run analyze plus widget tests for rendering, callbacks, semantics, and large
  text scale; add golden or screenshot checks for visual component changes
  when configured.
