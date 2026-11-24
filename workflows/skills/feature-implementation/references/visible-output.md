---
keyflow_id: sys_feature_visible_output
status: review
type: ai-generated
---

# Changing Visible Output

Use when the work changes something people look at and judge (a page, scene,
3D or WebGL world, game, animation, video or design), across one round or
many.

- Write a keep list before editing: what the user liked or must not change.
  Carry it forward every round; a round that breaks a keep item has regressed,
  whatever it added.
- Capture the baseline before changing it: the same views or times you will
  judge afterwards, from the current version. Commit or tag that version when
  the project allows, or save the captures outside the tree; an uncommitted
  project has no baseline to return to.
- Use a named reference only as a quality bar; copy nothing from it.
- When the user says it looks wrong, unnatural, busy or cheap, remove or
  replace before adding, and say what was removed. More features is not more
  quality.
- Judge the candidate next to the baseline at the same views. Feature
  presence, zero console errors, passing tests or "verified X exists" do not
  show that it looks better, and neither does self-assessment such as
  "achieved the exact look". Report what is still weak.
- Canvas, 3D and timeline evidence follows
  `common/skills/ui-visual-verification/SKILL.md`
  (`## Canvas, WebGL And Timeline Output`,
  `## Comparison Oracle And Evidence Budget`).
- Produce expensive finals (video, full renders, deploys) only when asked.
- When other agents share the work, also apply
  `workflows/skills/multi-agent-collaboration/references/current-guidance.md`
  `## Quality Across Rounds`.
