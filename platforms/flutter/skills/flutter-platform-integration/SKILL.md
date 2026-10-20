---
keyflow_id: sys_platforms_flutter_flutter_platform_integration_md_skill
status: review
type: ai-generated
---

# Flutter Platform Integration

Use when Flutter work touches MethodChannel/EventChannel, generated channel
code, plugins, native Kotlin/Swift code, permissions, OS data stores (health,
photos, contacts, location), push notifications, app lifecycle, background
execution, isolates, secure storage, files, share sheets, WebViews, or
iOS/Android build setup (Swift Package Manager or CocoaPods, Gradle, manifests,
entitlements, privacy manifests).

Do not use when the change stays in pure Dart logic with no plugin, channel,
permission, or target API.

## Read

- `references/current-guidance.md` for the boundary shape, rules, stop
  conditions, and verification.
- `references/mobile-native-bridges.md` before choosing a plugin versus own
  native code, adding a channel, requesting a permission, reading an OS data
  store, wiring push or background work, or changing iOS/Android build setup.
- `platforms/flutter/skills/flutter-review/references/mobile-release-checks.md`
  when store submission, signing, target SDK, or privacy disclosures change.
- `platforms/flutter/skills/flutter-security/SKILL.md` when the native surface
  touches credentials, files, links, WebViews, or sensitive OS data.

## Stop If

- A required target lacks the plugin or API and no fallback or disabled state
  is defined.
- Native setup, entitlements, or store declarations are needed but absent from
  repo-local docs.

## Verification

- Run analyze/tests, then build or smoke each affected target; exercise
  permission denied, unavailable, cancellation, and lifecycle resume paths on a
  real device when the API cannot run in a simulator or emulator.
