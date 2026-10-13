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
3. **Identifiers.** Launcher (`tao-hook`), state directory (`~/.tao/`), root
   pointer, `TAO_*` environment variables, `<TAO_ROOT>`/`<TAO_LAUNCHER>`
   placeholders, bridge marker, permission identifier, `tao_*` agent roles and
   the `tao:language` site event. Ship compatibility first: the old launcher
   path and environment names keep resolving for a stated window, setup
   writes both, and removal is a separate, announced step. Re-review the
   protected site prompts and update their test hashes in the same change.
4. **Repository, folder and domain.** GitHub repository rename, local folder
   move, `docs/CNAME` and the site URL. Each is an external or cross-project
   action with its own approval; GitHub redirects old repository URLs, but
   Claude session memory is keyed by folder path, so record anything a later
   session needs in this file first.
5. **Moru app.** TaoIDE's own rename (app name, bundle identifier,
   `app.thdev.taoide` namespace) is owned by the TaoIDE repository and was
   handed to that session on 2026-10-13. A bundle identifier change creates a
   new app identity for the operating system and any store listing; decide it
   separately from the display name.

## Before Each Identifier Or External Phase

- Close or restart running agent sessions, as in the precedent's host-side
  migration, and keep a transitional symlink for the old state directory.
- Preserve Spill token-metering hooks, label handoff commands and
  `SPILL_*` environment handoff when runtime bridges are regenerated.
- Rerun runtime setup for this repository and every project that references
  it, then run the remnant check the precedent describes.

## Still Open

- Trademark, domain and existing-product checks for "Moru" have not been run.
  Do them before phase 4 or any public announcement.
- Whether the site moves off `tao.thdev.app` (phase 4).
- Publication: phase 1 is merged locally only; pushing publishes the site.
