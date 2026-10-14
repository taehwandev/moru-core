---
keyflow_id: doc_moru_rename_migration
status: draft
type: human-reviewed-needed
---

# Moru Rename Migration

Plan for renaming the product family. Decided by the owner on 2026-10-13.

| Before | After |
|---|---|
| TaoIDE (macOS app) | Moru |
| Tao Agent OS (rules and checks) | Moru Core |

The repository slug is `moru-core`. Runtime records and the user-local
installation use `.moru`, not `.moru-core`; the shorter directory is shared by
the Moru family. An existing `~/.moru/workspace/` is preserved and is not
itself evidence that Moru Core runtime records have been migrated.

`모루` is a smith's anvil: the surface work is laid on and shaped. The app is
the workbench; Moru Core is the rule set underneath it. Prose says "Moru" and
"Moru Core"; Korean copy says "모루" and "모루 코어".

## Scope Decision

The owner chose to rename internal names too, not only visible text. The
precedent in [tao-agent-os-rename.md](tao-agent-os-rename.md) shows why this is
done in phases: a single substitution corrupts paths, and identifier changes
break every running agent session until it restarts.

Count each token by syntactic role before estimating: prose, URLs, paths,
environment variables, launcher names, permission identifiers and file names
are separate inventories.

## Phases

1. **Site (done in this change).** `docs/` is one combined Moru and Moru Core
   site. The setup prompts embedded in it are protected by
   `tests/test_site_workflow.py` and still name Tao Agent OS, the current
   repository URL and the current launcher, because those are the commands
   that work today. They change only in phase 3, together with their hashes.
2. **Display name in this repository.** Replace "Tao Agent OS" in prose
   (README, AGENTS.md, guidance cards, templates, docs) with "Moru Core",
   directory by directory, keeping paths, URLs and identifiers unchanged.
   Keep one "formerly Tao Agent OS" line in README for discoverability.
   Done on 2026-10-14 across prose, messages and guidance; the site prompts
   changed with phase 3 and their hashes were re-reviewed.
3. **Identifiers.** Launcher (`tao-hook`), state directory (`~/.tao/`), root
   pointer, `TAO_*` environment variables, `<TAO_ROOT>`/`<TAO_LAUNCHER>`
   placeholders, bridge marker, permission identifier, `tao_*` agent roles and
   the `tao:language` site event. Ship compatibility first: the old launcher
   path and environment names keep resolving for a stated window, setup
   writes both, and removal is a separate, announced step. Re-review the
   protected site prompts and update their test hashes in the same change.
   The compatibility commit is on local `main`: both launchers are installed.
   On 2026-10-13, 35 project and worktree state roots and the user-local state
   moved to `.moru`, with relative compatibility links under `.tao`. The
   workspace router at `~/git/.tao` remains separate because `~/git` is not a
   Git project. A `state-ready` marker selects `.moru` only after the records
   have moved; an existing `.moru` directory alone is not sufficient.
   On 2026-10-14 the identifiers themselves moved: `MORU_*` settings (reads
   fall back to `TAO_*`), `<MORU_ROOT>`/`<MORU_LAUNCHER>`, the
   `moru-runtime-bridge` and `MANAGED MORU CORE ROUTING` markers, `moru-hooks`
   Codex rules block, `moru-workspace` profile, `MoruCorePython` setup labels,
   `moru_*` agent roles, `.moru-backup`, the `moru:language` event, the
   `com.taehwandev.moru-core.maintenance` LaunchAgent, tao-named files and
   Python identifiers. New installs and projects without a `.tao` tree start
   on `~/.moru`, `moru-hook` and `.moru` directly. Setup recognises and replaces
   each pre-rename spelling it wrote. On 2026-10-15 the compatibility layer
   was removed: no `tao-hook` launcher or `tao-root` pointer is installed,
   `TAO_*` settings are no longer read, `~/.tao` and project `.tao` trees are
   no longer selected, and runtime code recognises only Moru markers. The old
   spellings live only in `scripts/support/legacy_names.py`, used by setup to
   remove what an older setup wrote and by the two migration tools.
   `migrate_moru_local_state.py` now moves records without leaving links and
   removes the drained `.tao` tree.
4. **Repository, folder and domain.** The GitHub repository is now
   `taehwandev/moru-core`; the local checkout moved to `~/git/moru-core` on
   2026-10-13. The old `~/git/tao-agent-os` path is a compatibility link.
   The `tao.thdev.app` domain has not moved.
   Claude session memory is keyed by folder path; the compatibility link keeps
   prior path-based references available during the transition.
5. **Moru app.** TaoIDE's own rename (app name, bundle identifier,
   `app.thdev.taoide` namespace) is owned by the TaoIDE repository and was
   handed to that session on 2026-10-13. A bundle identifier change creates a
   new app identity for the operating system and any store listing; decide it
   separately from the display name.

## Before Each Identifier Or External Phase

- Close or restart running agent sessions, as in the precedent's host-side
  migration. Move ignored runtime records to `.moru` only after writers are
  quiescent; keep relative links from their old `.tao` paths so older running
  commands and saved worktree paths still resolve. Do not move Git-tracked
  `.tao/skills` guidance as though it were runtime state. Use
  `scripts/migrate_moru_local_state.py` on one verified project root at a time,
  deepest linked worktree first, and migrate the user-local root separately.
  Its default workspace inventory is read-only; `--apply` requires an exact
  `--project` or `--global-state` target. Verify each new `.moru/state-ready`
  marker and compatibility link before switching the next project.
- Preserve Spill token-metering hooks, label handoff commands and
  `SPILL_*` environment handoff when runtime bridges are regenerated.
- Rerun runtime setup for this repository and every project that references
  it, then run the remnant check the precedent describes.

## Still Open

- Trademark, domain and existing-product checks for "Moru" have not been run.
  Do them before phase 4 or any public announcement.
- Whether the site moves off `tao.thdev.app` (phase 4).
- Publication: phase 1 is merged locally only; pushing publishes the site.
