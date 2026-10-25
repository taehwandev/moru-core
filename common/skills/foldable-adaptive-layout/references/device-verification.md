---
keyflow_id: sys_foldable_device_verification
status: review
type: ai-generated
---

# Device Verification And Sources

## Minimum Matrix

Capture compact outer and wide inner windows, partially folded book and
tabletop, portrait/landscape, and narrow multiwindow. Repeat fold/unfold while
a detail is selected and scrolled, a draft has focus/keyboard, and media is
playing where applicable. Check continuity, Back/collapse behavior, hinge and
safe-area overlap, large text, reachable actions and no duplicate submissions.
Endpoint screenshots alone do not prove a transition passed.

### Android Emulator

Select the intended emulator with `adb -s <serial>` when several are running.
Use a foldable AVD; posture IDs and sensor support depend on its configuration.

```sh
adb -s <serial> emu fold
adb -s <serial> emu unfold
adb -s <serial> emu posture
adb -s <serial> emu posture <supported-id>
adb -s <serial> emu sensor set hinge-angle0 <angle>
adb -s <serial> shell dumpsys SurfaceFlinger --display-id
adb -s <serial> shell screencap -h
adb -s <serial> shell screencap -d <display-id> /sdcard/foldable.png
adb -s <serial> pull /sdcard/foldable.png <evidence-path>
```

Query supported postures instead of assuming `2` means half-open everywhere.
Foldables have inner and outer displays: identify the currently active display
and use its screenshot display ID; a default-display capture can be blank or
show the inactive surface. Do not assume an Activity logical display ID equals
the ID accepted by `screencap`. Verify both displays and record transition
behavior, not just a successfully issued emulator command.

### iPhone Duo

Xcode 27.1 includes the `iPhone Duo` simulator device type. Confirm the selected
Xcode/runtime with `xcodebuild -version`, `xcrun simctl list devicetypes` and
`xcrun simctl list devices available`. Open the simulator in Device Hub
(DeviceHub UI) and use its open/close/fold/rotate controls. `simctl` can select,
boot and capture the device; do not invent a `simctl fold` command. Fold/unfold
verification needs Device Hub UI interaction, automated through an available
UI tool or performed manually. Capture with
`xcrun simctl io <device-udid> screenshot <evidence-path>`; exercise both Split
View placements. Report UI access or runtime limits as unverified coverage.

## Sources And Freshness

Research baseline: 2026-10-25. Recheck version-sensitive APIs against the target
SDK/interfaces and pinned libraries; do not upgrade dependencies from a claimed
latest version. The iOS 27.1 SwiftUICore Swift interface confirms the SwiftUI
API names; UIKit signatures require its own SDK headers/interface.

- [Android adaptive layouts](https://developer.android.com/develop/ui/compose/layouts/adaptive)
  and [list/detail](https://developer.android.com/develop/ui/compose/layouts/adaptive/list-detail): window-driven layout and scaffolds.
- [Compose fold awareness](https://developer.android.com/develop/ui/compose/layouts/adaptive/foldables/make-your-app-fold-aware),
  [adaptive API](https://developer.android.com/reference/kotlin/androidx/compose/material3/adaptive/package-summary),
  [layout API](https://developer.android.com/reference/kotlin/androidx/compose/material3/adaptive/layout/package-summary)
  and [WindowManager](https://developer.android.com/develop/ui/views/layout/foldables/make-your-app-fold-aware): posture, bounds and hinge policies.
- [Adaptive releases](https://developer.android.com/jetpack/androidx/releases/compose-material3-adaptive),
  [Android 16 changes](https://developer.android.com/about/versions/16/behavior-changes-16)
  and [Android 17 changes](https://developer.android.com/about/versions/17/behavior-changes-17): dependency and resize compatibility.
- [Emulator console](https://developer.android.com/studio/run/emulator-console),
  [screenshots](https://developer.android.com/tools/adb#screencap)
  and [AOSP screencap](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/cmds/screencap/screencap.cpp): commands and display selection; check installed command help.
- Apple [Prepare your app for iPhone Duo](https://developer.apple.com/videos/play/tech-talks/111461/): SDK adoption, traits, safe areas and Device Hub.
- Apple [adaptive arrangements](https://developer.apple.com/videos/play/tech-talks/111463/),
  [multiple displays and scenes](https://developer.apple.com/videos/play/tech-talks/111464/)
  and [vertical bars](https://developer.apple.com/videos/play/tech-talks/111462/): arrangements, hinge effects and toolbar adaptation.
- Apple [Duo Group Lab](https://developer.apple.com/forums/thread/847644)
  and [TN3192](https://developer.apple.com/documentation/technotes/tn3192-migrating-your-app-from-the-deprecated-uirequiresfullscreen-key): continuity and full-screen compatibility.
