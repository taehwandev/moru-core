---
keyflow_id: sys_common_node_package_module_boundaries
status: review
type: ai-generated
use_when: Deciding package, folder, target, workspace, or api/impl/ui/assertions module splits, auditing flat root packages, or moving files across boundaries on any stack.
skip_when: Editing behavior inside one existing file or settled single-role package with no new file, folder, export, or dependency edge.
---

# Package And Module Boundaries

Apply this shared gate before adding or moving packages, folders, targets, or
workspace modules. Platform structure cards refine it with toolchain syntax.

## Boundary Promotion Ladder

Walk the ladder and stop at the smallest boundary a named caller needs:

```text
file-private -> flow/role package -> unsplit module/target -> api + impl
-> api + impl + ui -> core/<capability> -> public package
```

- Every new package, target, or module needs a named caller/consumer, allowed
  imports, a concrete forbidden import, and a focused check before code moves
  (see `common/skills/code-structure-ownership/references/structure-stops.md`).
- Keep a feature unsplit when one host owns it and no peer module, extension,
  widget, worker, or test helper must compile against its contract alone.

## Feature `api` / `impl` / Optional `ui` / `assertions` Contract

- `api` (`*Contract`) owns the complete caller and navigation surface:
  destination identity (`*Route`), arguments, deep-link/result/event shapes,
  the navigate/launch helper, and ports. A caller that only navigates or
  dispatches must compile against `api` alone.
- Keep `Route` unambiguous: `*Route` names destination data in `api`, never a
  stateful UI holder (`*Screen` / `*Container`) or stateless view
  (`*Content` / `*View`).
- `impl` owns execution: stateful holder, state owner, UDF models, stateless
  renderer, mappers, destination-to-content binding, and platform/host entry
  adapters. Only the composition root imports `impl` to wire the graph.
- `ui` is an optional extraction created **only** when a named consumer outside
  `impl` reuses the same concrete surface without pulling platform/host entry
  code: move the stateless renderer (`*Content`), visual display models, and
  callbacks/slots when the consumer supplies state (Widget, App Clip, preview
  gallery), or move the holder + state owner + stateless renderer over stable
  ports when a second host needs the working feature without `impl`'s platform
  entry (keeping `*Content` stateless). Previews, internal folders, and the
  feature's own wrapper are not outside consumers. `impl` delegates to `ui`;
  `ui` never imports `impl`.
- `assertions` (`*TestSupport`) owns role-sized fixtures, recording fakes,
  builders, and assertion subjects compiling against `api` alone, never `impl`.
- Start data coarse (one capability-partitioned contract + impl pair before
  splitting modules). Name `core/<capability>` modules by concrete capability,
  never `common`, `shared`, `utils`, `helpers`, `base`, or `feedback`.

## Root-Package Audit And Complete Role Moves

- Keep a module or target root limited to its public entry surface once ~20+
  files or three or more roles accumulate (rendering, unrelated state owners,
  mappers, data sources/DTOs, parsers, platform adapters, localized copy).
- Split large features **by flow first, then role** (`<flow>/`, `<flow>/ui/`);
  keep `UiState`/`Action`/`Effect` beside their state owner instead of creating
  empty `state/` or `contract/` folders.
- Split data and domain **by capability first, then role** (`account/`,
  `billing/` -> `repository/`, `local/`, `remote/`, `mapper/`), never into
  repo-wide horizontal `models/`, `services/`, or `repositories/` dumps.
- Complete every role move: adding `ui/`, `mapper/`, or `remote/` requires
  moving all existing root files of that role in the same slice so the root is
  never half-migrated. Collapse one-file folders that add no import rule.

## Do Not

- Do not hide `api -> impl`, `ui -> impl`, `core -> feature`, or cross-feature
  `featureA -> featureB/internal` edges behind DI bindings, catch-all barrels
  (`index.ts`, `__init__.py`), or private-path imports (`lib/src/`, `_internal`).
- Do not widen `private`/`fileprivate` helpers during a file or package split
  without searching the destination scope for colliding declarations first.
- Do not call a split complete when the host/app target net-grew or retained
  the moved screen/service behind glue without an inline owner and removal rule.

## Verification

- Compile a navigating or contract-only caller against `api`/`*Contract` alone,
  plus each changed implementation target and at least one real consumer.
- Run manifest and source import searches (`rg`) for `api -> impl`, `ui -> impl`,
  `core -> feature`, cross-feature internal imports, and unused declared edges;
  never claim clean edges without search output.
- Audit touched package/folder file and role counts to confirm no half-applied
  role split or new grab-bag root remains.
- Report chosen shape, justifying caller, edges added/removed, integration
  owner, and (for moves) host files deleted vs added plus remaining bridges.
