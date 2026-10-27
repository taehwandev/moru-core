---
keyflow_id: sys_ui_visual_verification
status: stable
type: human-reviewed-needed
---

# UI Visual Verification

Use when changing UI layout, interaction, visible text, controls, navigation,
responsive behavior, accessibility labels, or state presentation.

## Default

A build or typecheck proves that UI code compiles. It does not prove that the UI
is usable, visible, readable, or wired to the intended action.

Verify the user path, not only the component in isolation, when the change
affects navigation, commands, permissions, persistence, or cross-surface state.

## Check

- Main success path.
- Empty, loading, disabled, error, unavailable, and permission-denied states.
- Long text, localized text, missing images, missing icons, and slow data.
- Grouped and decimal numeric text, unit labels, measurements, and value+unit
  pairs in compact labels, badges, tables, charts, summary cards, tooltips,
  notifications, and accessibility labels.
- Small and large viewports or containers relevant to the product.
- Touch and coarse-pointer input: any menu, dropdown, tooltip, popover, or
  control that is revealed or triggered only on `:hover`/`group-hover`/
  `focus-within` must also open and be fully operable by tap/click. Touch
  devices have no hover, so verify at a touch/mobile viewport, not only desktop
  hover.
- Light mode, dark mode, increased system font size, reduced motion, and high
  contrast when the platform supports them and the change can be affected.
- Keyboard focus, screen reader labels, hit targets, and visible focus state.
- Whether text, icons, badges, menus, or overlays overlap or resize the layout
  unexpectedly.
- Whether multiple entry points for the same command produce the same result.
- Whether visual state updates after actions, retries, refreshes, or navigation.

## Detail & Craft Gate

When building, restyling, or polishing user-facing surfaces, verify these six
craft invariants against the rendered target runtime (see
`common/skills/minimal-visual-design/references/platform-craft-matrix.md` for
platform-specific recipes):

- **Zero layout jitter**: Numeric updates use tabular figures (`tabular-nums`,
  `.monospacedDigit()`), hover/focus states do not shift sibling widths,
  scrollbars reserve stable gutter space, and skeleton/loading placeholders
  match loaded geometry without jumping adjacent content.
- **Single-owner insets & keyboard avoidance**: Status bar, navigation bar,
  safe-area, and software-keyboard/IME insets are consumed exactly once. Verify
  with keyboard open and closed that bottom actions are neither clipped nor
  double-padded.
- **Unclipped text scaling & optical alignment**: No fixed height on text
  containers; verify at `AX3`-`AX5` (iOS), `fontScale = 2.0f` (Android), or
  `textScaler = 2.0` (Flutter) that text wraps or reflows cleanly, and that
  leading icons and unit labels align to the first text baseline.
- **Forgiving hit targets & input parity**: Touch targets measure at least
  `44x44pt` (iOS) / `48x48dp` (Android), input affixes/padding focus the field on
  click, interactive controls prevent accidental text selection, and desktop/web
  controls expose visible `:focus-visible` rings and keyboard shortcuts.
- **Actionable state & formatted values**: Empty, loading, partial, and error
  states preserve user input and provide a concrete next action; numbers, dates,
  and units are locale-formatted (never raw floats or internal enum strings).
- **Content-to-edge padding**: Text and icons clear every painted edge (fill,
  border, shadow) by at least 8px inside a control and 12px inside a card,
  panel, row or dialog, and mobile text clears the viewport edge by 16px. Run
  `## Content-To-Edge Padding Check`; reading the stylesheet or modifier chain
  is not proof.

## Content-To-Edge Padding Check

Run after building, restyling or polishing any surface, and again after a
refactor that touches its markup or modifiers. Padding is the most often
dropped detail, and a code read misses it because the inset can come from the
element, a child margin, a layout gap or nothing at all.

- Measure rendered geometry: the distance from the nearest text or icon box to
  the inner edge of each painted surface, on all four sides. Computed `padding`
  alone misses escaping children and padding supplied elsewhere.
- Check at a narrow (about 375) and a wide (about 1280) width, with large text,
  and at the start and end of each scroll area, including nested ones and
  under fixed headers or footers.
- Inspect screenshots at native scale or zoomed in. A downscaled capture
  cannot tell 0px from 12px.
- Every reported surface is a failure unless it is intentional full-bleed
  media, a divider, or an edge-to-edge row whose content carries its own inset;
  say which exception applies.

Web (DevTools console or Playwright `page.evaluate`; thresholds are control,
surface and mobile gutter):

