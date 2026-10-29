---
name: flutter-review
description: "Flutter Review: Use when reviewing Flutter widgets, state owners, Dart packages, repositories, platform channels, plugins, target setup, or mobile/desktop/web behavior."
keyflow_id: sys_platforms_flutter_flutter_review_md_skill
status: review
type: ai-generated
---

# Flutter Review

Use when reviewing a Flutter diff: widgets, state owners, Dart packages,
repositories, platform channels, plugins, native code, target setup, release
configuration, or mobile/desktop/web behavior.

Do not use as an implementation guide; load the matching Flutter card for the
change itself.

## Read

- `references/current-guidance.md` for findings priority, checks, approval
  blockers, and output shape.
- `references/mobile-release-checks.md` when the diff touches build setup,
  signing, target SDK, permissions, privacy disclosures, or store submission.
- `platforms/flutter/skills/flutter-architecture/references/reusable-layers.md`
  when the diff adds a shared layer, package, or fake.

## Verification

- Confirm analyzer/test/build evidence exists for each affected package and
  target, or record the gap as residual risk in the review output.
