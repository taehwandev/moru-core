---
keyflow_id: sys_flutter_project_structure
status: review
type: human-reviewed-needed
---

# Flutter Project Structure

Use when deciding Flutter feature folders, Dart package boundaries, monorepo
packages, plugin/federated plugin splits, package exports, or where new Dart and
native platform code should live.

This card follows current Flutter guidance: apps should keep clear UI/data
boundaries, use packages for modular reusable code, and split plugins into
app-facing, platform-interface, and platform-implementation packages when the
platform boundary needs that strength.

References:

- Flutter app architecture:
  `https://docs.flutter.dev/app-architecture/guide`
- Developing packages and plugins:
  `https://docs.flutter.dev/packages-and-plugins/developing-packages`
- Using packages:
  `https://docs.flutter.dev/packages-and-plugins/using-packages`

## Default Rule

Start with the smallest owner boundary that works:

```text
private file -> feature folder -> app package library
-> local package -> plugin package -> federated plugin family
-> published package/API
```

Use folders inside one app package until reuse, plugin boundaries, build
ownership, or dependency leakage justifies a package. A package split without a
stable export surface usually adds `pubspec.yaml` overhead before it adds value.

## File And Class Split

Apply `common/skills/code-structure-ownership/SKILL.md` before growing Dart files.
Default to one primary public widget, controller, notifier, view model,
repository, service, DTO, mapper, adapter, fixture, or test assertion owner per
Dart file. Private helper widgets or functions may stay near a single caller
only while they share the same review and test path.

Split files before adding behavior when a feature file mixes separate owners
such as route, view, state owner, widget section, repository contract,
repository implementation, service, DTO, mapper, platform channel wrapper,
fixture, and golden helper.

Review must fail when a Dart runtime file keeps multiple independently
importable owners in one file: widgets, controllers, notifiers, view models,
repositories, services, DTOs, mappers, adapters, platform-channel wrappers,
fixtures, or assertion helpers.

Do not:

- Put a route, screen, view model, repository, DTO, mapper, and platform service
  in one Dart file because they are small or feature-local.
- Export multiple unrelated public classes from one file or barrel library.
- Use `part` files, nested classes, or broad `common.dart`, `helpers.dart`, or
  `services.dart` files to hide unrelated responsibilities.
- Create a package split when purpose-named files inside the app package would
  solve the review and ownership problem.

## Project Families

Use repo-local names first. Flutter apps commonly separate these families:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| App package | App entry points, flavors, dependency injection, routing shell, localization setup, top-level theme. | Feature internals, raw plugin channels, data-source details. |
| Feature folder/package | Views, view models/state owners, feature widgets, feature routes, UI display models. | Shared design primitives, platform channel schemas, repository internals. |
| Domain package | Use cases/interactors, product policies, domain models, typed failures. | Flutter widgets, `BuildContext`, plugin DTOs, database rows. |
| Data package | Repository contracts and implementations, services, DTO mapping, cache/network/storage coordination. | Widgets, routes, snackbars/dialogs, platform channel strings scattered in UI. |
| Design-system package | Theme, tokens, reusable widgets, semantics/focus contracts, golden fixtures. | Product routes, analytics, repositories, permission policy. |
| Platform-services package | Typed wrappers around plugins, MethodChannel/EventChannel, lifecycle, permissions, files, notifications. | Feature-specific UI decisions or hidden global state. |
| Plugin package | App-facing API plus native/web implementations for one platform capability. | App-specific product flows or screen state. |
| Federated plugin family | App-facing package, platform interface, and independent platform implementations. | Direct app dependencies on implementation packages unless intentionally non-endorsed. |
| Test support package | Fakes, fixtures, golden helpers, mock services, deterministic clocks. | Production behavior required by app code at runtime. |

## Split Decision

Keep a feature as folders in one app when:

- it has one app caller and one implementation
- no other package needs to import its contract
- dependencies are acceptable to the app package
- the state and route contract are still changing
- analyzer, widget tests, and previews/goldens can be scoped without a package

