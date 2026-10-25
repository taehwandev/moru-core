---
keyflow_id: sys_foldable_ios_layout
status: review
type: ai-generated
---

# iPhone Duo, SwiftUI And UIKit

## Size Classes And System Containers

- Build with the iOS 27.1 SDK for the full inner-display experience. Keep the
  project's deployment target separate; guard new APIs with availability and
  retain adaptive fallbacks on older OS versions.
- Read SwiftUI horizontal/vertical size classes or UIKit traits and local view
  geometry. Do not branch on iPhone/iPad idiom, orientation or
  `UIScreen.main.bounds`. Closed portrait is compact width; closed landscape
  can be compact/compact; the open inner display is regular/regular. A window
  in Split View still needs its own traits and available geometry.
- Prefer `NavigationSplitView` / `UISplitViewController` for list/detail and
  `TabView` / `UITabBarController` for navigation. Let the system collapse,
  tile, overlay and reposition bars before inventing a custom split.
- For non-navigation primary/secondary content, use iOS 27.1
  `ArrangementView(primary:secondary:)` with `.arrangementViewStyle(.split)`
  or `.overlay`; `SplitArrangementViewStyle.axes(_:)` controls eligible axes.
  Keep navigation containers outside it. Do not place it inside a `List` or
  `ScrollView`; each arranged child may own its own scrolling. UIKit uses
  `UIArrangementViewController`, `UISplitArrangement` and `UIOverlayArrangement`.

## Regions, Bars And Hinge Effects

- Custom layout uses `GeometryProxy.reservedRegions(kind:options:layoutDirectionBehavior:)`
  or UIKit `UIView.reservedRegions(kind:options:)`: `.division` identifies the
  fold division, `.occlusion` identifies obstructed regions. Respect current
  active regions; `.includeInactive` is an explicit query choice, not a reason
  to always reserve a flat crease. Convert coordinates before intersection.
- In book/tabletop layouts, place related panes on either side of the division;
  keep text and interactive controls clear. Use the system arrangement when it
  fits rather than calculate a division from an angle.
- Closed Duo can place toolbars/tab bars vertically at the trailing edge;
  rotation or Split View can move them to either side. Respect leading,
  trailing, top and bottom safe areas independently, including UIKit's
  `safeAreaLayoutGuide`; do not mirror a single inset or hard-code bar height.
  `toolbarVerticalEdge` is optional (`nil` for horizontal bars). Apply
  `toolbarVerticalBehavior(_:)`, `toolbarVerticalCompressionBehavior(_:)` and
  `axisBehavior(_:)` only after checking their available signatures and need.
- `.onHingeChange` provides old/new `DeviceHingeContext`; `hinge` is optional.
  `DeviceHinge` status (`closed`, `partiallyOpen`, `fullyOpen`) and angle, or
  UIKit `UIHingeInteraction`, serve effects/interactions. There is no universal
  pose value or guaranteed sensor update rate for layout branching.

## Continuity And Compatibility

- Fold/unfold updates traits and geometry in the same scene. Preserve view and
  state identity, selection, text/focus, scroll, keyboard and playback; do not
  rebuild the navigation root or repeat a submission on a hinge callback.
  Actual scene disconnection uses the app's restoration contract separately.
- Support resizing and rotation. Inner-display behavior makes orientation locks
  unreliable; deprecated `UIRequiresFullScreen` is not a foldable layout fix.
- Keep these native APIs in the native host/iOS actuals when embedding Compose.

## Verification

Use the [device matrix](device-verification.md), including asymmetric vertical
bars, compact/compact, both halves of Split View and live fold transitions.
