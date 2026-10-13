---
keyflow_id: sys_common_minimal_visual_design_guidance
status: draft
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

## Generic Tells

Review the rendered screen against these default or AI-looking choices and
replace each one found:

- a purple-to-blue gradient hero, glowing blobs, or glassmorphism used as
  decoration
- a grid of identical cards with the same radius, shadow, and icon-in-circle
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
