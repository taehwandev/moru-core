---
keyflow_id: sys_flutter_mobile_native_bridges
status: review
type: ai-generated
---

# Flutter Mobile Native Bridges

Use when a Flutter app on Android or iOS must call native APIs: choosing a
plugin or owning native code, defining a channel contract, requesting runtime
permissions, reading an OS data store (health/fitness, photos, contacts,
location), wiring push or background work, or changing native build setup.

Do not use for desktop or web shells (use the base
`current-guidance.md`) or for pure Dart services with no native call.

Official sources to check for current behavior before relying on a version:

- Platform channels: `https://docs.flutter.dev/platform-integration/platform-channels`
- Pigeon: `https://pub.dev/packages/pigeon`
- Swift Package Manager for app and plugin developers:
  `https://docs.flutter.dev/packages-and-plugins/swift-package-manager/for-app-developers`

## Inspect First

1. Repo-local docs for target OS minimums, flavors, signing, and store
   declarations.
2. `pubspec.yaml` and lock file for existing plugins that already wrap the API.
3. `android/app/src/main/AndroidManifest.xml`, Gradle files, `ios/Runner/Info.plist`,
   entitlements, and the iOS dependency manager in use (Swift Package Manager
   or CocoaPods).
4. The product's data minimization rule: which values may leave the device.

## Decision Rule: Plugin Or Own Native Code

| Choose | When |
| --- | --- |
| Maintained community or first-party plugin | It covers the exact API surface, both targets, current OS SDKs, and its permissions/manifests do not exceed what the product declares. |
| Own native code behind a generated typed channel | The app needs a narrow slice of a large API (for example one aggregate query), a plugin would add permissions or data types the store declaration does not cover, or plugin maintenance lags OS releases. |
| Local plugin package | The own native code is reused by more than one app or needs its own tests and release cadence. |

Before adopting a plugin, record: supported targets, last release date,
declared permissions it merges into the manifest or plist, and whether the
store review would see capabilities the product does not use. A plugin that
silently adds permissions is a store-review risk, not only a size cost.

## Typed Channel Contract

- Prefer a generated contract (Pigeon or the repo's equivalent) over
  hand-written `MethodChannel` string maps. One Dart definition file generates
  the Dart client and the Kotlin/Swift host interfaces.
- Keep the contract file, generated outputs, and generator version in one
  owner folder; regenerate in CI or check generated files for drift.
- Return a small result type, not raw platform objects: a value plus a status
  enum such as `ok`, `noPermission`, `unavailable`, `notInstalled`,
  `locked`, `error`. Never return `null` for both "no data" and "not allowed".
- Map native exceptions to typed Dart failures at the platform service; leaf
  widgets never see `PlatformException` codes.
- Generate Dart and native outputs from the same schema with the same
  generator version and update them together; Pigeon does not guarantee
  compatibility across generator versions, and a mismatch can crash at
  runtime. If Dart and native must ship independently (add-to-app, separately
  released plugins), define an explicit compatibility protocol and test each
  supported version pair.

```text
Widget -> State owner -> Repository -> PlatformService (Dart interface)
  -> GeneratedApi (Pigeon client) -> Host API (Kotlin / Swift) -> OS SDK
```

The Dart interface is the test seam: unit tests use a fake implementation,
never the generated client.

## Permission Flow

1. Explain before asking: an in-app rationale screen precedes the OS prompt
   when the platform or store policy requires a purpose statement.
2. Check availability first (SDK present, provider app installed, device
   supported), then permission state, then request.
3. Model the outcome as state, not a boolean: granted, denied, permanently
   denied or "ask again in settings", restricted, not determinable.
4. Some platforms hide read denial for privacy (for example, iOS health
   authorization status reflects write access only; a denied read type returns
   no samples from other sources but may still return samples the app wrote
   itself). Neither an empty nor a non-empty result proves read access. Do not
   show "permission denied" when the API cannot tell; show a neutral "no data
   yet, check settings" state.
5. Re-check permission on app resume; users change it in system settings.
6. Request only the data types the product uses. Store declarations and the
   manifest/plist must list the same set.

## OS Data Stores

- Prefer the OS-provided aggregate or statistics queries over summing raw
  samples in Dart. Check per data type how the store prioritizes and
  deduplicates sources and which time window it uses; deduplication applies to
  some types only, and others simply sum every writing app.
- Send only the derived value the product needs (for example a daily total
  and its measurement time), never raw samples, when the product does not need
  them.
- Read in the foreground unless background delivery is a documented product
  requirement; background reads add entitlements, battery cost, and review
  questions.
- Handle "store locked" (device locked) and "provider not installed or needs
  update" as distinct states.

## Push, Background, And Lifecycle

- Push token registration, notification permission (Android 13+ runtime
  permission, iOS authorization), and channel setup live in a platform service,
  not in widgets.
- Scheduled local reminders: prefer inexact scheduling. On Android, exact
  alarms use either `SCHEDULE_EXACT_ALARM` (user-granted, revocable; check
  `canScheduleExactAlarms()` and fall back to inexact when denied) or
  `USE_EXACT_ALARM` (auto-granted but restricted to alarm-clock and calendar
  use cases by store policy). Re-register after reboot, app update, time-zone
  change, and exact-alarm permission changes.
- Background work (WorkManager, BGTaskScheduler, isolates) needs a named owner,
  cancellation, and a documented reason; foreground-only reads are the default.
- Observe app lifecycle (`AppLifecycleListener` or equivalent) at the app or
  service layer to refresh permissions and data on resume.

## Native Build Setup

- iOS: Flutter defaults to Swift Package Manager for iOS/macOS from Flutter
  3.44; CocoaPods remains a fallback for plugins without Swift packages, and
  the CocoaPods trunk becomes read-only on 2026-12-02. Check each plugin's
  Swift package support before adding it, and record the dependency manager in
  repo-local docs.
- iOS: usage-description strings, capabilities/entitlements, and
  `PrivacyInfo.xcprivacy` (including third-party SDK manifests) are part of the
  feature, reviewed with the code that needs them.
- Android: declare only the permissions used; inspect the merged manifest for
  permissions added by dependencies and remove unwanted ones with
  `tools:node="remove"`. Keep target SDK at the store's current requirement.
- Keep keystores, provisioning profiles, service config files, and signing
  secrets out of the repository unless repo policy says otherwise.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "The plugin is popular, so its permissions are fine." | Inspect the merged manifest and plist; store review judges declared capabilities. |
| "A hand-written channel is quicker." | Use a generated contract unless the call is a single throwaway prototype. |
| "Null means no permission." | Return an explicit status; null cannot distinguish no data, denied, and unavailable. |
| "It works in the simulator." | OS data stores, push, and permissions need a real-device check. |

## Stop If

- The store declaration, manifest/plist, and requested data types disagree.
- The feature needs background access or an entitlement that repo-local docs
  do not authorize.
- Raw sensitive samples would be sent off the device without a documented
  product need and consent path.

## Verification

- Unit-test the Dart platform service with a fake host API, covering each
  status value.
- Run the generator and confirm generated files have no drift.
- On a real device per target: grant, deny, revoke in settings then resume,
  provider missing, and device locked when reachable.
- Inspect the merged Android manifest and the iOS privacy report for unexpected
  permissions or data types.
