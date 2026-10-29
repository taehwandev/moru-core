---
name: performance-verification
description: "Performance Verification: Use when changing or reviewing performance, loading behavior, rendering cost, startup, frame time, memory, bundle size, binary size, query latency, cache behavior, background work, animation smoothness, or runtime resource use."
keyflow_id: sys_common_performance_verification_md_skill
status: stable
type: human-reviewed-needed
metadata:
  internal: true
---

# Performance Verification

Use when changing, reviewing, or reporting performance across any platform.

## Read

- `references/current-guidance.md` for the all-platform performance proof rules.
- `../web-performance-verification/SKILL.md` when the measured surface is browser
  or web runtime behavior.
- The matching platform performance, profiling, visual verification, or release
  readiness skill when the target platform has specialized tooling.

## Process

1. Name the performance claim, user path, and affected boundary.
2. Choose the smallest metric and environment that can prove or disprove it.
3. Treat development tools, previews, hot reload, emulators, and inspection
   counts as diagnostic unless the source explicitly defines them as production
   evidence.
4. Change one plausible cause at a time, then re-measure.
5. Report whether the result proves the claim or only reduces structural risk.

## Do Not

- Do not call a change a performance fix from code shape alone.
- Do not compare debug/development evidence against release/production claims.
- Do not optimize performance by weakening correctness, accessibility,
  security, lifecycle, or recovery behavior.

## Verification

- Run the narrowest available measurement, benchmark, profile, release build,
  trace, or repo-provided performance check for the changed path.
- If measurement tooling is unavailable, state that no performance claim is
  proven and report the change as structural risk reduction only.
