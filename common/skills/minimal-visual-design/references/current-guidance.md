---
keyflow_id: sys_common_minimal_visual_design_guidance
status: review
type: ai-generated
---

# Minimal Visual Design

Concrete defaults for a quiet, refined interface. They are a starting point
when a repository has no design system of its own; existing tokens, brand
guides, and design sources take precedence. Values are given in CSS pixels;
map them to the platform's units (pt, dp) and token holders.

## Direction

- Derive the look from the subject: who uses it, for what job, in what
  setting. "Clean and modern" is not a direction.
- Minimal means fewer, better decisions, not fewer affordances. Every
  remaining element should be legible, aligned, and clearly interactive when it
  is interactive.
- Work in two passes: draft the compact system and a rough layout, review it
  against the brief, replace anything that reads as a generic default, then
  build.

## Typography

- One family is enough; two at most (for example a display cut for headings).
  Prefer a well-hinted neutral sans or the platform system font over a novelty
  face.
- Use a fixed scale and two or three sizes per component, for example
  12 / 14 / 16 / 20 / 24 / 30 / 36 / 48. Body text is at least 16px on the web.
- Weights: 400 body, 500 labels, 600 headings and buttons. Avoid 300 for body
  text and 800+ anywhere.
- Line height: 1.5 for body, 1.2-1.3 for headings, about 1.0-1.2 for single-line
  controls.
- Tighten large headings slightly (about -0.01em to -0.02em); keep body
  tracking at 0. Widen tracking only for rare all-caps text.
- Keep reading lines under about 70-80 characters. Use tabular figures for
  numbers that are compared in columns.
- Secondary text is a lighter color, not a smaller size, wherever possible.

## Space And Layout

- Use one spacing scale on a 4px base: 4, 8, 12, 16, 24, 32, 48, 64, 96.
  Never invent a one-off value.
- Space communicates grouping: related items sit closer than unrelated ones.
  Space between groups should be clearly larger than space inside them.
- Start with more whitespace than seems necessary, then remove.
- Align every element to a shared edge, grid, or baseline. Apply a 1px optical
  nudge when an icon or glyph looks off-center.
- One primary element per view. One filled primary button; secondary actions
  are outlined or subtle, tertiary actions are text-only.
- Nested corner radii are concentric: an inner radius is the outer radius
  minus the padding between them, never larger than the outer one.
- Hit targets are at least 24px with a pointer and 44px on touch, even when the
  visible control is smaller.

## Padding And Insets

Agents most often drop padding, not spacing between items: a surface gets its
color, radius and shadow, and its text still touches the edge. Padding is a
relationship between a container and its content, so set it whenever you set a
surface, and measure it on the rendered result.

Keep three kinds of space apart, and give each one owner:

- **Padding**: the inset between a painted edge and the content inside it.
- **Gap**: the space between siblings, set on the parent layout (`gap`,
  `spacing`, `Arrangement.spacedBy`), never as margins on every child.
- **System inset**: safe area, status/navigation bar, keyboard and fixed
  header/footer clearance, consumed once at the screen owner. It is added to the
  page gutter, not used in place of it.

Rules:

- **Painted-surface inset**: any element with a fill, border, outline, tonal
  step or shadow has non-zero padding on every side that holds text or icons.
  Only full-bleed media, dividers and an intentional edge-to-edge row (whose
  content then carries its own inset) are exempt.
- **Padding lives on the element that paints**: a full-width child with its own
  background (`width: 100%`, `fillMaxWidth`, `double.infinity`) carries its own
  padding; the parent's padding does not reach inside it.
- **Scrolling content pads inside the viewport**: put the inset on the scrolled
  content (`contentPadding`, inner padding, `.contentMargins`, `scroll-padding`)
  so the first and last items clear the edge and any fixed bar by at least 16px,
  instead of padding an outer wrapper that clips.
- **Nothing else stands in for padding**: a sibling gap, an outer margin, a
  minimum height or an enlarged hit region does not create clearance inside a
  painted edge.
- **Rows align to the container**: list rows and the first and last table
  columns use the same horizontal inset as their card or page, so text lines up
  on one edge.
- **Polish and refactor keep padding**: a cleanup that removes wrappers,
  borders or decoration keeps the padding that framed the content, or says in
  the report why it changed. "Remove what carries no meaning" never applies to
  padding.

Defaults, on the 4px scale (CSS px; map to pt/dp):

| Surface | Default padding |
| --- | --- |
| Page side gutter | 16 below 600 wide, 24 from 600, 32 from 1024 with a max-width column |
| Card or panel | 16 (12 dense, 24 roomy) |
| Dialog or sheet | 24 (16 on narrow screens); actions row keeps the bottom inset plus safe area |
| Button | 8-12 vertical, 16 horizontal (12 compact); horizontal is at least 1.5x vertical |
| Chip | 4-6 vertical, 12 horizontal |
| Badge or pill | 2-4 vertical, 8 horizontal; never 0 against a rounded end |
| Input or select | 8-12 vertical, 12 horizontal; same clearance around prefix and suffix icons |
| List row | 12 vertical, 16 horizontal (matching the gutter) |
| Table cell | 8-12 vertical, 12-16 horizontal |
| Toolbar or app bar | 8 vertical, 16 horizontal (matching the gutter) |
| Section rhythm | 48-64 between sections, 16-24 inside a group |

