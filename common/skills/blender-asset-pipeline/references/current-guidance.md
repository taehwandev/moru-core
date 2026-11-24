---
keyflow_id: sys_blender_asset_pipeline
status: review
type: ai-generated
---

# Blender Asset Pipeline

Rules for agents that author 3D assets in Blender and hand them to code. The
asset is only done when it looks right in the consuming renderer, not in
Blender.

## Source Of Truth

- A Blender Python script is the source of the asset; the exported `.glb` is a
  build output committed next to it so the app runs without Blender. Keep one
  script per asset under the repo's tools path and make it rebuild the file
  from an empty scene, deterministically.
- Run Blender headless by its resolved absolute path:
  `<BLENDER> -b --factory-startup --python <script> -- <args>`. Check
  `<BLENDER> -v` once instead of assuming a version; Python API names change
  between major versions.
- In a sandbox, point `BLENDER_USER_RESOURCES` (and any cache or temp path) at
  a folder inside the worktree.
- Do not hand-edit binary `.blend`/`.glb` files or treat a saved `.blend` as
  the only source.

## Contract With The Consuming Code

Write the contract before modelling, from the code that consumes the asset,
and record it in the asset's notes file:

- units (metres), axes (glTF is +Y up; export with Y-up conversion and verify
  the forward axis the code expects), origin and pivot points;
- the exact object, mesh-part and material names the code binds to: material
  names drive paint or shader overrides, part names drive instanced buckets,
  named empties carry anchors (seats, lights, wheel and rotor pivots, effect
  ports);
- dimensions copied from the shape being replaced, with a tolerance, checked
  by the script itself (print the bounding box and fail when it is outside);
- a triangle budget per asset and per on-screen instance count, LODs for far
  or instanced copies, and a texture-size cap;
- deformation needs: enough mesh density or shape keys for any crush, bend or
  damage state the code applies.

Keep a match to the replaced shape when the user asked for a better-made
version of the same thing: silhouette, proportions, livery and motion stay;
detail and finish improve.

## Inspecting Assets

- Never open `.glb`, `.blend`, `.png`, `.jpg` or other binary files with a
  text or file-read tool. Some runtimes reject the turn with an "empty,
  corrupted, or malformed media" error and stop the run.
- Inspect them through Blender (`-b --python` printing names, counts and
  bounds), a glTF inspection CLI already installed in the project, or a short
  script that reads the GLB JSON chunk. View renders as images only through a
  tool that accepts images.

## Wiring Into The App

- Load assets through the project's existing asset loader and keep the
  previous code-built or placeholder shape as the fallback when a file fails
  to load; exercise that fallback once.
- Fit the asset to the existing rig (groups, pivots, anchors, shadows,
  instancing, damage states) rather than bending the rig to the asset. If the
  asset does not fit, fix the script and re-export.
- Keep asset authoring and wiring as separate steps with separate owners when
  several agents work in parallel: authoring owners get disjoint asset paths;
  one integrator wires every asset and owns the seams.

## Verification

- Judge in the target renderer: capture the real page, app or game at the
  shots and distances where the asset appears, next to the previous version
  and any reference frames. Turntable renders in Blender are supporting
  evidence only.
- Check scale, ground contact, clipping, popping between LODs, material
  binding, lights and emissives, and every animated state the asset takes
  part in.
- Report the frame time or draw cost before and after on the same capture,
  and keep it inside the project's budget.
- Use only assets the user may ship: original models, or downloads under a
  licence the user approved. No real brands, badges or recognisable
  trademarked shapes unless the user owns them.

## Stop Conditions

Stop and report instead of shipping when the asset cannot meet the contract
(names, axes, dimensions, budget), when the only way to fit is to change the
consuming code's behaviour, or when a needed download or paid tool is not yet
approved.
