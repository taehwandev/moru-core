---
name: kmp-compose-ui
description: "KMP Compose UI: Use when creating, changing, moving, or reviewing Compose Multiplatform screens, state holders, reusable UI components, previews, resources, or UI tests."
keyflow_id: sys_platforms_kmp_kmp_compose_ui_md_skill
status: review
type: ai-generated
---

# KMP Compose UI

Use for Compose Multiplatform screens, state holders, components, previews,
resources or UI tests in shared or desktop (JVM) source sets. Not for
Android-only modules (`platforms/android/skills/android-compose-ui/SKILL.md`)
or non-Compose UI.

## Read

- `common/skills/social-sign-in-buttons/SKILL.md` for auth UI, provider buttons
  and native sign-in control boundaries.

- `common/skills/foldable-adaptive-layout/SKILL.md` when changing adaptive,
  large-screen or foldable layouts and state continuity across fold/unfold.
- `references/current-guidance.md`; `references/design-system.md` for tokens
  and shared components.
- `references/mobile-platform-native-ui.md` when the app ships to Android and
  iOS and the change touches app bars, tab bars, sheets, dialogs, controls,
  settings lists, search, scroll-edge backgrounds, blur or push transitions.

## Verification

- Compile the changed source set, then run `runComposeUiTest`, a screenshot or
  a captured-window check for the changed screen.
- For iOS actuals, link the app with `xcodebuild`; capture Android and iOS
  screenshots of the changed screen.