Measure, do not trust the stylesheet: on the rendered screen the nearest text
or icon box sits at least 8px from the painted edge of a control and at least
12px from a card, panel, dialog or row, and mobile body text sits at least 16px
from the viewport edge. Padding can come from the element, a child's margin or
a layout gap, so the check is rendered geometry, not the computed `padding`
value. Use the content-to-edge check in
`common/skills/ui-visual-verification/references/current-guidance.md`.

## Color

- Build a neutral ramp of 9-10 steps, tinted slightly warm or cool, instead of
  pure gray. Use near-black (around #171717) rather than #000 for text, and an
  off-white or very light neutral for large surfaces.
- Add one accent hue with 5-7 steps. Reserve it for primary actions, links,
  selection, and focus. Status colors (success, warning, danger) appear only
  for status.
- Generate ramps in a perceptual space such as OKLCH or LCH so steps at the
  same lightness look equally light across hues and themes.
- Define themes from a few inputs (base neutral, accent, contrast) rather than
  dozens of independent values; dark mode is a re-derivation, not an inversion.
- Hover, active, and focus states carry more contrast than the rest state.
- Body text meets at least 4.5:1 contrast. Never signal status by color alone;
  pair it with a label or icon.

## Depth And Edges

- Prefer separation by space or a one-step background change over borders.
- When a border is needed, keep it 1px and light; a semi-transparent border
  adapts to any surface.
- Shadows use two layers, a tight one for the edge and a soft one for ambient
  light, with one consistent light source. Keep to two or three elevation
  levels, for example:
  - raised: `0 1px 2px rgb(0 0 0 / 0.06), 0 1px 3px rgb(0 0 0 / 0.10)`
  - overlay: `0 4px 12px rgb(0 0 0 / 0.08), 0 16px 32px rgb(0 0 0 / 0.12)`
- On a tinted background, tint borders and shadows toward the same hue.
- Use one radius family (for example 6 / 10 / 16) across the product.

## Motion

- Animate only to show cause and effect: where something came from, what
  changed, where it went. Anchor motion to its source.
- Skip motion for high-frequency actions such as menus, command palettes, and
  keyboard navigation; they feel faster without it.
- Keep durations short (about 150-250ms for UI state changes), animate
  `transform` and `opacity`, and list properties explicitly instead of
  `transition: all`.
- Animations are interruptible and never block input. Honor reduced-motion
  settings.
- Delay a loading indicator by about 150-300ms and keep it visible for at
  least 300-500ms so fast responses do not flash.

## Micro-Detail & Interaction Craft

Apply these universal execution rules across every platform, and open the
matching platform section in
[platform-craft-matrix.md](platform-craft-matrix.md) (`Web & React`,
`iOS SwiftUI & UIKit`, `Android Jetpack Compose`,
`Flutter & KMP Compose Multiplatform`, `Desktop Application & CLI`, or
`Server, Python & API Contracts`) for native APIs and falsifying checks:

- **Zero layout jitter on value, hover, or async transitions**: Enable tabular
  numerals (`tabular-nums`, `.monospacedDigit()`, or `FontFeature.tabularFigures()`)
  on counters, timers, prices, percentages, and table columns. Never change font
  weight on `:hover`/`:active` without reserving width, reserve `scrollbar-gutter: stable`
  on scrollable containers, and match skeleton/loading placeholder geometry to
  the final loaded component.
- **Concentric corner geometry & optical alignment**: Compute nested radii as
  `r_inner = max(0, r_outer - padding)` so inner buttons, inputs, or media
  thumbnails share the outer card's curvature center. Align icon + text and
  metric + unit pairs to the first text baseline (`FirstBaseline` /
  `.firstTextBaseline`) and match icon stroke weight to the adjacent font weight.
- **Single-owner insets & unclipped text scaling**: Consume safe-area, system-bar,
  and software-keyboard/IME insets exactly once at the screen or scaffold
  boundary—never double-pad child containers. Never put a fixed height on
  text-bearing views; allow text to scale to `200%` / `AX5` / `textScaler 2.0`
  and reflow horizontal rows into vertical stacks when space is tight.
- **Forgiving hit targets & input ergonomics**: Expand interactive touch regions
  to at least `44x44pt` (iOS) / `48x48dp` (Android) / `24x24px` (desktop pointer)
  even when the visible glyph is smaller. Clicking any prefix, suffix, icon, or
  padding inside a text input container must focus the input, and interactive
  controls (`button`, tabs, chips, toggles) must disable accidental text
  selection (`user-select: none`).
- **Actionable state completeness**: Empty, loading, partial, offline,
  permission-denied, and error states must preserve user draft input, state what
  happened in plain language, and offer a concrete recovery action (retry, clear
  filter, or copyable remediation command)—never a dead-end generic string or
  raw unformatted float/enum.

## Product & Scrollytelling Stages

- **Stage vs. reading-column separation**: When a sticky 3D/WebGL or canvas
  stage shares the viewport with scrolling narrative chapters, offset the focal
  subject horizontally on wide viewports so the narrative column and embedded
  UI showcases never collide with the primary silhouette.
- **Legible narrative backing**: Do not float unbacked body copy over a moving
  canvas whose luminance shifts across scroll progress. Use a quiet translucent
  panel (`backdrop-filter: blur(12px-16px)` with a 1px hairline border) only
  where needed to guarantee `>= 4.5:1` text contrast over the stage.
- **Chapter wayfinding**: Any sticky scroll narrative with three or more
  chapters needs a compact progress/navigation rail that shows the active
  chapter and lets the reader jump directly to any beat.
- **Luminance bridging**: Avoid hard cuts from a near-black canvas stage to a
  stark white section. Bridge dark narrative stages into light content sections
  through an intermediate twilight step or soft gradient transition.

## Scaled UI & Interactive Proof

- **Legibility floor for scaled app frames**: When embedding a faithful desktop
  or dashboard recreation via `transform: scale()`, keep the effective scale at
  or above `0.55x` on desktop viewports so 12-13px UI chrome never shrinks
  below ~7px and primary data/labels remain `>= 9.5px` effective. Widen the
  showcase container (for example 560-640px for a 1000px-wide frame) or trim
  secondary chrome instead of crushing a full window into a 400px text column.
- **Interactive proof over passive loops**: Product recreations should offer at
  least one genuine, low-friction interaction—filtering a live metric view,
  approving or replaying a state transition, or switching step tabs—paired with
  a subtle affordance hint. Auto-cycling timers are fine as a default preview,
  but user clicks and keyboard input must work and override the loop cleanly;
  never wrap interactive showcases in `role="img"` or `pointer-events: none`.

## System Architecture & Product Cards

- **Topology before catalog**: When presenting a multi-product suite or
  layered architecture, precede or pair the card grid with a numbered system
  flow strip (`01 -> 02 -> 03`) that shows how data, control, or workflow
  moves from one piece to the next.
- **Flagship vs. companion hierarchy**: Differentiate the primary user-facing
  workspace from supporting CLI/runtime utilities or sidecars using a subtle
  elevation step, border contrast, and a quiet status pill. Do not render a
  multi-part system as three identical cards with equal visual weight.
- **Actionable onboarding**: When an onboarding section asks the user to run
  prompts or commands, pair the copyable block with a numbered checklist of
  what happens before, during, and after the command, and use compact switcher
  tabs when two steps share the same structure.

## Generic Tells

Review the rendered screen against these default or AI-looking choices and
replace each one found:

- a purple-to-blue gradient hero, glowing blobs, or glassmorphism used as
  decoration rather than contrast backing over a live canvas
- a grid of identical cards with the same radius, shadow, and icon-in-circle,
  or a multi-product suite presented without a causal flow strip
- desktop UI recreations scaled below `0.5x` where text becomes unreadable
  micro-copy, or interactive-looking mockups locked behind `role="img"`
- multi-chapter scrollytelling pages with no chapter wayfinding rail or with
  the 3D focal subject centered directly behind unbacked body copy
- text or icons touching the edge of a card, button, badge, input, row or
  dialog, or mobile content flush against the screen edge
- every heading bold, every section boxed, every list item with a divider
- emoji or decorative icons in front of every label
- an eyebrow label above every heading, or one accented word in a headline
- several saturated colors competing on one screen
- centered body text in long paragraphs
- arbitrary spacing values that are not on the scale
- placeholder copy such as "Lorem ipsum" or "Welcome to your dashboard"

Copy is part of the visual result: write short, plain, sentence-case labels
and specific button text such as "Save changes" instead of "Submit".

## Sources

Ranked for relevance with the repository's research-triage adapter on
2026-10-13; all five scored above 0.95. Rules here are condensed and
re-derived, not copied.

- Anthropic, frontend-design skill:
  https://github.com/anthropics/claude-code/tree/main/plugins/frontend-design
- Refactoring UI tactical principles (third-party summary of the book by Adam
  Wathan and Steve Schoger):
  https://cdn.jsdelivr.net/npm/claude-code-skills@0.5.0/data/skills/ux-ui-design-system/references/refactoring-ui.md
- Linear, "How we redesigned the Linear UI":
  https://linear.app/now/how-we-redesigned-the-linear-ui
- Rauno Freiberg, "Invisible Details of Interaction Design":
  https://rauno.me/craft/interaction-design
- Vercel, Web Interface Guidelines: https://vercel.com/design/guidelines
