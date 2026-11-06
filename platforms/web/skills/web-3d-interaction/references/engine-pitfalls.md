---
keyflow_id: sys_web_3d_engine_pitfalls
status: review
type: ai-generated
---

# Three.js Engine Pitfalls

Open only for an unresolved engine behavior. These are cases where code runs
without errors but the picture is wrong. Each rule is a Three.js convention or
default, kept only where independent model answers agreed and the behavior is
documented; claims that could not be confirmed were dropped.

- **Facing.** `Object3D.lookAt(target)` points a mesh or group's +Z at the
  target; cameras and lights point -Z. `Matrix4.lookAt(eye, target, up)` builds
  the camera basis (-Z toward the target), so using it for a model whose nose is
  +Z flies it tail-first. Fix the model's forward axis once, in a pivot group,
  and check `forward · velocity > 0` at sampled points of the path.
- **Curve speed.** `getPoint(t)` is not arc-length parameterized, so speed
  varies. Use `getPointAt(u)` and `getTangentAt(u)` for even motion, wrap `t` on
  closed curves, and never look ahead past the end of an open one.
- **Smoothing.** Slerp quaternions, not Euler angles, which turn the long way
  across ±π. Use `1 - Math.exp(-k * dt)` for frame-rate independent easing.
  `Clock.getElapsedTime()` calls `getDelta()`, so using both in one frame
  corrupts the step.
- **Camera ownership.** `OrbitControls.update()` rewrites the camera from its own
  state. While a follow or fixed mode drives the camera, stop updating the
  controls; on handing back, set `controls.target` and the camera position
  together.
- **Update order.** Move targets and call `updateMatrixWorld()` before a follow
  camera reads them, or it lags one frame.
- **Reparenting.** `add()` keeps the local transform and so changes the world
  pose; `attach()` keeps the world pose.
- **Culling.** `Points`, instanced and custom geometry whose vertices move keep a
  stale `boundingSphere` and are culled while visible. Recompute it after
  changes, or set `frustumCulled = false` for such objects.
- **Point sprites.** A `PointsMaterial` without a `map` draws square dots. Give
  particles a radial-gradient canvas or image texture, `sizeAttenuation`, and
  additive blending, and tune size and opacity so the effect reads as soft light
  or smoke.
- **Glow and transparency.** Transparent objects sort per object, not per
  triangle. For glow and particles use `transparent`, `depthWrite = false` and an
  explicit `renderOrder`.
- **Resize.** Apply `setPixelRatio(Math.min(devicePixelRatio, 2))`, `setSize`,
  `camera.aspect` and `updateProjectionMatrix()` as one step. `fov` is vertical,
  so a narrow portrait view loses width; fit the subject's bounds on both axes.
- **Color.** Set `renderer.outputColorSpace`, mark color textures
  `SRGBColorSpace`, and choose tone mapping and exposure once; tune lights after
  that baseline.
- **Near plane.** A large `camera.near` clips geometry in close follow shots.
- **Imports.** Every module imports the symbols it uses. A missing
  `import * as THREE` is a runtime-only `ReferenceError` in a bundle; only
  loading the page and reading the console proves that every module works.
