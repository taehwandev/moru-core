---
keyflow_id: sys_e2d59ab64adc
status: stable
type: ai-generated
---

# Moru Core

[English](README.md) · [한국어](README.ko.md)

Moru Core is a shared guidance and runtime layer for AI coding agents. One
checkout gives Claude, Codex, Antigravity and other agents the same operating
rules, workflow routes, review checks, platform guidance and executable
lifecycle evidence across every repository you link to it. Repo-local
instructions stay small and keep the final say.

- Repository: <https://github.com/taehwandev/moru-core>
- Website: <https://getmoru.com/core> · [Efficiency Report](https://getmoru.com/report)
- Releases: <https://github.com/taehwandev/moru-core/releases> · release notes in [`.github/release-notes/`](.github/release-notes/)

## What It Is

- **Provider-neutral.** The same rules work for Claude, Codex, Antigravity/AGY
  and generic agents; runtime files are thin bridges.
- **Selective.** Each task loads only the documents its route requires, not the
  whole library.
- **Executable.** A launcher records routing, gates, review and finish as local
  JSON evidence, so "I checked" becomes a checked fact.
- **Not a product template.** Repo commands, paths, product policy, credentials
  and domain language belong in the target repository, never here.
- **Not a safety scanner.** [VibeGuard](https://vibeguard.thdev.app/) is the
  required safety gate; Moru Core is passed to it as the rule source.

Runtime names: launcher `moru-hook` in `~/.moru/bin`, `MORU_*` settings,
`<MORU_ROOT>`/`<MORU_LAUNCHER>` placeholders in committed docs, `.moru` local
state and the `moru_explorer`/`moru_worker`/`moru_reviewer` agent roles.

## Why Moru Core (Architecture Comparison & Field Telemetry)

Native coding CLIs, on-demand skill packs (such as `Superpowers` or Agent
Skills), and self-evolving agent runtimes (such as Nous Research's Hermes Agent
or OpenHands) each address different layers of the agent stack. Moru Core is not
a replacement runtime or a static prompt pack—it is a **host-native repository
operating contract** that governs what guidance is required for a route, how
shared rules and project memory evolve, and what executable evidence is checked
before work is marked complete.

| Dimension | Native CLI (Stock Claude Code / Codex) | Rulebooks & Skill Packs (Mega `CLAUDE.md` / `Superpowers`) | Self-Evolving Agent Runtime (e.g., Hermes Agent) | **Moru Core (Host-Native Repository Contract)** |
| --- | --- | --- | --- | --- |
| **Who owns the loop** | Host CLI (native permissions, plan/sandbox modes, optional hooks) | Host CLI (eager monolithic rulebook or `SessionStart` bootstrap skill) | Standalone runtime loop (owns orchestration, subagents, terminal backends, gateway) | **Host CLI layer**: keeps your native Claude Code, Codex, or Antigravity session and binds shared repo contracts |
| **Guidance & context loading** | Loads repo instructions only; discovers build/test conventions ad hoc | Monolithic `CLAUDE.md` pays an eager prefix tax every turn; skill packs load bodies on demand via tool calls | Bounded frozen memory snapshot (`~1.3K` tok `MEMORY.md` + `USER.md`), `~3K` skill index, on-demand `skill_view` / FTS5 search | **Deterministic route manifest**: selects exact `required_docs` (`4.15` avg in Oct, **-79.7%** vs our Jul `20.45` baseline); references open only for unresolved decisions |
| **Read-only questions** *(“Why is this slow?”)* | Supports manual plan/read-only modes, not automatically separated from repo workflows | Monolithic files still load review/release rules; skill packs still inject bootstrap instructions | Runs inside the general agent loop with startup snapshot and skill index attached | **Stateless Read-Only Fast Path**: skips Moru `start`/`review`/`finish` lifecycle and worktree setup; active read-only runs block writes |
| **How skills & memory evolve** | Manual edits to `CLAUDE.md` / `AGENTS.md` or local notes | Hand-written static markdown skills; no automated verification or TTL expiry | Agent auto-creates/patches skills via `skill_manage` (`write_approval` off by default, no TTL/expiry) + persistent `MEMORY.md` | **Governed evolution**: canonical rules update only on a verified `reusable_gap` checked by `workflow.py validate`; `project-memory` recalls `≤3` entries with mandatory `--review-on` expiry and `--applies-when`/`--not-when` guards |
| **Follow-up runs & re-verification** | Conversational context only; no structured gate ledger across runs | Prompt checklists; follow-ups repeat checks or rely on conversational recall | FTS5 session search recalls prior chats, but no file-hash gate ledger to carry local checks | **`--continue-from` & `--reuse-inputs`** carry eligible local gates when declared `input_paths` hashes and attested scope/toolchain match (observed **-54.4%** p50 events in Oct continuation vs fresh cohort) |
| **Definition of “Done” & tradeoffs** | Model self-report unless custom repo hooks are hand-built per project | Prompt-enforced checklists (e.g., `verification-before-completion`); model can drift | Provides sandboxes, messaging gateways, cron, and autonomous skills, but completion relies on model judgment | **Executable `finish` gate** checks fresh test evidence, `≤300` added-line dev file budget, and VibeGuard (hook-enforced in Claude Code; CLI-verified elsewhere). *Tradeoff: does not provide sandboxes, chat gateways, cron, or unreviewed skill generation.* |

### Observed May–October 2026 Field Cohorts (Single Operator · 26 Repos · 4,984 Git Commits · 419,857 Spill Events)

The figures below summarize our own May–October 2026 field telemetry (`419,857`
recorded Spill events, `1,207` Codex threads, `584` Moru tracked runs, and `265`
October session-bound runs across `26` repositories). They document how our
workflow cohorts evolved over time—not a randomized controlled benchmark against
external runtimes:

- **-79.7% route `required_docs` per run** (`20.45` docs in our Jul v1 manifest → `4.29` in Sep → `4.15` in Oct via Need-Driven Reading).
- **-60.7% recorded events per Git commit** (`150.7` events/commit in Jul → `59.2` in Oct) and **+122.4% daily commit rate** (`29.5/day` across `11` active repos [`2.68/day/repo`] → `65.6/day` across `17` active repos [`3.86/day/repo`, **+44.0% per active repo**]).
- **-78.1% reference-weighted tokens per changed file** (`432.5K` in Jul → `94.6K` in Oct using Spill's `1.0 / 1.25 / 0.1 / 1.0` comparison index; weighted tokens per commit moved from `3.07M` in Jul → `1.47M` in Sep → `1.63M` in Oct [**-46.9%** vs Jul] alongside larger multi-file refactors averaging `17.2` files/commit in Oct).
- **-93.8% Codex median thread tokens (p50)** (`20.28M` → `1.25M`; p90 tail dropped from `146.1M` → `17.9M`).
- **Within-model observational cohorts (holding model ID constant)**:
  - On `claude-opus-5-5` (Sep → Oct), median recorded events per run dropped from **`591.0 → 35.5` (-94.0%)**, median weighted tokens from **`33.47M → 0.41M` (-98.8%)**, and average context per event from **`488.3K → 301.0K` (-38.4%)**.
  - On `gpt-6-sol` (Sep → Oct), median recorded events per run dropped from **`855.0 → 174.5` (-79.6%)**, with `classify`-stage events per run falling from **`1,215.2 → 6.0` (-99.5%)**.
  - Within October 2026 (`265` session-bound runs, `92.98%` session match coverage), `continuation` runs had lower median events than `fresh` runs on `claude-opus-5-5` (**`45.0 → 20.5` events, -54.4%**) and on the `commit` route (**`52.5 → 13.0` events, -75.2%**; weighted tokens **`2.02M → 0.29M`, -85.6%**).

Inspect your own local cohort and monthly/weekly period efficiency trends (`W1–W4` when `--month` is passed; content-free, no prompts or file paths exported):

```bash
python3 scripts/agent-os-status.py --efficiency-trends --all-projects --month 2026-10
```

Full architectural scenario walkthrough and May–October field ledger: <https://getmoru.com/report>.

## Quick Start

Reuse an existing checkout when one is on the machine or pinned in the repo. Do
not clone a second copy unless the user approves it after being told which root
was found.

**1. Get a root.** A personal shared install:

```bash
git clone https://github.com/taehwandev/moru-core.git ~/.moru/core
```

A team that must pin one reviewed version adds it as a submodule instead, after
the repo owner approves the location and update policy:

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

**2. Install the launcher and runtime bridges.**

```bash
python3 ~/.moru/core/scripts/setup-agent-hooks.py
```

This installs `~/.moru/bin/moru-hook` (referred to as `<MORU_LAUNCHER>`), the
`~/.moru/moru-root` pointer, managed bridge blocks for Codex, Claude and AGY,
hooks, and permissions scoped to the launcher's absolute path. Check or repair
later with `<MORU_LAUNCHER> setup-agent-hooks --check` and
`<MORU_LAUNCHER> setup-agent-hooks`; rerun setup after moving the checkout.

**3. Validate.**

```bash
<MORU_LAUNCHER> workflow validate
<MORU_LAUNCHER> doctor --project <TARGET_REPO>   # read-only health report
```

**Update** between tasks, never during one, so rules do not change mid-run:

```bash
cd ~/.moru/core && git pull --ff-only && <MORU_LAUNCHER> workflow validate
```

Target repos that link to the root need no update of their own. A pinned
submodule moves through the target repo's normal review. Release changes are in
[`.github/release-notes/`](.github/release-notes/).

## Connect A Project

1. Read the target repo's existing `AGENTS.md`, `CLAUDE.md`, `CODEX.md` or
   `.agents/` instructions first.
2. Add the managed routing block from
   [`templates/repo-agents-routing.md`](templates/repo-agents-routing.md) to the
   file the runtime reads, preferring `AGENTS.md`. Update existing
   runtime-specific pointers in the same pass instead of creating duplicates.
3. Keep committed instructions portable: use `<MORU_ROOT>`, `${MORU_HOME}` or a
   repo-relative pinned path such as `.agents/moru-core`, never a personal
   absolute path.
4. Run VibeGuard with the Moru Core root as the rule source. If the repo already
   has guardrails or custom instructions, decide first whether to audit only,
   refresh the managed block, or set up from scratch:

   ```bash
   npx --yes @taehwandev/vibeguard@latest audit . --rules <MORU_ROOT>
   ```

When an agent starts outside the target repo, resolve it first with
`<MORU_LAUNCHER> agent-entry --runtime <runtime> --request "<USER_REQUEST>" --cwd "$PWD"`.
Products spanning several repositories can declare workspace groups in
`~/.moru/projects.json`. Install modes, the application drill and cross-repo
rules: [agent bootstrap](docs/skills/agent-bootstrap/SKILL.md) and
[runtime setup](docs/skills/agent-runtime-integration/references/runtime-setup.md).

## Apply With Any AI Agent

Paste the request in [`templates/apply-moru-request.md`](templates/apply-moru-request.md)
into an agent session in the target repo. Its short form:

```text
Apply Moru Core to this project: https://github.com/taehwandev/moru-core
Reuse an existing local copy if there is one; ask before downloading another.
Read this repo's instructions and VibeGuard files first and ask before
replacing them. Use the Moru Core root as the VibeGuard rule source. Add the
short routing block to AGENTS.md and keep repo-specific rules in this repo.
```

For a one-shot session without changing the repo, use
[`templates/use-moru-prompt.md`](templates/use-moru-prompt.md).

## How A Task Runs

Read-only questions are answered from direct evidence without a lifecycle.
Work that changes something runs once through the launcher:

```bash
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> \
  --command <route> --request "<USER_REQUEST>" \
  --intent <safe_slug> --target-summary "<bounded target>"
```

1. **Start** classifies the request, selects the route and binds its authority.
   Pass `--approved-effect git_write` (or higher) only when the user authorized
   commits, pushes or other Git and external writes.
2. **Read** every `required_docs` entry the route lists; other references are
   opened only for an unresolved question.
3. **Work and record** the route's gates with `<MORU_LAUNCHER> gate-batch`.
   `<MORU_LAUNCHER> next` prints the next step and a copyable command.
4. **Review hook** checks the diff, structure, links, workflow validity and
   VibeGuard.
5. **Finish hook** verifies the evidence before any final report, commit,
   release or handoff.

Gate status is only `🐱🟢 SUCCESS` or `🐱🔴 FAIL`. Direct `workflow route`,
`agent-preflight` and `agent-finish-check` calls are lower-level diagnostics,
never a second lifecycle. Interrupted work resumes with
`start --continue-from <run id>`, which keeps the work identity while scope and
authority are checked again.

Common routes are `small-change` (one owner, at most four files), `bugfix`,
`feature`, `refactor`, `docs`, `review`, `commit`, `cleanup` and `release`;
`<MORU_LAUNCHER> workflow list` prints every route, platform and concern.
Mechanics, schemas and recovery rules:
[scripted agent workflow](workflows/skills/scripted-agent-workflow/references/current-guidance.md)
and [executable evidence gate](docs/skills/agent-runtime-integration/references/executable-evidence-gate.md).

## Memory And Work Cards

Agents capture verified project facts (a root cause, a pitfall, a decision
reason) with `<MORU_LAUNCHER> project-memory`; later starts recall up to three
relevant, in-date records as reference. Work cards keep unfinished tasks visible
across sessions. Both stay on your machine and never grant authority. Details:
[project memory and work cards](docs/project-memory.md).

## Runtimes

- **Codex** and **Antigravity/AGY** read `AGENTS.md` directly; AGY also gets a
  `GEMINI.md` bridge.
- **Claude** reads `CLAUDE.md`, which imports `AGENTS.md`.
- Setup installs short managed bridge blocks in each runtime's user-level
  instructions and the native `moru_*` subagent roles.
- Spill workflow labels are optional: setup wires a label bridge only when the
  local Spill helper exists, and labels are written only after a real start.
  Moru Core installs no token-usage hooks.

Runtime-specific rules: [agent runtime integration](docs/skills/agent-runtime-integration/SKILL.md).

## Repository Layout

```text
AGENTS.md         Shared entrypoint for agent runtimes
index.md          Catalog for selecting the smallest useful document set
common/           Platform-neutral engineering guidance
platforms/        Android, KMP, Flutter, iOS, Swift, React Native, web, server, Python and application tracks
product-patterns/ Reusable product mechanics such as auth, invite, billing and agent credentials
workflows/        Repeatable agent work paths
scripts/          Launcher, hooks, routers, validators
templates/        Repo-local routing block and prompts
docs/             Reference pages, specs and bootstrap/runtime skills
```

Start most coding work from
[`common/skills/agent-operating-skill/SKILL.md`](common/skills/agent-operating-skill/SKILL.md).

## Contributing

- Shared guidance is written in English, short and action-oriented. Localized
  copy (such as [README.ko.md](README.ko.md) or `docs/ko/`) never becomes the
  source of truth.
- Link to an existing card instead of copying it. Platform-neutral lessons go to
  `common/`, product mechanics to `product-patterns/`, repeatable paths to
  `workflows/`.
- A lesson is shared only if it still holds after removing every project,
  service, path and vendor name.
- Documents carry frontmatter (`keyflow_id`, `status`, `type`) as described in
  [doc conventions](common/skills/doc-conventions/SKILL.md).

## Local Hook Testing

Run the lifecycle smoke checks in a temporary repository sandbox:

```bash
python3 scripts/run_smoke_checks.py
```

Unit tests: `PYTHONPATH=tests:scripts python3 -B -m unittest discover -s tests`.

## Moru Maintenance Audit

Health and efficiency audits of Moru Core itself, with their living checks and
recorded findings, are in [docs/maintenance-audit.md](docs/maintenance-audit.md).

## Website Deployment

The public site is <https://getmoru.com/core>, deployed on Vercel as part of
the Moru site; this repository no longer carries a custom-domain `CNAME`. A
public release is cut only for a meaningful change set, not for every merge.
The general contract is
[web deployment versioning](common/skills/web-deployment-versioning/SKILL.md).
Release tags use weekly CalVer `vYY.WW.N` on the Korean calendar (Asia/Seoul,
Monday-start weeks), as defined by
[release versioning](common/skills/release-versioning/SKILL.md).
