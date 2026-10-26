---
keyflow_id: sys_ios_security
status: review
type: human-reviewed-needed
---

# iOS Security

Use when iOS work touches credentials, Keychain, local storage, permissions,
Universal Links, URL schemes, app groups, extensions, WebViews, networking,
signing, entitlements, or release builds.

Also use `common/skills/secure-development-baseline/SKILL.md` for shared secret handling,
authorization, logging, diagnostics, and open-source repository safety rules.
Use `common/skills/runtime-url-configuration/SKILL.md` for environment-specific API origins,
Universal Link domains, URL scheme callback hosts, redirect/callback URLs,
asset hosts, and release-channel config.

Also use `common/skills/observability-error-handling/SKILL.md` when adding or changing
crash reporting, error telemetry, logging, diagnostics, or analytics.

References:

- Keychain Services:
  `https://developer.apple.com/documentation/security/keychain-services`
- UserDefaults: `https://developer.apple.com/documentation/foundation/userdefaults`
- Firebase Crashlytics: `https://firebase.google.com/docs/crashlytics`
- Firebase pricing: `https://firebase.google.com/pricing`
- Sentry Apple SDK: `https://docs.sentry.io/platforms/apple/`
- Sentry pricing: `https://sentry.io/pricing/`

## Rules

- Store credentials, refresh tokens, private keys, and sensitive auth material in
  Keychain or a repo-approved secure storage wrapper.
- Treat UserDefaults, plist files, caches, screenshots, logs, analytics, and
  crash payloads as visible data surfaces.
- Keep server-only secrets out of app bundles, generated config, assets, and
  build settings.
- Put environment-specific API origins, callback URLs, Universal Link domains,
  URL scheme callback hosts, and asset hosts in build settings, `.xcconfig`,
  Info.plist values, schemes, or the repo-approved config path instead of source
  literals.
- Restrict client keys by bundle id, team id, associated domain, API scope,
  quota, or provider-specific controls when available.
- Treat URL schemes, Universal Links, App Clips, widgets, extensions, pasteboard,
  document providers, and share extensions as trust boundaries.
- Validate incoming links, file URLs, callback payloads, and redirect targets
  before using embedded IDs, tokens, or actions.
- Keep WKWebView bridges narrow, typed, and unavailable to untrusted content.
- Keep App Transport Security exceptions explicit and debug-scoped unless the
  repo documents an accepted production reason.
- Ensure permission purpose strings are specific, truthful, and aligned with the
  data actually used.
- Production iOS apps need crash reporting unless the repo documents a stricter
  privacy, regulatory, offline-only, or cost reason to disable it.
- Prefer Firebase Crashlytics for app-first iOS crash reporting when the app
  already uses Firebase or wants mobile-native crash grouping with low setup
  overhead. Prefer Sentry when the product needs cross-platform tracing,
  backend-to-client correlation, release health across services, or existing
  Sentry operations. Use both only with an explicit reason, because duplicate
  SDKs increase binary, privacy, alerting, and cost surfaces.
- Check current provider pricing, quotas, retention, data residency, PII
  scrubbing, sampling, and release-channel setup before adding or expanding
  crash reporting. Do not treat a public DSN or Firebase config as secret, but
  still keep provider-private tokens server-side.
- Signing, entitlements, provisioning profiles, associated domains, and release
  build configuration need explicit smoke coverage when changed.

## Local Storage Tiers

Use storage tiers by sensitivity, not convenience:

| Tier | Use For | Review Notes |
| --- | --- | --- |
| Keychain | Access tokens, refresh tokens, private credentials, device-bound secrets, and small sensitive auth material. | Choose accessibility/access-group behavior intentionally; handle read/write failures, reinstall/account-switch behavior, and token revocation cleanup. |
| UserDefaults / `@AppStorage` | Non-sensitive preferences, toggles, enum choices, onboarding flags, display settings, and simple feature settings. | Treat values as user-visible local data; avoid secrets, personal data, entitlement truth, and queryable product records. |
| App group UserDefaults/container | Small non-sensitive values that an extension or widget must share. | App group scope is broad; name the sharing reason, cleanup trigger, and privacy risk before use. |
| Files, caches, SQLite, SwiftData, or Core Data | Documents, caches, durable models, queryable data, and offline state. | Use the persistence guidance for schema, migration, corruption handling, and source-of-truth ownership. |

Do not use a `loggedIn` boolean, cached role, cached entitlement, or feature
flag in UserDefaults as an authorization source. Treat those values as hints for
UI startup only, then revalidate with the trusted server or platform boundary.

## Check

- Which app, extension, URL, file, web content, or external service can trigger
  this action?
- Is sensitive data outside UserDefaults, logs, screenshots, crash reports, and
  broad app group storage?
- Are permission denied, revoked permission, and restricted-device states visible
  and recoverable?
- Do entitlements, associated domains, callback URLs, and bundle ids match the
  intended environment?
- Do API origins, redirect/callback URLs, Universal Link domains, asset hosts,
  and provider app registrations match the release channel being built?
- Does release configuration avoid debug endpoints, broad ATS exceptions, and
  embedded private credentials?
- Which crash provider is the primary source of truth, what data is collected,
  what is filtered, what release/channel metadata is attached, and what cost or
  quota limit applies?
- Which local storage tier is used for each persisted value, and what clears it
  on logout, account switch, revoke, entitlement downgrade, or remote deletion?

## Do Not

- Do not put credentials, refresh tokens, OAuth client secrets, signing
  material, private API tokens, or service-role keys in app bundles, assets,
  Info.plist files, generated config, or build settings.
- Do not store sensitive user data in UserDefaults, plain plist files, caches,
  screenshots, crash payloads, pasteboard, or broad app group containers unless
  the repo records an accepted risk and protection model.
- Do not accept Universal Links, URL schemes, files, pasteboard values,
  extension payloads, or WebView messages without validating origin, target,
  action, and embedded identifiers.
- Do not keep WKWebView bridges broad, stringly typed, or available to
  third-party/untrusted content.
- Do not ship debug ATS exceptions, debug API origins, entitlement drift, broad
  associated domains, or vague permission purpose strings in release builds.
- Do not install both Firebase Crashlytics and Sentry by default. Require a
  written reason and verification plan for duplicate crash providers.
- Do not send access tokens, refresh tokens, private API payloads, user content,
  secrets, local file paths, or raw server responses to crash breadcrumbs,
  logs, screenshots, attachments, analytics, or custom keys.
- Do not add crash, analytics, or telemetry SDKs without checking current
  pricing/quotas and the repo's consent, privacy, and open-source posture.
- Do not use UserDefaults, `@AppStorage`, plist files, cache directories, app
  group containers, or crash custom keys as a shortcut for token, credential,
  role, entitlement, personal, or regulated data storage.
- Do not put large product data, queryable records, histories, or offline
  domain datasets in Keychain only because the data is sensitive. Split secrets
  into Keychain and product records into a storage layer with a protection,
  cleanup, and sync model.

## Tests

Cover permission denied and revoked states, malformed Universal Links or URL
schemes, stale auth after app restart, Keychain read/write failure when
applicable, WebView bridge misuse when present, crash provider initialization in
debug/release channels, PII scrubbing for crash metadata, UserDefaults default
and cleanup behavior for non-sensitive preferences, and release-build entitlement
or signing configuration when changed.
