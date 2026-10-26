---
keyflow_id: sys_9b770e3542d3
status: review
type: ai-generated
---

# iOS Review

Use for iOS SwiftUI/UIKit, navigation, concurrency, permission, and UI flow review.

## Findings Priority

1. User-visible crash, data loss, permission bypass, credential exposure,
   insecure WebView/deep link, or release-signing risk.
2. Broken navigation, state ownership, async cancellation, target membership, or
   package/public API contract.
3. Missing tests or visual checks for changed ViewModel, coordinator, screen,
   adapter, permission, or release surface.
4. Accessibility, Dynamic Type, localization, focus, keyboard, or small-screen
   regression.
5. Maintainability, package layout, preview/fixture ownership, or duplicated
   platform adapter risk.

## Review

- Check Swift package, architecture, design-system, and target boundaries
  against `platforms/swift/skills/swift-review/SKILL.md` when Swift-wide concerns changed.
- Check View/ViewModel ownership, navigation state, async task lifetime, and cancellation.
- Check SwiftUI route/screen/section boundaries against
  `platforms/ios/skills/ios-swiftui-ui/SKILL.md` when SwiftUI screens changed.
- For SwiftUI changes, check whether simple Model-View is enough for trivial
  local state; otherwise prefer TCA before approving ad hoc MVVM for async,
  navigation, shared state, or reducer-testable workflows.
- Check UIKit coordinator/view-controller/ViewModel/list/form boundaries
  against `platforms/ios/skills/ios-uikit-ui/SKILL.md` when UIKit screens changed.
- Check target/package boundaries against `platforms/ios/skills/ios-module-structure/SKILL.md` when new
  targets, local Swift packages, access-control changes, package exports, or
  feature contracts are touched.
- Check design-system tokens, styles, primitives, variants, previews, and
  reusable control contracts against `platforms/swift/skills/swift-design-system/SKILL.md` when
  shared UI or styling changed.
- Confirm `UiState` represents loading, content, empty, error, permission
  denied, offline, disabled, and submitted states when applicable.
- Confirm API-backed initial loading preserves the page structure with a
  skeleton, redacted placeholder, or equivalent stateful layout when the final
  shape is known.
- Verify main actor boundaries for UI updates.
- Verify `@Observable` ownership wrappers, `.task` usage, stable list IDs,
  Dynamic Type, VoiceOver labels, and SwiftUI previews when SwiftUI views
  changed.
- Verify `NavigationStack`, per-tab paths, `.sheet(item:)`, centralized router
  mapping, and validated deep-link handling when navigation changed.
- Ensure API, persistence, keychain, file, notification, and permission APIs are wrapped.
- For persistence changes, confirm the storage choice matches the data shape:
  SwiftData/Core Data/SQLite for durable or queryable models, UserDefaults or
  `@AppStorage` only for non-sensitive preferences, Keychain only for small
  secrets, and files/caches for documents or derived data.
- Check loading, empty, error, permission-denied, and offline states.
- Confirm sensitive data is not stored in plain UserDefaults or logs.
- Review Universal Links, URL schemes, entitlements, WebView bridges, ATS
  exceptions, and release signing when security surfaces change.

## Do Not Approve When

- View, view controller, or coordinator code owns API, persistence, keychain,
  file, notification, permission, or SDK calls directly instead of using an
  adapter or state owner.
- UI state can represent contradictory loading, content, empty, error,
  permission, offline, disabled, or submitted states.
- Non-trivial SwiftUI async/navigation/shared-state work avoids TCA without a
  repo-local reason and instead scatters mutation across Views or ad hoc
  ViewModel methods.
- API-backed screens show only a spinner or blank page when the content layout
  is known and a skeleton/redacted placeholder should preserve the transition.
- A new ViewModel, protocol, use case, package, or router is added only for
  ceremony and does not isolate state, navigation, side effects, product rules,
  or tests.
- Async tasks, delegates, timers, notifications, Combine subscriptions, or
  platform handles can outlive the owning screen, command, or app lifecycle.
- SwiftUI navigation uses `NavigationView`, stores views in navigation state,
  shares one path across independent tabs, or parses deep links in multiple
  unvalidated places.
- Feature modules leak DTOs, persistence rows, SDK objects, app-route
  implementation types, or broad `public` APIs without a caller contract.
- UserDefaults, `@AppStorage`, plist files, caches, or app group containers hold
  tokens, credentials, personal data, role/entitlement truth, or queryable
  product records without an accepted risk and cleanup model.
- Keychain is used as a general product database instead of storing only small
  secrets while durable records live behind a repository/storage boundary.
- Entitlements, URL schemes, Universal Links, WebViews, app extensions, signing,
  or release config changed without security and release verification.

## Tools

- Static: Swift compiler, `swift-format` or SwiftFormat for formatting, and
  SwiftLint for naming, line length, complexity, file/type size, force unwraps,
  and maintainability when configured. If no Swift lint config exists, review
  against `common/skills/code-conventions/SKILL.md` plus `platforms/swift/skills/swift-review/SKILL.md`.
- Unit: XCTest or Swift Testing for mapper, policy, service, ViewModel state.
- UI: XCUITest for navigation, forms, permissions, and critical flows.
- Snapshot: use only when visual regression matters and repo already supports it.
- Build: `xcodebuild test` or repo wrapper command.

## UI Test Focus

- Main flow works from launch to completion.
- Permission prompts and denied states are handled.
- Async loading and cancellation do not leave stale UI.
- Storage migration, corruption/defaulting, and logout/account-switch cleanup
  are covered when persistence or key-value storage changed.
- Initial loading, background refresh with stale content, retry after error,
  empty state, permission denial, and offline state are visually and
  behaviorally distinct when reachable.
- SwiftUI previews or an equivalent visual check cover the changed visual
  states when UI structure changed.
- Dynamic Type, small screens, and VoiceOver labels are considered.
- Release configuration does not expose debug endpoints, secrets, or broad
  entitlements.

## Output

Lead with concrete findings and identify the target, screen, or package
boundary:

```text
Findings:
- [High] platforms/ios/... - issue, impact, affected boundary, required verification
```

If no findings remain, say so and list unchecked target, permission, accessibility,
or release surfaces.
