---
keyflow_id: sys_flutter_reusable_layers
status: review
type: ai-generated
---

# Flutter Reusable Layers

Use when a Flutter change adds or reshapes a repository, service, use case,
result/failure type, command, dependency wiring, design-system component, or
test fake, or when the request asks for code that other features or apps can
reuse.

Do not use to justify layers for a single unstable caller. Apply
`common/skills/reusable-code-design/SKILL.md` first: reuse is earned by a
second real caller or a stable contract, not by a template.

Official source: Flutter app architecture guide and recommendations,
`https://docs.flutter.dev/app-architecture/guide` and
`https://docs.flutter.dev/app-architecture/recommendations`.

## Reuse Ladder

Promote one level at a time, and only when the lower level stops protecting
ownership, tests, or dependency direction:

```text
private helper -> feature folder file -> app-level shared folder
-> local package (lib/src + public export) -> plugin package
```

## Layer Contracts

| Layer | Owns | Reuse Rule |
| --- | --- | --- |
| Service | One external system call surface: HTTP client, backend SDK, OS data store, local storage, platform channel. Stateless; returns DTOs or typed results. | Reusable across features; never imports widgets or state owners. |
| Repository | Source of truth for one domain model; combines services, caching, retries, and maps DTOs to domain models and typed failures. | One repository per data type, shared by every feature that needs it. |
| Use case (optional) | Product rule spanning repositories, or logic shared by several view models. | Add only when two callers share it or the rule needs isolated tests. |
| View model / state owner | Screen state and user intents; calls repositories or use cases. | Feature-owned; do not share view models across screens. |
| Design-system component | Visual and interaction contract driven by parameters and callbacks. | No repositories, routes, analytics names, or product copy inside. |

## Result And Failure Types

- Return a sealed result from services and repositories instead of throwing
  across layers:

```dart
sealed class Result<T> { const Result(); }
final class Ok<T> extends Result<T> { const Ok(this.value); final T value; }
final class Err<T> extends Result<T> { const Err(this.failure); final AppFailure failure; }
```

- `AppFailure` is a small sealed hierarchy (network, unauthorized, not found,
  permission, unavailable, validation, unknown) with no raw exception text in
  user-facing fields. Keep the raw cause for logging only.
- Switch exhaustively on both levels where the UI differs per failure: on
  `Result` and on the sealed `AppFailure` (or with nested patterns such as
  `Err(failure: PermissionFailure())`). Only a switch over `AppFailure`
  without a wildcard makes the analyzer flag callers when a failure kind is
  added.
- One `Result` and one failure hierarchy per app or shared core package; do
  not define per-feature variants.

## Command Pattern For User Actions (Optional)

When the repo's state tool does not already model per-action progress, and
the same running/error/retry handling repeats across screens, extract it into
one generic command object that exposes `running`, `error`, and `completed`
state. If Riverpod, BLoC, or the existing state owner already represents this,
use that instead; do not add a second state owner per action.

```text
View -> viewModel.share.execute()   // Command
Command -> running/error/result listenable -> View rebuilds
```

The command is generic over its argument and result; feature view models hold
instances, widgets bind to them. Prevent double submission by ignoring
`execute` while `running` is true.

## Dependency Wiring

- One composition root in the app package creates services, repositories, and
  overrides per flavor or environment.
- Features receive dependencies through constructors or the repo's chosen DI
  container; do not call a global locator inside widgets or repositories.
- Every service and repository is defined as an abstract interface (or a class
  with an overridable constructor) so tests and other apps can swap it.
- Environment values (API origins, project ids) come from flavors or
  `--dart-define`, read once at the composition root.

## Fakes And Test Support

- Ship a fake for each service/repository interface in a test-support folder
  or package; fakes are deterministic, in-memory, and configurable per test.
- Share fixtures (domain model builders, fixed clocks, fixed dates) through the
  same test-support owner instead of copying them per feature.
- Inject a clock and a time-zone source wherever logic depends on "today".

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "Every feature needs a use case layer." | Add a use case only for shared or isolated product rules. |
| "Throwing is simpler than a Result." | Throw only inside a layer; cross-layer calls return typed results. |
| "We will extract the package later, export everything now." | Keep internals in `lib/src` and export only the stable caller surface. |
| "The design-system button can read the theme provider and analytics." | Pass values and callbacks; components stay product-agnostic. |

## Red Flags

- A widget imports a service, DTO, generated channel client, or backend SDK.
- Two features define their own `Result`, failure, or date helper types.
- A repository returns DTOs or backend document snapshots to view models.
- Tests need network, emulator, or device access to check a product rule.

## Verification

- Unit tests for repositories (mapping, failure translation, caching) and view
  models (state transitions per command) using fakes only.
- Widget tests for shared components with large text scale and semantics.
- `flutter analyze` with exhaustive-switch lints enabled for result handling.