```js
((control = 8, surface = 12, gutter = 16) => {
  const sides = ["Top", "Right", "Bottom", "Left"];
  const painted = (el, s) => !/^(rgba\(0, 0, 0, 0\)|transparent)$/.test(s.backgroundColor)
    || sides.some((side) => parseFloat(s[`border${side}Width`]) > 0 && s[`border${side}Style`] !== "none")
    || s.boxShadow !== "none";
  const content = (root) => {
    const rects = [], walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node; (node = walk.nextNode());) {
      if (!node.textContent.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      rects.push(...[...range.getClientRects()].filter((r) => r.width && r.height));
    }
    for (const el of root.querySelectorAll("svg, img, video, input, select, textarea")) {
      const r = el.getBoundingClientRect();
      if (r.width && r.height) rects.push(Object.assign(r, { media: el.matches("img, video") }));
    }
    return rects;
  };
  const tight = [];
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el), box = el.getBoundingClientRect();
    if (box.width < 24 || box.height < 16 || el.matches("img, svg, video, canvas, hr, input, select, textarea") || !painted(el, s)) continue;
    const inner = { left: box.left + parseFloat(s.borderLeftWidth), right: box.right - parseFloat(s.borderRightWidth),
      top: box.top + parseFloat(s.borderTopWidth), bottom: box.bottom - parseFloat(s.borderBottomWidth) };
    // Full-bleed media spanning the surface is intentional; everything else needs clearance.
    const rects = content(el).filter((r) => !(r.media && r.width >= (inner.right - inner.left) - 1)
      && r.bottom > inner.top && r.top < inner.bottom && r.right > inner.left && r.left < inner.right);
    if (!rects.length) continue;
    const min = el.matches("button, a, [role=button], label, span, li, td, th") && box.height < 56 ? control : surface;
    const gaps = { left: (r) => r.left - inner.left, right: (r) => inner.right - r.right, top: (r) => r.top - inner.top, bottom: (r) => inner.bottom - r.bottom };
    const short = Object.entries(gaps).map(([side, gap]) => [side, Math.round(Math.min(...rects.map(gap)))]).filter(([, gap]) => gap < min);
    if (short.length) tight.push(`${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}.${[...el.classList].join(".")} needs ${min}: ${short.map((e) => e.join("=")).join(" ")}`);
  }
  const width = document.documentElement.clientWidth;
  const edge = width < 600 ? content(document.body).filter((r) => r.left < gutter || r.right > width - gutter).length : 0;
  return { width, tight, textInsideGutter: edge };
})();
```

Native equivalents compare the content node's bounds with its surface's inner
bounds in the same units:

- Compose: tag surface and content, read `getBoundsInRoot()` from the unmerged
  tree (`useUnmergedTree = true`); merged touch bounds are not layout bounds.
- SwiftUI: `.padding()` must come before `.background()`/`.overlay()` to inset
  content inside the fill; verify with the view debugger or a snapshot test.
- Flutter: compare `tester.getRect(find.text(...))` with the surface's
  `tester.getRect(...)` in a widget test.

## Tools By Platform

Use repo-local tooling first. Common evidence sources include:

- Web: Playwright, Testing Library, axe, browser screenshots, geometry checks.
- Android: Compose UI Test, Espresso, screenshot or layout inspection, and the
  host-driven device MCP in `common/skills/local-tools/references/device-mcp.md`
  when the surface has to be captured from the running app.
- iOS: XCUITest, accessibility inspector, previews, screenshot checks.
- Desktop/application: platform smoke tests, WebDriver/Playwright when
  applicable, screenshot checks, menu/tray/window interaction smoke.

Also load `common/skills/accessibility-i18n/SKILL.md` for user-facing text, forms, labels,
dates, numbers, units, measurements, localization, focus, or screen-reader behavior. Load the
matching platform review card when platform UI tooling or conventions matter.

## Evidence

Use the strongest practical evidence available:

- component, view, or interaction tests for deterministic behavior
- accessibility-tree or semantic assertions for labels, roles, and states
- screenshot, pixel, geometry, or layout smoke checks for visual regressions
- manual smoke when automation cannot observe the affected surface

State what the check can and cannot prove. Geometry does not prove contrast or
copy quality. A screenshot does not prove that the command executed. A visible
button does not prove that the trusted boundary behind it was reached.

## Comparison Oracle And Evidence Budget

Define the comparison target before operating the UI. Use one of these explicit
oracles: a requirement or state invariant, the approved design frame, a known-good
build, or the pre-change behavior when the task claims a regression or improvement.
Current-state observation by itself can prove a state invariant, but it cannot
prove that behavior improved or that a regression disappeared.

For a before/after claim, run the same bounded scenario against the baseline and
candidate with the same device, display/orientation, flavor, theme, data state,
and entry point. Capture the baseline before replacing its build. On Android,
prefer the device MCP's in-memory `capture_baseline` and `compare_current` tools
when available; their pixel and semantic deltas describe what changed and do not
decide whether the candidate is correct. When the baseline cannot be reproduced,
verify only the explicit current-state invariant and report the comparative claim
as unverified.

Collect the smallest evidence pair that can falsify the acceptance criterion:
one baseline observation and one candidate observation for a stable state. Repeat
only after a failed action, an unstable state, or a conflicting result, and state
why the extra observation was needed. Reuse a valid pair while the build, device
state, scenario, and acceptance criterion remain unchanged; do not wander through
screens or recapture identical states for confidence alone.

Motion claims require matched temporal evidence, such as baseline and candidate
recordings or bounded frame sequences covering the same trigger and interval. A
single frame, a static pixel delta, or an element hierarchy cannot prove that an
animation was removed, added, or timed correctly.

