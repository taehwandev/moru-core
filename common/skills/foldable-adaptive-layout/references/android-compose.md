---
keyflow_id: sys_foldable_android_compose
status: review
type: ai-generated
---

# Android And Compose Layout

## Choose Layout From The Window

- Use `currentWindowAdaptiveInfo().windowSizeClass` for the current app window,
  including multiwindow. Width classes start at compact <600dp, medium
  600–839dp and expanded >=840dp; consult the installed library for additional
  large/extra-large classes. Height and each pane's usable width also matter.
- Prefer Material 3 adaptive `ListDetailPaneScaffold` (or its navigable variant)
  and `NavigationSuiteScaffold` before a custom rail and weighted `Row`.
  Keep selection/back behavior stable when panes collapse or expand.
- Pass current adaptive information into `calculatePaneScaffoldDirective`.
  Its default `HingePolicy.AvoidSeparating` feeds hinge bounds into the
  directive's `excludedBounds`; preserve those exclusions in custom directives.
  Choose `AvoidOccluding`, `AlwaysAvoid` or `NeverAvoid` only for a reason tied
  to the content. A crease on a flat continuous display need not force a split.

## Use Posture And Region Geometry

- `windowPosture.isTabletop` describes a half-open horizontal fold. For media,
  camera or editing, put content above and reachable controls/input below.
  For list/detail, retain a usable side-by-side arrangement when appropriate;
  do not assume a vertical-pane scaffold also clears horizontal hinges.
- `windowPosture.hingeList` supplies `HingeInfo` bounds and flags (`isVertical`,
  `isFlat`, `isSeparating`, `isOccluding`). The
  `separatingVerticalHingeBounds` / `separatingHorizontalHingeBounds` helpers
  support custom book/tabletop layouts. Bounds are window-relative pixels;
  convert into the layout's coordinates/units before applying exclusions.
- Use Jetpack WindowManager `FoldingFeature` directly for Views, platform
  surfaces or information absent from the Compose abstraction. Inspect
  `bounds`, `orientation`, `state` (`FLAT`/`HALF_OPENED`), `isSeparating` and
  `occlusionType`; collect `WindowInfoTracker` updates with the owner lifecycle.
- Galaxy Z Fold/Pixel Fold continuous displays can be non-separating when flat;
  a physical dual-screen hinge can remain occluding/separating. Read reported
  features rather than infer them from a model or portrait/landscape label.
  Reserve hinge-angle sensors for effects, never as a substitute for bounds.

## State, Resizing And Multiplatform

- Do not rely on `screenOrientation`, aspect-ratio limits or
  `resizeableActivity=false`. Large-screen restrictions change with target SDK;
  Android 16/17 rules require testing rotation and resizing rather than relying
  on a compatibility opt-out.
- Use stable navigation/state holders, `ViewModel`, `rememberSaveable` and
  stable list keys as appropriate; do not recreate the screen's identity when
  a size class changes. Verify both resize and Activity recreation.
- Check Material 3 adaptive APIs against the project's actual dependency and
  source-set support. Android WindowManager/sensors stay in `androidMain`;
  iOS safe areas/reserved regions stay in `iosMain` or the native host. Share
  semantic pane/state contracts and mapped geometry, not platform SDK types.
  Android posture support does not prove iOS hinge support in shared Compose.

## Verification

Run the [device matrix](device-verification.md); check vertical and horizontal
exclusions, compact Back behavior, restore/recreation and both displays.
