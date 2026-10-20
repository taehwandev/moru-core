---
keyflow_id: sys_flutter_mobile_release_checks
status: review
type: ai-generated
---

# Flutter Mobile Release Checks

Use when a Flutter diff or release touches Android/iOS build configuration,
signing, flavors, target SDK, permissions, privacy disclosures, store
metadata, or a store submission (internal test, TestFlight, production).

Do not use for Dart-only changes that leave native configuration, permissions,
and declared data use unchanged.

Store policies change often. Confirm current requirements in the official
Google Play Console Help and Apple App Review Guidelines before submission and
record the checked date in repo-local docs.

## Inspect First

1. Repo-local release runbook, flavor list, and store declaration records.
2. The diff of `AndroidManifest.xml`, Gradle files, `Info.plist`, entitlements,
   `PrivacyInfo.xcprivacy`, and dependency lock files.
3. The data the app collects or shares after the change.

## Checklist

### Both Platforms

- Declared data use (Play Data safety, App Store privacy labels) matches what
  the code sends off the device, including SDK-collected identifiers.
- Every runtime permission has a user-facing purpose and an in-app path that
  works when it is denied.
- Account creation implies in-app account deletion; check whether the store
  also needs a web deletion URL.
- Release builds use release API origins and public client identifiers from
  flavors or `--dart-define`; debug tools are absent from release. Anything
  compiled into the app is extractable: server secrets, service-account keys,
  signing secrets, and private API keys never go into the bundle, defines, or
  assets.
- Obfuscation or symbol upload (`--obfuscate --split-debug-info`) is configured
  consistently with the crash reporter, and symbols are stored outside the repo.

### Android

- Target SDK meets the current Play requirement; minimum SDK matches repo docs.
- The merged manifest contains only intended permissions and queries.
- Sensitive or restricted permissions (health data, exact alarms, background
  location, full media access) have matching Play Console declarations.
- App bundle signing uses Play App Signing or the documented key path.

### iOS

- The build uses the Xcode/SDK version the App Store currently requires.
- Each usage-description string exists only for an API the app calls.
- Capabilities and entitlements match the features shipped.
- The privacy manifest covers required-reason APIs, and third-party SDK
  manifests and signatures are present; review the Xcode privacy report.
- Sign in with a third-party provider may require offering Sign in with Apple;
  account deletion must revoke provider tokens when applicable.

## Stop If

- A store declaration would need to change and no owner has updated it.
- A new SDK collects data not covered by the privacy policy or disclosures.
- Signing material or service config would be committed.

## Verification

- Build release artifacts for each target and install them on a real device.
- Diff the merged manifest and the privacy report against the previous release.
- Record store declaration changes and the policy check date in repo-local docs.
