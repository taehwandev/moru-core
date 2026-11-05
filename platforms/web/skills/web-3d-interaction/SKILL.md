---
name: web-3d-interaction
description: "Create or change browser 3D scenes, viewers and configurators (Three.js, WebGL, R3F, Babylon), including camera, motion and option UI; excludes CSS-only transforms and native modeling."
keyflow_id: sys_web_3d_interaction
status: review
type: ai-generated
---

# Interactive Web 3D

Use before designing or changing an interactive browser 3D experience. Select
this skill for actual scene/model interaction work, not ordinary CSS transforms,
static illustrations, native/Blender modeling or a mention of 3D in prose.

## Make The First Result Worth Using

- Keep the user's chosen experience and creative ambition. Choose an intentional
  silhouette, material/light contrast, composition and motion language. Check
  that the focal subject is readable before the first interaction. Match fidelity to the
  request; do not replace an engaging scene with a checklist demo.
- Plan the meaningful user actions and visible consequences before construction.
  Connect options to an observable geometry, material, pose or behavior change;
  make the selected value, available actions and disabled reasons understandable.
- Treat the first working version as a draft. Look at the running page, list what
  still reads as a placeholder (flat unlit primitives, a bare background, no
  secondary motion, effects without falloff, a subject without parts or detail),
  and spend effort there before adding more tests or procedure. Visible craft
  is part of done, not an optional extra.
- Preserve freedom of engine, visual style, file layout and implementation.
  Separate responsibilities when it improves the work, not to achieve a file
  count. Do not add a mandatory framework, debug API, demo subject or repair turn.

## Scene And Interaction Decisions

- Frame the subject using its bounds and the usable canvas area after controls
  and safe areas. The subject must remain inspectable in that visible area at
  the requested start, intermediate and final states, including the narrow
  aspect ratio. Use intentional close-ups when the experience calls for them;
  do not mistake accidental clipping or a missing subject for cinematic framing. The
  default view is what people judge first: the subject reads at a useful size
  there, with its parts visible, not as a speck inside an overview. Offer a wider
  overview as a named camera mode. Plan a clear focal subject and background
  depth; effects must support that reading.
- Effects that show energy or contact (thrust, glow, dust, sparks, trails) need a
  deliberate look: soft round or emissive sprites or meshes with colour and
  falloff that suit the subject. A default square point sprite or an untextured
  placeholder shape is a defect, not a style. Effects follow the subject's state
  and fade out with it.
- Give each camera mode one active owner. Coordinate manual orbit, tracking and
  transitions; a moving target needs a coherent camera offset and look target.
  Reset restores a useful framing, not only a preset label. Check clipping,
  material contrast and subject visibility through the entire interaction.
- Derive UI, geometry and motion from the same selected state. Keep related
  parts attached under transforms; do not accidentally scale, detach or hide
  them when changing scene modes. Use elapsed time for animation rather than a
  fixed amount per frame, and handle interrupted transitions deliberately.
- A moving model faces its direction of travel and rests in its pre-action state
  (engine, effects and sound off until the action starts). Effects sit opposite
  the force or motion they show (thrust opposite the acceleration, a trail behind
  the path) and follow state changes. Axis and facing conventions that differ by
  engine API: `references/engine-pitfalls.md`.
- Place option controls where the subject remains inspectable. Labels, values,
  states and hit targets must survive long options, touch, keyboard and narrow
  screens; use a deliberate scroll/reflow layout, reserve panel space before
  choosing camera framing, and never hide the main action behind the panel.
- Silent defects that code review and builds miss, so check them in the running
  page: a moving-vertex `Points`/instanced object is culled unless its bounds
  are refreshed or culling is off; a model's lowest point must meet the surface
  it rests on; overlays pass pointer and wheel input to the scene except over
  real controls; global key handlers skip focused controls; pause freezes
  effects and sound too; teardown releases loops, listeners and GPU/audio
  resources.
- Keep rendering/input separate from domain transitions when that boundary is
  useful. Import library symbols in each module that uses them; bundling does
  not prove a click handler has its dependencies. Own listener, control, GPU
  resource and animation-loop cleanup; do not dispose shared resources in use.

## Verify The User Experience Before Delivery

Use the project's available browser tooling and report the viewport, actions
and captured states. Without browser or visual observation, mark those
properties unverified rather than inferring polish from source code.

1. Run the initial user path from a fresh load. Operate every promised option
   and required action through public controls; capture console errors and
   visible results. A click receipt, counter or successful build is insufficient.
2. Observe start, intermediate and final motion states. Keep the subject visible
   and parts coherent. Inspect orbit/zoom/reset as well as mode transitions.
   Interrupt each automatic sequence once with reset, pause, follow off and on,
   and manual orbit/zoom; the camera must then track or release as the control
   shows, and the follow state and its UI must agree. At an end state (arrived,
   finished) the subject stays framed at a readable size, motion and status text
   agree, and a place the subject travels to gets closer instead of being
   positioned relative to the moving subject.
3. Inspect the option panel itself on desktop and a narrow touch viewport:
   selected-state clarity, actual option effect, label wrapping, padding,
   alignment, truncation, overlays, focus and reachable controls. Separately
   inspect composition, lighting and animation quality; successful logic cannot
   substitute for a polished visible result.
4. Verify motion and state numerically and also look at the running page:
   numbers do not show framing, effects or a wrong value on screen. Assert what
   the user reads where the UI binds a number (formatted text, unit, plausible
   range), `forward · velocity > 0` at several points of every moving phase, and
   no active flight effects at rest; run each module's update path once so a
   missing import fails. Reversed, mirrored or sideways motion is a defect.
5. Run the structure check in `platforms/web/skills/web-code-structure/references/current-guidance.md`
   (New Browser Builds Without A Framework) on the finished code, and split what it
   flags before reporting done.
6. Get a second opinion before reporting a build or a multi-phase change done:
   ask an independent read-only reviewer (another model, a fresh subagent or a
   fresh session that did not write the code) to read the finished project and
   report, with file:line evidence, the defects a user would hit, each stated
   requirement as implemented, partly or missing, and what it did not check.
   Name the requirements and ask for the user-visible defects first (camera
   follow after reset, pause or phase change; a displayed value that changes
   unit, scale or reference between phases; an end state that disagrees with its
   status text). Fix the findings you can reproduce or that the code plainly
   shows, rerun the affected check, and report the rest as open. Start the
   reviewer before claiming it is unavailable: a subagent, or a separate CLI
   run in read-only mode (for example `codex exec --sandbox read-only` or
   `claude -p` with edit tools denied). Only a failed attempt counts; report
   the command tried and its error. The author's own review does not replace
   this step.

The routed UI quality companion is `common/skills/ui-visual-verification/SKILL.md`;
read its core before styling controls and use its padding/overlap checks before
delivery. A quiet/minimal aesthetic is not a default for expressive 3D work. For
an unresolved API decision read the installed version's documentation:
[Three.js docs](https://threejs.org/docs/), [manual](https://threejs.org/manual/).