Create a local Dart package when:

- multiple apps or features need the same stable contract
- the code should be tested without booting the app
- the dependency graph should hide heavy SDKs, generated clients, or storage
- the package can expose a small public library and keep internals under
  `lib/src`
- a monorepo workflow already supports package-level analysis and tests

Create a plugin package when:

- Dart code must call Android, iOS, macOS, Windows, Linux, or web platform APIs
- channel payloads, lifecycle, permission, and unsupported-target behavior need
  a typed boundary
- native setup belongs in a package rather than scattered app code

Create a federated plugin family when:

- platform implementations can evolve independently
- a platform domain expert may own one implementation
- callers should depend on one app-facing API while platform packages register
  themselves
- a platform-interface package can keep implementations compatible

## Dependency Direction

Keep dependencies explicit:

```text
app
  -> feature packages/folders, design system, platform service contracts
feature
  -> state owner, domain/use cases, repository contracts, design system
domain
  -> repository contracts and pure Dart models
data implementation
  -> repository contracts, services, DTOs, storage/network/plugin wrappers
platform service
  -> plugin/channel implementation and typed payload mappers
plugin app-facing package
  -> platform interface
plugin platform implementation
  -> platform interface and native/web code
```

Forbidden edges:

- widget/view -> repository implementation, raw MethodChannel, database row,
  DTO, or platform-specific map
- domain -> Flutter widgets, `BuildContext`, controllers, platform channels, or
  plugin implementation packages
- design system -> feature route, repository, analytics label, permission prompt
- app-facing plugin package -> app-specific feature or product policy
- package public export -> unstable `src` internals

## Feature Layout

Inside an app package:

```text
lib/
  main.dart
  app/
    app.dart
    router.dart
    di.dart
  features/profile/
    profile_route.dart
    profile_view.dart
    profile_view_model.dart
    profile_state.dart
    widgets/
    fixtures/
  data/
  domain/
  design_system/
```

Inside a reusable package:

```text
packages/profile/
  pubspec.yaml
  lib/profile.dart          public exports
  lib/src/                  private implementation
  test/
```

Expose only caller-facing types from `lib/<package>.dart`. Keep implementation
files under `lib/src` so callers do not build accidental dependencies on
unstable internals.

## Repository And Service Layout

```text
repository/
  profile_repository.dart       contract or app-facing repository
  profile_repository_impl.dart  implementation when local to package
model/
  profile.dart                  domain/display-safe model
service/
  profile_api.dart              remote service
  profile_cache.dart            storage service
dto/
  profile_response.dart         transport model
mapper/
  profile_mapper.dart           DTO/cache/plugin -> domain mapping
```

Repositories are the source of truth for model data. Services own external API,
plugin, storage, or platform calls. DTOs, rows, and channel payloads should not
cross into views or domain unless they are intentionally the public contract.

## Migration Strategy

When modernizing an old Flutter app:

1. Record imports, provider scopes, routes, generated files, native setup, and
   package dependencies before moving files.
2. Extract view state, repository contracts, and platform service contracts
   before moving implementation.
3. Move widgets and state owners feature-by-feature; avoid global `lib/common`
   dumping grounds.
4. Convert reusable code into a local package only after its public exports are
   stable.
5. Move raw MethodChannel/EventChannel code behind a typed service or plugin
   before changing feature behavior.
6. Run package-level analyzer/tests and at least one app-level smoke/build path
   for moved boundaries.

## Review Checklist

- Is a folder, package, plugin, or federated plugin the lowest boundary that
  protects the real owner?
- Does every package expose a small public library and keep internals in
  `lib/src`?
- Are views free of business logic, raw channels, DTOs, repositories, and
  storage details?
- Are domain models free of Flutter framework and plugin implementation types?
- Are package path dependencies relative and portable when committed?
- Are platform unsupported states, permission denial, lifecycle, and listener
  cleanup covered by tests or smoke checks?
