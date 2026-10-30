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
- Preserve freedom of engine, visual style, file layout and implementation.
  Separate responsibilities when it improves the work, not to achieve a file
  count. Do not add a mandatory framework, debug API, demo subject or repair turn.

## Scene And Interaction Decisions

- Frame the subject using its bounds and the usable canvas area after controls
  and safe areas. The subject must remain inspectable in that visible area at
  the requested start, intermediate and final states, including the narrow
  aspect ratio. Use intentional close-ups when the experience calls for them;
  do not mistake accidental clipping or a missing subject for cinematic framing. Plan a clear
  focal subject and background depth; effects must support that reading.
- Give each camera mode one active owner. Coordinate manual orbit, tracking and
  transitions; a moving target needs a coherent camera offset and look target.
  Reset restores a useful framing, not only a preset label. Check clipping,
  material contrast and subject visibility through the entire interaction.
- Derive UI, geometry and motion from the same selected state. Keep related
  parts attached under transforms; do not accidentally scale, detach or hide
  them when changing scene modes. Use elapsed time for animation rather than a
  fixed amount per frame, and handle interrupted transitions deliberately.
- Place option controls where the subject remains inspectable. Labels, values,
  selection/focus/disabled feedback and hit targets must survive long options,
  touch, keyboard and narrow screens. Use a deliberate scroll/reflow layout;
  squashing cards or clipping options to keep everything on one screen fails.
  Reserve panel space before choosing camera framing. When scrolling is needed,
  make more options discoverable; do not hide the main action behind the panel.
- Keep rendering/input separate from domain transitions when that boundary is
  useful. Import library symbols in each module that uses them; bundling does
  not prove a click handler has its dependencies. Own listener, control, GPU
  resource and animation-loop cleanup; do not dispose shared resources in use.

## Verify The User Experience Before Delivery

Use the project's available browser tooling and report unavailable checks.
Report the actual viewport, actions and captured states. Without browser or
visual observation, mark those properties unverified rather than inferring a
polished result from source code. Do not require a separately billed model.

1. Run the initial user path from a fresh load. Operate every promised option
   and required action through public controls; capture console errors and
   visible results. A click receipt, counter or successful build is insufficient.
2. Observe start, intermediate and final motion states. Keep the subject visible
   and parts coherent. Inspect orbit/zoom/reset as well as mode transitions.
3. Inspect the option panel itself on desktop and a narrow touch viewport:
   selected-state clarity, actual option effect, label wrapping, padding,
   alignment, truncation, overlays, focus and reachable controls. Separately
   inspect composition, lighting and animation quality; successful logic cannot
   substitute for a polished visible result.
The routed UI quality companion is
`common/skills/ui-visual-verification/SKILL.md`; read its core before styling
controls and use its padding/overlap checks before delivery. A quiet/minimal
aesthetic is not a default for expressive 3D work. Read engine documentation for the
installed version when an API decision is unresolved. Useful primary sources:
[Three.js documentation](https://threejs.org/docs/),
[Three.js manual](https://threejs.org/manual/),
[OrbitControls](https://threejs.org/docs/pages/OrbitControls.html).
