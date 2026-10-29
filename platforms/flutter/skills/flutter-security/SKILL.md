---
name: flutter-security
description: "Flutter Security: Use when Flutter work touches credentials, secure storage, platform channels, plugins, WebViews, deep links, local files, clipboard, notifications, network clients, logs, analytics, crash reports, release builds, signing, or open-source-safe setup."
keyflow_id: sys_platforms_flutter_flutter_security_md_skill
status: review
type: ai-generated
---

# Flutter Security

Use when Flutter work touches credentials, tokens, secure storage, biometrics,
platform channels, plugins, WebViews, deep links, local files, clipboard,
notifications, network clients, logs, analytics, crash reports, sensitive OS
data (health, photos, location), release builds, or signing.

Do not use for UI-only or pure-logic changes with no data, input, or release
surface.

## Read

- `references/current-guidance.md` for rules, review questions, and
  verification.
- `common/skills/secure-development-baseline/SKILL.md` and
  `common/skills/security-privacy-review/SKILL.md`.
- `platforms/flutter/skills/flutter-platform-integration/references/mobile-native-bridges.md`
  for sensitive OS data minimization and permission flows.

## Stop If

- A secret would ship in Dart code, assets, generated config, or fixtures.
- Sensitive OS data would leave the device without a documented purpose and
  consent path.

## Verification

- Inspect the diff for secrets, broad channel methods, unsafe logs, and
  link/WebView exposure, and smoke the privileged path on each target.