## Figma parity gate

When a Figma frame or screenshot is part of the requirement, visual parity is a
blocking check rather than optional polish.

- Capture the full, uncropped surface on the requested device and flavor. The
  card boundary, surrounding inset, next section, system chrome, and relevant
  state must be visible. Capture it from the running app through the platform's
  device tooling; on Android that is the device MCP above. Computing geometry
  from the source — path maths on a vector, measured token values, a rendered
  preview — is a different claim than this gate makes and does not satisfy it,
  because it cannot show the surrounding inset, chrome or state.
- Compare the implementation with the exact frame side by side or by overlay.
  Record outer bounds, outer-edge insets, media ratio, title line count and
  ellipsis, title/footer gap, icon and button size, metadata slot separation,
  and unchanged caller variants.
- Check each meaningful variant independently. A passing default variant does
  not prove the other media types, states, or header/footer variants of the
  same component.
- Text containers must grow from content and padding. Do not force a Figma
  sample height with `height()` or `size()` to hide clipping; use padding and
  an explicit minimum only when the component contract requires one.
- Build, unit tests, semantic assertions, and JSON measurements are supporting
  evidence. None of them replaces the full-frame visual comparison.

If the reference is cropped, the implementation route is uncertain, or a
caller/variant cannot be identified, mark visual verification incomplete and
stop the completion report instead of filling the gap by inference.

## Existing Surface Detail Audit

Use when the request is to raise quality, polish, or QA an app or screen that
already exists, not to verify one diff. Detail defects hide in surfaces nobody
changed recently, so walk them on purpose instead of waiting for a diff.

1. Inventory every screen, sheet, and entry point, including nested and
   platform-specific hosts (for example a shared UI screen embedded in a
   native navigation stack).
2. Walk each screen against the checklist below and record findings as
   `file:line`, the symptom the user sees, the fix, and severity. Mark a
   finding inferred when it was not observed running.
3. Fix the most user-visible findings first in small reviewed slices. Ask
   before changing a layout or visual design the user approved; detail fixes
   are not a license to redesign.
4. Confirm gesture, typography, and density findings on a real device or
   simulator; source reading alone cannot show how text reads in a hand.

Checklist per screen:

- Value meaning: every number, date, fraction, progress, count, and badge has
  a label, unit, or unambiguous format; relative and absolute dates follow one
  rule; zero, one, and large values read correctly.
- Platform adaptation: text sizes, line heights, spacing, and hit targets use
  the target platform's baselines (phone reading body around 16-17pt/sp,
  touch targets 44pt/48dp) instead of values copied from a web or desktop
  build; system text scaling is honored without clipping fixed-height text.
- Control placement: preferences that persist across content (text size,
  font, theme) live in the platform's settings surface, not in a per-screen
  toolbar copied from the web; hover-only and desktop-width affordances are
  replaced.
- Dead or fake state: every button has a handler with a visible result, every
  event and effect has a consumer, every setting is applied where it claims
  to apply and persists across relaunch when users expect it; remove state
  fields nothing renders.
- System navigation: back gestures, predictive back, sheet dismiss, keyboard
  avoidance, and safe areas still work where system bars are hidden or
  replaced, including when the embedded screen has its own inner stack.
- States: loading, empty, error, offline, signed-out, and retry are present
  and use product copy rather than developer messages.
- Copy and locale: no hard-coded strings, every locale has every key, and web
  wording that does not fit a mobile context is rewritten.
- Release hygiene: debug logging, debug-only menus, and placeholder copy are
  absent from user builds.

Report the audit as a ranked list. Separate observed findings from inferred
ones, and name the surfaces that were not walked.

## Do Not Accept

- Do not treat a build, typecheck, or unit test as proof that a UI is readable,
  reachable, responsive, or accessible.
- Do not verify only the happy path when the changed surface has loading,
  empty, disabled, error, permission, offline, or long-text states.
- Do not approve a UI change from a cropped screenshot that hides the command
  entry point, overflow area, modal/sheet boundary, or next section.
- Do not ignore keyboard, focus, screen-reader labels, hit target, reduced
  motion, or high-contrast behavior when the change touches interaction.
- Do not accept hover-only reveal (`:hover`/`group-hover`/`focus-within`) as the
  sole way to open an actionable menu, dropdown, or control. Touch users cannot
  hover, so require an explicit tap/click toggle (with an outside-tap/escape
  close) and verify it on a touch/mobile viewport.
- Do not accept an unlabeled number, date, or fraction whose meaning depends
  on context the user cannot see.
- Do not accept text sizes, hit targets, or toolbar controls copied from a web
  build into a native app without re-deriving them for the platform.
- Do not accept a control or setting that has no visible effect, or that
  silently resets when the screen closes.
- Do not claim system back navigation works on a screen that hides system
  bars until the gesture was performed on a device or simulator.
- Do not claim visual verification when the assets, icons, fonts, or remote
  data failed to load in the checked environment.

## Report

Name the scenario, environment, action, expected result, observed result, and
remaining risk when verification is manual or partial.
