---
keyflow_id: sys_common_ui_visual_verification_md_skill
status: stable
type: ai-generated
required_contract: core
---

# UI Visual Verification

Use when changing UI layout, interaction, visible text, controls, navigation, responsive behavior, accessibility labels, or state presentation.

## Read

The core below is the required contract. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## Check` for the full state, text, numeric, viewport and input checklist.
- `## Detail & Craft Gate` for micro-detail, inset, scaling, and layout-stability verification.
- `## Content-To-Edge Padding Check` whenever a surface (card, button, badge, input, row, dialog, page) was built, restyled, polished or refactored.
- `## Text Overlap Check` with it, and whenever a page places labels, captions or tooltips by script, canvas or 3D scene.
- `## Tools By Platform` for evidence tooling per platform and companion cards.
- `## Comparison Oracle And Evidence Budget` for before/after, regression or motion claims.
- `## Figma parity gate` for the parity measurement list when a design frame is the requirement.
- `## Existing Surface Detail Audit` for the per-screen audit checklist when raising the quality of, polishing, or QAing an existing app or screen.
- `common/skills/minimal-visual-design/SKILL.md` (and the active target platform section of `common/skills/minimal-visual-design/references/platform-craft-matrix.md`) when building, restyling, or raising visual craft on a UI surface without a conflicting repo design system.

## Must

- Treat build, typecheck and unit tests as proof of compilation only. Verify the user path, not only the component, when the change affects navigation, commands, permissions, persistence or cross-surface state.
- When raising quality, polishing, or auditing an existing app or screen (rather than verifying a single diff), execute the **Existing Surface Detail Audit** loop (`references/current-guidance.md` `## Existing Surface Detail Audit`): (1) inventory every screen, sheet, and entry point including nested/platform hosts; (2) walk each surface against the reference checklist (value meaning, platform adaptation, control placement, dead/fake state, system navigation, and non-happy states), recording `file:line`, user-visible symptom, fix, severity, and observed vs. inferred status; (3) fix the highest-impact findings in small reviewed slices without unapproved redesign; and (4) verify gestures, typography, and density on a real device or simulator.
- Check the success path plus empty, loading, disabled, error, unavailable, offline and permission-denied states; long/localized text, missing images/icons, slow data; numeric, unit and value+unit text; relevant viewports; light/dark, font size, reduced motion, high contrast when supported.
- Every visible value says what it is: a bare number, date, fraction, count or badge needs a label, unit or format that cannot be read as another quantity (a month/day `10/20` reads as page 10 of 20).
- Values ported from another platform are re-derived for the target, not copied: web px/rem text sizes, line heights, hit targets, density and hover/toolbar controls get the target platform's reading, touch and settings conventions.
- Every control, setting and state field has a visible effect and the persistence users expect; wire or remove state that is stored but never rendered, or reset when the screen closes.
- Hiding or replacing system chrome must keep system navigation working on every stacked screen (edge swipe back, predictive back, sheet dismiss); only a real device or simulator gesture proves it.
- Check micro-detail craft: zero layout shift on hover/async/numeric changes (`tabular-nums` / `.monospacedDigit()`), single-owner safe-area/IME inset consumption without double padding, unclipped text at `AX5` / `fontScale 2.0` / `textScaler 2.0`, concentric nested radii, actionable recovery in empty/error states, and measured content-to-edge padding and page gutter (text or icons touching a painted edge or the mobile screen edge fail).
- Check keyboard focus, screen-reader labels, hit targets, visible focus; measured text overlap (a label or caption covering other text or a control fails) or unexpected resize; same result from every entry point; state updating after actions, retries, refreshes, navigation.
- Hover-only reveal (`:hover`/`group-hover`/`focus-within`) is never the sole way to open an actionable menu or control: require a tap/click toggle with outside-tap/escape close, verified at a touch/mobile viewport.
- Use repo-local tooling first and the strongest practical evidence: interaction tests, semantic assertions, screenshot/geometry checks, manual smoke only when automation cannot observe it. Load `common/skills/accessibility-i18n/SKILL.md` for text, forms, numbers, units, localization, focus or screen readers.
- State what each check can and cannot prove: geometry is not contrast, a screenshot is not command execution, a visible button is not the trusted boundary reached.
- Define the comparison oracle before operating the UI: requirement or state invariant, approved design frame, known-good build, or pre-change behavior. Current state alone cannot prove an improvement or a fixed regression.
- Before/after: same bounded scenario, device, display, flavor, theme, data state and entry point; capture the baseline before replacing its build. Collect one baseline and one candidate observation; repeat only after a failure, instability or conflict, and say why. No recapturing for confidence.
- Motion claims need matched temporal evidence; a single frame, pixel delta or hierarchy cannot prove them.
- Figma parity is blocking: capture the full, uncropped surface from the running app on the requested device and flavor; compare side by side or by overlay; check each variant independently. Source-computed geometry does not satisfy it. Text containers grow from content and padding; never force a sample height with `height()`/`size()` to hide clipping.

## Stop If

- The Figma reference is cropped, the implementation route is uncertain, or a caller/variant cannot be identified: mark visual verification incomplete and stop the completion report.
- The only screenshot is cropped and hides the entry point, overflow, modal/sheet boundary or next section.
- Assets, icons, fonts or remote data failed to load in the checked environment; do not claim visual verification.
- The baseline cannot be reproduced: verify only the current-state invariant and report the comparative claim unverified.

## Verification

- Report scenario, environment, action, expected result, observed result, and remaining risk when verification is manual or partial.
- Name the oracle used and which claims stay unverified.
