---
keyflow_id: sys_common_minimal_visual_design_md_skill
status: review
type: ai-generated
---

# Minimal Visual Design

Use when building or restyling a screen, landing page, product story, or
component whose visual quality matters and the result should look refined and
quiet rather than developer-default. Do not use it to decide token or component
ownership; that is `common/skills/design-system/SKILL.md`. A repository's
existing design system, brand guide, or Figma source always wins over this card.

## Read

Open `references/current-guidance.md` for the concrete rules:

- `## Direction` before the first visual decision.
- `## Typography`, `## Space And Layout`, `## Color`, `## Depth And Edges`,
  `## Motion` for the matching decision.
- `## Product & Scrollytelling Stages`, `## Scaled UI & Interactive Proof`, and
  `## System Architecture & Product Cards` when building landing pages,
  sticky canvas stories, or embedded product showcases.
- `## Generic Tells` when reviewing a draft for default or AI-looking choices.
- `## Sources` for the evidence behind each rule.

## Process

1. Name the product, audience, and primary job in one line. Pick one quiet
   direction that follows from them, not from habit.
2. Before writing UI code, draft a compact system: one or two typefaces with
   type roles, a 4/8-based spacing scale, a tinted neutral ramp plus one
   accent, two shadow levels, and one radius family. Reuse the repository's
   tokens when they exist.
3. Lay out in grayscale. Build hierarchy with weight, color, and space before
   size; one primary element and one filled primary action per view.
4. For product stories and landing pages, separate sticky canvas/3D stages from
   the reading column, keep scaled UI recreations above the legibility floor
   (`>= 0.55x` scale on desktop) with at least one real interactive affordance,
   and show system topology (`01 -> 02 -> 03`) before uniform spec cards.
5. Add the accent last, only on actions, selection, and status.
6. Remove every border, divider, badge, icon, and animation that carries no
   meaning. Then check the result rendered.

## Do Not

- Do not reach for the framework default look: stacked cards with identical
  radius and shadow, a gradient hero, and bold text everywhere.
- Do not use pure black text, pure gray, or more than one saturated hue.
- Do not separate every group with a border; use space or a background step.
- Do not shrink a desktop UI recreation below `0.5x` scale or lock an
  interactive-looking showcase behind passive `role="img"` wrappers.
- Do not place a sticky 3D/canvas focal subject directly behind unbacked body
  copy or omit chapter wayfinding on a multi-chapter scroll story.
- Do not animate frequent actions, use `transition: all`, or block input on
  an animation.
- Do not trade accessibility for minimalism: keep contrast, focus rings,
  labels, and hit targets.

## Stop If

- The repository already owns a design system or brand guide that conflicts:
  follow it and report the conflict instead of overriding it.
- The request needs a bold, maximal, or brand-expressive direction; this card's
  restraint is the wrong baseline.

## Verification

- View the rendered result in light and dark themes, at narrow and wide widths,
  with long text. A code diff alone is not visual evidence; use
  `common/skills/ui-visual-verification/SKILL.md` for capture.
- Verify that scaled UI frames remain legible (`>= 0.55x` desktop scale) and
  their interactive controls respond to pointer and keyboard input.
- Walk `## Generic Tells` against the rendered screen and fix each hit.
- Check text contrast and visible focus on interactive elements.

## Report

State the direction chosen, the compact system (type, spacing, color,
depth), how stage choreography or interactive showcases were verified, which
generic tells were removed, and what was or was not rendered.
