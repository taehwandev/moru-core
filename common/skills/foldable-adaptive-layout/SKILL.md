---
name: foldable-adaptive-layout
description: "Foldable And Adaptive Layout: Use for adaptive or large-screen mobile layouts, fold/unfold transitions, book/tabletop postures, hinges and dual-screen regions: Android foldables (including Galaxy Z Fold and Pixel Fold), iPhone Duo, Jetpack Compose, Compose Multiplatform, SwiftUI and UIKit."
keyflow_id: sys_common_foldable_adaptive_layout_skill
status: review
type: ai-generated
---

# Foldable And Adaptive Layout

## Use When

Use for adaptive or large-screen mobile layouts, fold/unfold transitions,
book/tabletop postures, hinges and dual-screen regions: Android foldables
(including Galaxy Z Fold and Pixel Fold), iPhone Duo, Jetpack Compose,
Compose Multiplatform, SwiftUI and UIKit. Skip unrelated UI styling, adaptive
icons and desktop-only resizing.

## Read

- Inspect the target's UI/state owners, minimum OS, SDK and dependency versions.
  Retain the applicable Android, KMP or iOS UI skill's authoring contract.
- [Android and Compose](references/android-compose.md) for Android or shared
  Compose layouts; its platform boundary applies to Compose Multiplatform.
- [iOS layout](references/ios-layout.md) for SwiftUI, UIKit or iOS actuals.
- [Device verification and sources](references/device-verification.md) before
  claiming posture coverage or selecting version-sensitive APIs.

## Decision Rule

1. Choose pane count and navigation from the current window's available space
   and size classes. Re-evaluate on resize, rotation and fold/unfold; device
   names, screen bounds and a one-time width check do not determine layout.
2. Prefer adaptive navigation/pane containers before custom weighted splits.
   Respect safe areas and measured separating/occluding regions; keep primary
   text, inputs and actions clear of a hinge or division.
3. Use book posture for usable side-by-side content; use tabletop content above
   and controls below when that fits the task. A fold does not require two panes
   if either pane would be unusable. Hinge angle drives effects/interactions,
   while layout uses window geometry and the platform's region/posture APIs.
4. Keep selected item, navigation history, draft input, focus, scroll and media
   state in stable owners across layout changes. Save/restoration mechanisms
   also cover Android recreation; a resize must not repeat network mutations.

## Stop If

- A proposed fix locks orientation, disables resizing or hard-codes a model's
  dimensions instead of handling the available window.
- Custom panes ignore a separating region, reset user state, or leak platform
  hinge types into shared domain/feature contracts.
- The installed SDK/dependency does not expose the proposed API: keep a working
  fallback and resolve availability before implementation.

## Verification

- Compile affected targets; link iOS actuals with the app, not just Kotlin.
- Exercise compact, wide, book, tabletop, rotation and narrow multiwindow,
  including transitions with input/keyboard and a selected/scrolled detail.
- Capture each active display and check insets, accessibility text size, touch
  targets and state continuity using the device verification reference.

## Report

Name layout/state owners, chosen containers, API availability/fallbacks, tested
devices/postures and transitions, captured evidence and unverified states.
