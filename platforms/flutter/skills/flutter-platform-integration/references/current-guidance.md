---
keyflow_id: sys_flutter_platform_integration
status: review
type: human-reviewed-needed
---

# Flutter Platform Integration

Use when Flutter work touches MethodChannel, EventChannel, plugins, native
callbacks, permissions, app lifecycle, background execution, isolates, secure
storage, files, share sheets, notifications, WebViews, desktop APIs, or web
platform behavior.

For plugin package shape, package exports, and federated plugin splits, also use
`platforms/flutter/skills/flutter-project-structure/SKILL.md`.

## Boundary Shape

```text
Widget/State Owner -> Platform Service -> Channel/Plugin Adapter
-> Native/Web Implementation
```

Keep channel and plugin details out of widgets and domain models.

## Rules

- Treat channel messages, plugin callbacks, deep links, files, URLs, clipboard,
  notifications, and web messages as untrusted input.
- Keep channel names, method names, event names, and payload schemas centralized
  and version-aware when they are shared with native code.
- Map platform failures into typed Dart failures and user-safe messages.
- Define unsupported behavior for targets that lack a plugin, permission,
  browser API, desktop capability, or background execution mode.
- Own and dispose event streams, native listeners, controllers, isolates,
  timers, and plugin handles.
- Keep permission prompts and app lifecycle handling out of leaf widgets.
- Document target-specific setup, entitlements, manifests, signing, or native
  registration in repo-local docs, not in shared Moru Core cards.

## Stop If

- The target plugin or platform API is missing for a required app target and no
  fallback or disabled state is defined.
- Native setup, signing, entitlements, credentials, or store configuration is
  required but absent from repo-local instructions.
- A channel would need to expose broad filesystem, shell, credential, or native
  API access to untrusted UI input.

## Verification

- Run analyzer/tests plus the narrowest target build or smoke check for each
  affected platform when practical.
- Test channel payload parsing, unsupported target behavior, permission denied,
  cancellation, lifecycle resume/pause, and listener cleanup when affected.
- Review for broad channel APIs, dynamic payloads without validation, leaked
  native errors, missing disposal, and platform setup omitted from repo-local
  docs.
