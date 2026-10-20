---
keyflow_id: sys_kmp_mobile_platform_native_ui
status: review
type: ai-generated
---

# KMP Mobile Platform-Native UI

Read when a Compose Multiplatform app ships to Android and iOS and a screen
touches app bars, navigation, sheets, dialogs, controls, lists, search, scroll
edges, blur, or screen transitions. Compose draws every pixel itself, so
"shared UI" silently becomes "Android-looking UI on iPhone" unless each control
is placed on purpose. The Android baseline for the same concerns is
[android-compose-ui](../../../../android/skills/android-compose-ui/references/current-guidance.md)
and its [edge-to-edge insets](../../../../android/skills/android-compose-ui/references/edge-to-edge-insets.md)
reference; this card adds the iOS half and the shared-wrapper rules.

## Decide Per Control, Not Per App

Pick one column for each control and record it in the design-system module
docs. A product brand can stay shared while system chrome follows the OS.

| Control | Default | Android actual | iOS actual |
| --- | --- | --- | --- |
| Top app bar, back button, large title | native | M3 `TopAppBar` | `UINavigationBar` via `UIKitView` |
| Bottom tab bar | native | M3 `NavigationBar` | `UITabBar` |
| Alert, confirm dialog | native | M3 `AlertDialog` | `UIAlertController(.alert)` |
| Action list, share | native | M3 `ModalBottomSheet`, share intent | `UIAlertController(.actionSheet)`, `UIActivityViewController` |
| Bottom sheet with content | native | M3 `ModalBottomSheet` | `UISheetPresentationController` hosting a Compose view controller |
| Switch | native | M3 `Switch` | `UISwitch` |
| Push/pop transition, back gesture | native motion | shared axis / predictive back | push with parallax, edge swipe |
| Settings list rows | platform styled | M3 list items | inset grouped rows |
| Text field, search field | platform styled | M3 text field / search bar | `UITextField`/`UISearchBar` look |
| Pull to refresh | platform styled | M3 pull-to-refresh | `UIRefreshControl` look |
| Segmented choice | platform styled | M3 segmented buttons | `UISegmentedControl` look |
| Transient message | platform styled | M3 Snackbar | banner/HUD style, no Android toast shape |
| Content cards, feed rows, article body, brand chips | shared | design-system component | same component |

- "native" means a real platform control behind an `expect`/`actual`
  design-system wrapper.
- "platform styled" may stay Compose-drawn, but the wrapper picks platform
  shape, spacing, typography and feedback (ripple vs highlight) per target.
- "shared" is product content. Keep one implementation.
- Feature modules only call the product-prefixed wrapper. They never branch on
  platform and never import Material or UIKit types.

## Wrapper Contract

- One `commonMain` API per control (`PlatformTopBar`, `PlatformSwitch`,
  `PlatformDialog`, ...) with semantic parameters: title, actions as data,
  enabled, destructive, selection. No platform enums in the signature.
- `androidMain` and `iosMain` actuals own the platform look; `commonMain` owns
  the contract and a fallback for any other target.
- Map icons to platform symbols inside the actual (Material icon vs SF Symbol),
  keyed by a shared icon enum.
- Keep text, accessibility label and destructive role in the contract so both
  actuals announce the same thing.

## iOS UIKit Interop Rules

- Host UIKit controls with `UIKitView`. Use `placedAsOverlay = true` for bars
  drawn over scrolling Compose content, and pick the interaction mode on
  purpose (`NonCooperative` for buttons and switches).
- Create the UIKit view once (`remember`) and update values in `update`; do not
  rebuild bar items every recomposition. Re-create items only when their
  content key changes.
- Custom views inside bar items are sized by Auto Layout, not frames. Add
  width/height constraints or they fill the bar.
- iOS 26 shows custom bar-item views as glass capsules; prefer plain
  `UIBarButtonItem` with an SF Symbol when no capsule is wanted.
- Do not declare a Kotlin `object` that subclasses `NSObject` (delegates,
  targets). It compiles to a klib but fails at framework link. Use a remembered
  class instance instead.
- Always link the iOS app (`xcodebuild` for a simulator or device destination)
  after iOS actual changes; `compileKotlinIos*` alone does not catch link errors.
- Action sheets: set a popover source only on iPad. On iPhone a source turns the
  sheet into a popover on newer iOS versions.

## Scroll Edge And Translucency

- Bars over content are transparent only at the top. Once content scrolls under
  the bar, show the platform scroll-edge background: iOS
  `UINavigationBarAppearance.configureWithDefaultBackground()` (material +
  separator), Android an opaque or blurred surface with a hairline.
- Never fade a blur to transparent toward the bar's bottom edge; titles and
  buttons sit there and become unreadable over text.
- Decide "scrolled" from the real list position (first visible index/offset or
  progress), not from accumulated nested-scroll deltas. Programmatic jumps
  (search result, "continue reading", restore) do not produce nested-scroll
  events and leave the bar transparent.
- Compose blur via `graphicsLayer { renderEffect = BlurEffect(...) }` blurs the
  layer's own children. Put the blur on a separate background layer behind the
  content (`Box(Modifier.matchParentSize().blur...)` then the content), never on
  the container that holds icons or text.
- Blur may not render on emulators or older Android (pre-API 31). Pick a
  surface opacity that stays readable with no blur at all.

## Transitions

- Detail push/pop follows the platform: iOS slides the new screen fully and the
  previous one about 30% (parallax), and on pop the leaving screen stays on top
  (`targetContentZIndex = -1`); Android uses Material shared axis and a
  scale/fade predictive back.
- Tab switches are instant on both platforms.
- Respect reduced motion (`UIAccessibilityIsReduceMotionEnabled`, Android
  animator scale) with a plain fade.
- Avoid a blank frame during the push: render a skeleton shaped like the
  destination, then cross-fade to content, instead of a centered spinner.

## Adaptive Layout

- Use window width classes, not device names. Treat width at or above the
  Material medium breakpoint (600dp) as "wide" for foldables and tablets and
  choose the reading/layout mode from the width at first open.
- Keep the choice in state so unfolding or rotating mid-session does not reset
  what the user picked.

## Verification

- Compile both targets and link the iOS app.
- Capture each changed screen on an Android emulator or device (adb
  `screencap`, `screenrecord` for motion) and on an iOS simulator
  (`simctl io screenshot`). Simulators cannot be scrolled from the command
  line; name the unverified state (for example the scrolled bar) and check it on
  a device.
- Review that features import no Material or UIKit types and no platform
  branches, and that every "native" control in the table is behind a wrapper.

## Stop If

- The product asks for one identical custom look on both platforms for system
  chrome. Record that decision and its accessibility and review risk in the
  design-system docs before diverging from this table.
- A native control would require leaking platform types into feature code.
