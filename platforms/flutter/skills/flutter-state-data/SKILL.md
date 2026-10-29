---
name: flutter-state-data
description: "Flutter State And Data: Use when touching Flutter state owners, Riverpod, BLoC, Provider, ChangeNotifier, ValueNotifier, streams, repositories, storage, sync, isolates, or async effects."
keyflow_id: sys_platforms_flutter_flutter_state_data_md_skill
status: review
type: ai-generated
---

# Flutter State And Data

Use when touching Flutter state owners (Riverpod, BLoC/Cubit, Provider,
ChangeNotifier, ValueNotifier, or a local pattern), view models, commands,
streams, repositories, local storage, caching, remote backends, offline sync,
isolates, or async effects.

Do not use for purely visual widget changes or for native adapters with no
state change (use `platforms/flutter/skills/flutter-platform-integration/SKILL.md`).

## Read

- `references/current-guidance.md` for state defaults, state-tool rules,
  checks, and forbidden shapes.
- `platforms/flutter/skills/flutter-architecture/references/reusable-layers.md`
  for result/failure types, the command pattern, the repository/service split,
  and fakes.
- `common/skills/state-modeling/SKILL.md` and
  `common/skills/error-modeling/SKILL.md` for general state and failure shape.
- `common/skills/data-persistence-sync/SKILL.md` when storage, cache, or sync
  rules change.

## Stop If

- A persistence or cache format changes without versioning, migration, or reset
  rules for logout and account switch.

## Verification

- Unit-test state transitions and repository mapping with fakes, without
  pumping the whole app; cover cancellation and disposal paths.
