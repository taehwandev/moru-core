---
keyflow_id: doc_tao_agent_os_rename_migration
status: review
type: human-reviewed-needed
---

# Historical rename record: AgentPlaybook to Tao Agent OS

> Archive. The identifiers and shell commands below describe an earlier
> migration. They are retained as historical evidence and must not be used
> as Moru Core installation or state-migration instructions. Follow
> [the current Moru Core migration plan](moru-rename.md) instead.

Record of the rebrand to Tao Agent OS.

This file lives in the repository on purpose. A Claude session's memory directory
is derived from the project path, so renaming the folder makes the old session
memory unreachable. Anything a later session needs has to travel with the repo.

## Naming

| Use | Value |
|---|---|
| Display name | `Tao Agent OS` |
| Repository | `taehwandev/tao-agent-os` |
| Local folder | `~/git/tao-agent-os` |
| State directory | `~/.tao/` |
| Launcher | `~/.tao/bin/tao-hook` |
| Root pointer | `~/.tao/tao-root` |
| Environment | `TAO_ROOT`, `TAO_HOME`, `TAO_LAUNCHER`, `TAO_STATE_HOME`, and the rest of the `TAO_*` set |
| Placeholders | `<TAO_ROOT>`, `<TAO_LAUNCHER>` |
| Bridge marker | `<!-- tao-runtime-bridge:start -->` |
| Site | `tao.thdev.app` |

`道` means the way, the path. The project preserves a way of working across
agents, so the name states what it does. Display long, run short: prose says
"Tao Agent OS", commands say `tao`.

## What was done

Three commits on `fix/cross-project-gate`:

1. **Folder rename** — the checkout moved to `~/git/tao-agent-os`, followed by a
   setup rerun for this repo and the eleven other projects that reference it.
2. **Display name** — 627 prose occurrences across 247 files, plus 23 GitHub URLs
   that still pointed at the pre-rename repository slug and only resolved through
   GitHub's redirect.
3. **Identifiers** — every remaining token: the legacy environment-variable set
   became `TAO_*` across 23 distinct variables, the state directory became
   `.tao`, the launcher became `tao-hook`, the root pointer became `tao-root`,
   the bridge marker became `tao-runtime-bridge`, the permission identifier
   became `TaoAgentOSPython`, the launcher's fallback discovery roots were
   repointed, and five files and directories were renamed.

The 592-test suite passed unchanged at every step.

## Counting note

The original plan estimated 723 display-name occurrences. Measurement found 648
in prose and 568 more inside path strings. A repo-wide substitution would have
corrupted every path, so the work was split by directory under an explicit
exclusion contract that held paths, environment tokens, and lowercase
identifiers constant until they were renamed deliberately in their own step.

Worth keeping in mind for any future rename: count the token in each syntactic
role separately before estimating the work.

## Host-side migration

Tracked repository content no longer carries the old name, with one deliberate
exception: this section. A migration guide has to name what is being migrated
from, so the commands below spell out the old paths literally. Treat every
occurrence of the retired name in this file as data, not as branding, and
exclude this file when auditing for remnants.

Two things outside tracked content may still retain it: ignored local runtime
evidence written before the rename, and machines that installed an earlier
version. To migrate those installations:

```bash
# 1. Close every agent session first. A running session holds the launcher path
#    it read at startup and cannot pick up the new one until it restarts.

# 2. Move the state directory and rename the launcher and root pointer.
mv ~/.agentplaybook ~/.tao
mv ~/.tao/bin/agentplaybook-hook ~/.tao/bin/tao-hook
mv ~/.tao/agentplaybook-root ~/.tao/tao-root

# 3. Regenerate every runtime bridge, hook, and permission entry.
python3 ~/git/tao-agent-os/scripts/setup-agent-hooks.py --skip-graphify \
  --target ~/git/tao-agent-os
for d in ~/git/*/; do
  python3 ~/git/tao-agent-os/scripts/setup-agent-hooks.py --skip-graphify --target "$d"
done

# 4. Move each project's local state directory. Use `git mv` where the directory
#    is tracked, because a plain `mv` leaves that repository dirty and the rename
#    then needs its own commit there.
for d in ~/git/*/.agentplaybook; do
  [ -e "$d" ] || continue
  repo="$(dirname "$d")"
  if git -C "$repo" ls-files --error-unmatch "$d" >/dev/null 2>&1; then
    git -C "$repo" mv .agentplaybook .tao
  else
    mv "$d" "$repo/.tao"
  fi
done
```

