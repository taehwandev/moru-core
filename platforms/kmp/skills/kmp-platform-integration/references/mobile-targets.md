---
keyflow_id: sys_kmp_mobile_targets
status: review
type: ai-generated
---

# KMP Mobile Targets

Use when Kotlin Multiplatform or Compose Multiplatform work ships to Android
and iOS: exporting the shared framework to Xcode, calling Swift-only or
Objective-C frameworks, bridging coroutines and Flow to Swift, requesting
runtime permissions, reading OS data stores (health/fitness, photos,
contacts, location), wiring push or background work, or changing mobile build
setup.

Do not use for desktop-only shells (use `current-guidance.md` and the
application cards) or for `commonMain` logic with no target API.

Official sources to check before relying on a feature's stability:

- Kotlin/Native and iOS integration: `https://kotlinlang.org/docs/multiplatform/multiplatform-ios-integration-overview.html`
- Swift export: `https://kotlinlang.org/docs/native-swift-export.html`
- Compose Multiplatform iOS: `https://kotlinlang.org/docs/multiplatform/compose-multiplatform.html`

## Inspect First

1. Repo-local docs for Kotlin, Compose Multiplatform, Xcode, and OS minimum
   versions, and how the shared framework reaches Xcode.
2. The iOS app target: framework embedding (direct Gradle task, Swift Package,
   or CocoaPods), signing, entitlements, `Info.plist`, privacy manifest.
3. `androidMain`/`iosMain` actuals and any Swift code that implements Kotlin
   interfaces.
4. The product's data minimization rule for sensitive OS data.

## Framework Export

- Export one umbrella framework for the iOS app unless repo docs require
  several; multiple Kotlin frameworks duplicate the runtime and break type
  identity across them.
- Keep the exported surface small: export only the API Swift calls. Mark
  internal modules as non-exported dependencies.
- Objective-C export is the stable default. Swift export removes the
  Objective-C bridge but is not stable (Alpha per the official page, checked 2026-10-19); adopt it only
  with a repo-level decision and a rollback path. Re-check the official page
  before deciding.
- Kotlin `suspend` functions and `Flow` need an explicit Swift-facing shape:
  a repo-chosen bridge (completion handlers from the Objective-C export, a
  code-generation plugin, or Swift export when adopted). Pick one and use it
  everywhere; do not mix bridges per feature.
- Sealed classes, enums, and default arguments do not map one-to-one to Swift
  through the Objective-C export; expose Swift-friendly wrappers at the
  boundary when Swift code must switch over them.

## Calling Swift-Only Frameworks

Many current Apple APIs are Swift-only (Swift concurrency, Swift structs,
result builders) and cannot be called from Kotlin/Native through Objective-C
interop. Use dependency inversion:

```text
commonMain: interface HealthReader { suspend fun dailyTotal(date: LocalDate): Reading }
iosMain:    nothing, or a thin actual that receives the Swift implementation
Swift app:  class AppleHealthReader: HealthReader { ... uses the Swift API ... }
App start:  Swift passes its implementation into the shared DI graph
```

- This pattern assumes the Objective-C export, where a Kotlin interface
  appears as an Objective-C protocol that Swift can adopt. Swift export has
  documented limitations on integration modes and supported types; when it is
  adopted, compile-check that Swift can implement each exported interface
  before relying on this pattern.
- The Kotlin interface lives in shared code and is the test seam.
- The Swift implementation lives in the iOS app target (or a Swift package)
  and is registered once at app start.
- Objective-C-visible frameworks may still be called directly from `iosMain`
  through cinterop when the API is stable and simple; keep those calls inside
  one adapter file.
- Map Swift errors to the shared typed result before crossing into Kotlin.

## Permissions And OS Data Stores

- Permission prompts belong to the platform: Android uses Activity Result
  contracts owned by the Activity or a platform helper; iOS uses the
  framework's authorization call from Swift or `iosMain`. Shared code receives
  a permission state, not a launcher.
- Model availability and permission as a typed status (`ok`,
  `noPermission`, `unavailable`, `notInstalled`, `locked`, `error`), not a
  boolean or null. Some platforms hide read denial (for example iOS health
  read access, where results may still include samples the app wrote itself);
  show a neutral state when the API cannot tell.
- Prefer OS aggregate or statistics queries over summing raw samples, and
  check per data type how the store deduplicates sources; send only derived
  values the product needs.
- Re-check status when the app resumes; users change permissions in settings.

## Push, Background, And Lifecycle

- Push registration, notification permission, and token refresh live in each
  target app; shared code receives tokens and events through an interface.
- Scheduled reminders: inexact by default on Android. Exact alarms use
  `SCHEDULE_EXACT_ALARM` (user-granted and revocable; check
  `canScheduleExactAlarms()` and fall back to inexact) or `USE_EXACT_ALARM`
  (restricted by store policy to alarm-clock and calendar apps). Re-register
  after reboot, update, time-zone change, and permission changes.
- Observe lifecycle at the platform entry (Activity/Application on Android,
  scene/app delegate on iOS) and forward resume/pause to shared state holders.

## Mobile Build Setup

- Keep Android permissions minimal and inspect the merged manifest for
  dependency-added permissions.
- Keep iOS usage strings, capabilities, entitlements, and
  `PrivacyInfo.xcprivacy` in the iOS app target and review them with the
  feature that needs them.
- Confirm the Kotlin and Compose Multiplatform versions support the Xcode and
  iOS SDK the App Store currently requires before upgrading Xcode.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "Call the Apple API from iosMain directly." | Check whether it is Swift-only; if so, implement it in Swift behind a Kotlin interface. |
| "Export every module, Swift may need it later." | Export only the called surface; a wide export slows builds and leaks internals. |
| "Swift export is out, switch now." | It is not stable; adopt only with a repo decision and rollback path. |
| "Null means denied." | Return an explicit status per target. |

## Stop If

- A required API is Swift-only and the repo has no Swift implementation slot.
- The chosen Kotlin/Compose versions do not support the required Xcode/SDK.
- Store declarations, manifest/plist, and requested data types disagree.

## Verification

- Run `commonTest` with fakes for every adapter interface, then build the
  Android app and the iOS framework plus app target.
- On a real device per target: grant, deny, revoke then resume, provider
  missing, and device locked when reachable.
- Inspect the merged Android manifest and the Xcode privacy report.
