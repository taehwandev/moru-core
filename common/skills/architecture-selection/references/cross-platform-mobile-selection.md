---
keyflow_id: sys_cross_platform_mobile_selection
status: review
type: ai-generated
---

# Cross-Platform Mobile Stack Selection

Use when a new Android+iOS app, or a major rewrite, must choose between
Flutter, Kotlin Multiplatform with Compose Multiplatform (KMP/CMP), KMP with
native UIs, or two native apps. React Native is out of scope here; when a
web/React team is the deciding factor, start from
`platforms/react-native/skills/react-native-app/SKILL.md`.

Do not use for an existing app that already committed to a stack; follow the
repo's ARD and change stacks only through a new decision record.

## Inspect First

1. The team's current languages and the stacks they already maintain.
2. The native API surface the product needs: health/fitness stores, payments,
   camera, background work, widgets, watch apps, push.
3. UI expectations: one shared look, or platform-native look per OS.
4. Release constraints: deadline, number of maintainers, store review risks.

## Decision Factors

| Factor | Flutter | KMP + Compose Multiplatform | KMP + native UI | Two native apps |
| --- | --- | --- | --- | --- |
| Shared code | UI + logic in Dart | UI + logic in Kotlin | Logic only | None |
| Native API access | Plugins or own Kotlin/Swift behind typed channels | `androidMain` direct; iOS via cinterop or Swift implementations of Kotlin interfaces | Same as KMP, UI fully native | Direct |
| iOS interop cost | Channel boundary per API | Framework export, suspend/Flow bridging, Swift-only API slots | Same as KMP plus SwiftUI per screen | None |
| UI consistency | High UI sharing from one rendering engine; per-OS adjustments still needed | High UI sharing from one Compose UI; per-OS adjustments still needed | Native per OS | Native per OS |
| Ecosystem maturity on iOS | Mature plugin ecosystem | iOS target stable; multiplatform library choice narrower | Mature on each side | Mature |
| Fit for Kotlin/Android teams | Learn Dart and Flutter tooling | Reuse Kotlin, Compose, coroutines | Reuse Kotlin; need SwiftUI skills | Need both skill sets |
| Typical risk | Plugin permissions/maintenance, channel drift | iOS build/export friction, narrower library choice | Two UI implementations to maintain | Two UI and client implementations to maintain |

## Decision Rule

1. If the product needs few native APIs that both stacks can reach through a
   thin adapter, choose the stack the team can staff and ship fastest.
2. If the team already ships Kotlin/Compose and wants shared UI, prefer
   KMP + Compose Multiplatform; keep Flutter as the fallback.
3. If the team prefers one mature cross-platform toolkit with a broad plugin
   ecosystem, or has Dart/Flutter experience, prefer Flutter.
4. If platform-native UI fidelity is a core product requirement, prefer
   KMP + native UI or two native apps.
5. Whatever is chosen, put each native API behind a narrow interface with a
   typed status result so the decision stays reversible at the adapter level.

## Spike Before Committing

Run a one-week spike that implements the riskiest native call on real
devices for both targets, using the chosen stack:

- Read the required OS data and compare with the OS app's own value.
- Exercise grant, deny, revoke-then-resume, and provider-missing states.
- Build a signed internal test build for each store track.
- Record build times, iOS integration friction, and blockers in the ARD.

## Red Flags

- Choosing a stack for code sharing percentages without naming the native
  APIs and who will maintain the native code.
- Planning a broad health, payment, or media plugin when the product uses one
  narrow query; the plugin's declared permissions become store-review risk.
- No fallback stack named in the decision record.

## Verification

- The ARD names the chosen stack, the fallback, the spike results, and the
  native API adapters with their typed status values.

## Related

- `platforms/flutter/skills/flutter-platform-integration/references/mobile-native-bridges.md`
- `platforms/kmp/skills/kmp-platform-integration/references/mobile-targets.md`
