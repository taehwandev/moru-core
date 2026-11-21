---
keyflow_id: sys_web_3d_effects_character_selection
status: review
type: ai-generated
---

# Web 3D Effects And Character Selection

Use only the matching section. Keep the target project's renderer, asset
loader and state owners. Apply the parent skill's interaction and frame checks.

## Mesh Scan And Reveal

A surface highlight is enough when the user only needs to see scan progress.
If points or edges must trace the model, drive both them and the reveal from
one scan front. Bind the front to the world or the moving model according to
what should hold it in place. Verify attachment by moving the camera or the
model during the scan. [Adapted from Meng To's point-cloud scan](https://github.com/MengTo/Skills/blob/main/agent-skills/game-development/build-point-cloud-scan/SKILL.md)

## Lens Raindrops And Wet Glass

Use an overlay for decorative drops. When the scene must bend through the
drops, reuse the host's scene-color buffer and composite before drawing
controls. Compare dry and wet captures of the same high-contrast edge to
check that bending stays local and controls stay sharp. [Adapted from Meng To's lens raindrops](https://github.com/MengTo/Skills/blob/main/agent-skills/game-development/build-lens-raindrops/SKILL.md)

## Character Selection

Keep the current model visible while the next loads. Use the existing loader's
cancellation or check the request identity before updating the preview. Verify
the latest choice wins when an older load finishes late. Where confirmation is
part of the flow, verify the ready preview and the confirmed ID agree. [Adapted from Meng To's 3D character selector](https://github.com/MengTo/Skills/blob/main/agent-skills/game-development/build-3d-character-selector/SKILL.md)
