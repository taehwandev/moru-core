---
keyflow_id: sys_common_node_ui_state_render_boundary
status: review
type: ai-generated
use_when: Creating, changing or reviewing UI that connects application state or side effects to rendering, on any UI framework.
skip_when: No UI changes, or a pure display component or cosmetic edit introduces no state or effect ownership.
---

# Stateful Owner And Stateless Rendering

Generate a working state/render boundary, not only a state model or a folder
named `ui`. This contract applies to Compose, React, Flutter, SwiftUI, UIKit
and other UI frameworks using their existing lifecycle and state idioms.

## Inspect First

Read neighbouring screens and their entry points to find the repository's
stateful/stateless naming, state owner and lifecycle convention. Preserve those
conventions; no new state library, DI layer or framework is implied.

## Generation Contract

- A screen that obtains application state, subscribes to external data or runs
  product side effects needs two concrete rendering entry points: a stateful
  owner/adapter and a stateless view/content function, component or view type.
  They may share a file when repository rules allow it.
- The owner obtains the existing ViewModel, store, controller or feature hook,
  subscribes with the framework's lifecycle, handles one-off effects and maps
  user callbacks to actions. It calls the stateless renderer with values.
- The renderer accepts immutable display state, callbacks and optional slots.
  It can render with deterministic fixtures without DI, a router, database,
  network or platform service. Local focus, scroll, animation and uncommitted
  interaction state may remain local; stateless here means independent of
  application state owners and product side effects.
- Sections and leaves take only their display slice and intent callbacks.
  The whole-screen renderer may take the whole screen's display state.
- Connect the actual navigation, page or host entry to the owner, and the
  owner to the renderer. An unused pure component beside a monolithic live
  screen does not satisfy the split.
- Pure display UI and local-only interaction need no artificial owner,
  ViewModel, reducer or effect stream. For existing UI, repair the boundary
  when the requested work changes its state/effect ownership; a spacing or
  color edit does not authorize a screen-wide migration.

## Do Not

- Do not pass a ViewModel, store, query result, repository, navigation controller
  or service locator into the renderer, including through a default argument,
  context lookup or hidden global.
- Do not move fetching, persistence or product commands into the renderer's
  lifecycle callback, effect or coroutine to make the owner appear thin.
- Do not claim the split from file names, comments, an interface, or a preview
  wrapper while the running screen still mixes state acquisition and layout.

## Verification

- Trace and report concrete symbols for `entry -> owner -> renderer` and
  `renderer callback -> owner action`; inspect both declarations and callers.
- Render the real stateless entry with fixture values and exercise an affected
  callback without application services, using the repo's preview, story or UI
  test. Test owner transitions/effects when their behavior changed.
- Review dependency leaks and lifecycle cleanup; compile/typecheck the changed
  target. If a runtime check cannot run, name the missing evidence rather than
  treating source inspection as proof of generated behavior.