Step 4 crosses repository boundaries. Each project whose `.agentplaybook` was
tracked needs its own commit before the rename is real there; the loop stages the
move but deliberately does not commit on your behalf.

Verify:

```bash
cat ~/.tao/tao-root                                  # must print ~/git/tao-agent-os
cd ~/git/tao-agent-os && python3 -m unittest discover -s tests   # all pass
python3 ~/git/tao-agent-os/scripts/setup-agent-hooks.py --check   # all runtimes report OK

# Remnant check across the active runtime stores. Must return nothing.
grep -rl "agentplaybook\|AGENTPLAYBOOK" ~/.claude/settings.json ~/.claude/CLAUDE.md \
  ~/.codex/rules ~/.codex/config.toml ~/.gemini/config/config.json \
  ~/.gemini/antigravity-cli/settings.json 2>/dev/null
```

`setup-agent-hooks.py --check` confirms the managed Tao entries are present; it
does not look for legacy ones. The two checks answer different questions, so run
both.

The active runtime permission stores are part of the zero-remnant check. The
Codex and AGY stores were cleaned only after their canonical Tao entries were
verified, then the runtime-scoped installers were rerun to restore the complete
managed entry set without restoring the legacy values.

A transitional symlink at the old state-directory path pointing to `~/.tao` keeps
an already-running session alive across the move. It has to be deleted once those
sessions restart, or the old name survives in the one place that still resolves.

## Still open

- Domain `tao.thdev.app`: DNS now resolves, and `docs/CNAME` on this branch has
  been updated to the new host. What is still outstanding is publication —
  `origin/main` continues to carry the old host in `docs/CNAME`, so GitHub Pages
  serves the old domain until this branch merges. Check the real state with
  `cat docs/CNAME` against `git show origin/main:docs/CNAME`.
- Active runtime permission stores were cleaned on 2026-07-19. Codex rules,
  Codex project and hook state, both AGY permission stores, the AGY trusted
  workspace list, and the current Claude settings all returned zero legacy
  matches. Runtime-scoped setup checks passed afterward. Historical backups and
  session records remain a separate archival cleanup decision; they are not
  active configuration.
- Sibling repositories: seven projects under `~/git` still track a
  `.agentplaybook/` directory — 13 paths each, all of it the Graphify skill
  install rather than Tao state. Step 4 above stages the rename, but each repo
  needs its own commit, so this is seven deliberate changes and not a sweep.
- Generated Graphify output carries the old name in prose because it was built
  before the rename — `graphify-out/` in this repo and in `KeyFlow`. It is
  ignored, derived content; a graph refresh clears it. Nothing reads it as
  configuration, so it is stale cache rather than a remnant.
- Ignored runtime evidence under `.tao/` includes filenames like
  `preflight-agentplaybook-rename-audit.json`. Those encode the *task slug* a
  session was given, not the product name, and they are immutable run records.
  Leave them.
- Blog series (5 files under `~/Documents/KeyFlowVault/writing`) refers to the
  project by the old name. The published parts are a historical record; decide
  per file whether to update or leave.
- `CLAUDE_CODE_SESSION_ID` is occasionally absent at a turn boundary, which makes
  `start` write an unstamped preflight and the edit gate deny until `start`
  reruns. Fails closed, cause unreproduced.

## Observed gap

`setup-agent-hooks.py` reports `ok` for a permission target when the expected
entries are present, without checking whether the absolute paths inside them
still resolve. During this rename that was harmless, because the entries point at
the stable launcher rather than at the repository. A future move that does change
those paths would still report `ok` while leaving them stale.
