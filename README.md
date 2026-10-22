---
keyflow_id: sys_e2d59ab64adc
status: stable
type: ai-generated
---

# Moru Core

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

Moru Core is a shared set of working rules and completion checks for AI coding
agents. Connect it once, and Claude Code, Codex, Antigravity, and other agents
follow the same standards across all of your repositories—reading only the
guidance a task needs, reusing passed tests when code has not changed, and
verifying their work before calling it done. Your project's own instructions
stay short and always have the final say.

- Repository: <https://github.com/taehwandev/moru-core>
- Website: <https://getmoru.com/core> · [Why Moru Core & 5-Month Report](https://getmoru.com/report)
- Releases: <https://github.com/taehwandev/moru-core/releases> · release notes in [`.github/release-notes/`](.github/release-notes/)

## What It Does

- **Works in the tools you already use.** The same rules work across Claude
  Code, Codex, and Antigravity/AGY through a short connection block.
- **Reads only what the task needs.** Instead of dumping 20 rule files into
  every prompt, the agent opens only the few documents relevant to the current
  task.
- **Verifies before “Done.”** A local launcher records which tests, code
  reviews, and safety checks actually ran—turning “I checked it” from a claim
  into a verified record.
- **Keeps project rules in the project.** Build commands, paths, product policy,
  and secrets stay in your repository, never here.
- **Built-in safety checks.** [VibeGuard](https://vibeguard.thdev.app/) (Moru
  Guard) runs before edits and before completion using Moru Core as its rule
  source.

Runtime names: launcher `moru-hook` in `~/.moru/bin`, `MORU_*` settings,
`<MORU_ROOT>`/`<MORU_LAUNCHER>` placeholders in committed docs, `.moru` local
state, and the `moru_explorer`/`moru_worker`/`moru_reviewer` agent roles.

## Why Moru Core (How It Compares & 5-Month Real-World Results)

![Moru Core 5-Month Real-World Results & Tool Comparison](docs/assets/moru-core-telemetry.svg)

When you work with coding agents every day, three problems show up fast:
1. **Stuffing every rule into `CLAUDE.md` or `AGENTS.md` burns tokens on every turn**—even when you just ask a simple question.
2. **Agents repeat the same tests and mistakes across sessions** because they do not keep a record of which files were already tested or why a bug happened last week.
3. **Agents say “Done” while a test is still broken** or after writing a 900-line file that nobody wants to review.

Moru Core solves those three problems right inside your existing CLI:

| What you care about | **Moru Core (Rules Inside Your CLI)** | Stock Coding CLI (Plain Claude Code / Codex) | Long Rulebooks & Skill Packs (Giant `CLAUDE.md` / `Superpowers`) | Separate Agent App (e.g., Hermes Agent) |
| --- | --- | --- | --- | --- |
| **Do I have to switch tools?** | **✓ Keep Claude Code, Codex, or AGY** just as you use them today | ✓ Keep your current CLI | △ Keep your CLI, plus a giant rule file or startup prompt pack | △ Switch to a separate agent runtime and terminal setup |
| **How needed rules are found** | **✓ Wikimap (`0` LLM tokens, sub-second section index)** picks the exact `4.15` docs the task needs before the model even guesses (**-79.7%** vs `20.45` docs) | △ Only the repo's main instruction file; figures out the rest by trial and error | ✕ A 20-file rulebook pays the full token cost every turn (skill packs load on demand) | △ Carries the full skill list (`~3K` tok) every session + spends extra LLM turns to open skills or summarize raw chat logs |
| **Asking a simple question** *(“Why is this API slow?”)* | **✓ Answers right away**: skips branch creation and workflow steps, reads the code, and leaves your files untouched | △ Safe if you switch to read-only/plan mode yourself | ✕ Still loads commit and release rules just to answer a question | △ Runs a full agent session with its startup memory attached |
| **How it learns without rotting** | **✓ Verified fixes + expiring notes**: shared rules require passing tests (`repair-verify`) before syncing across all 26 repos, and project notes carry an expiry date (`--review-on`, max 3 recalled; **-79.5%** steps in 3 weeks) | ✕ Only if you edit `CLAUDE.md` by hand | ✕ Static markdown files never learn from mistakes or expire | △ Model rewrites its own skills (`skill_manage`) without test verification or expiry dates—one bad workaround stays in the prompt forever |
| **Following up & committing** | **✓ Reuses passed tests** when the relevant code files haven't changed (**-54.4%** fewer steps; **-85.6%** fewer tokens on commit) | ✕ Forgets what was already tested in the last run | ✕ Re-runs the whole checklist from the prompt | ✕ Searches old chat text, but doesn't check if code files changed |
| **When is a task allowed to be “Done”?** | **✓ Checks the result first**: blocks completion until tests pass, new code files stay under `300` lines, and safety checks pass | ✕ Whenever the model says it's done (unless you build custom scripts) | △ Checklist in the prompt—easy for the model to skip in long chats | △ Great sandboxes and chat bots, but the model still decides when it's done |

### What Changed Over 5 Months of Daily Work (26 Repositories · 4,984 Git Commits · 419,857 Agent Steps)

We tracked every task across `26` repositories from May to October 2026 (`419,857`
recorded Spill events, `1,207` Codex threads, and `584` Moru runs). These numbers
come from real daily development on our own projects, comparing the same models
before and after Moru Core's improvements:

- **-79.7% fewer rule files read per task** (`20.45` files in July when we loaded everything up front → `4.15` files in October by reading only what the task needs).
- **-60.7% fewer agent steps per Git commit** (`150.7` steps/commit in July → `59.2` in October) while **shipping +44.0% more commits per active repository each day** (`2.68` → `3.86` commits/day/repo; `29.5` → `65.6` total commits/day).
- **-78.1% lower token usage per changed file** (`432.5K` → `94.6K` weighted tokens per file; per-commit token usage dropped **-46.9%** from `3.07M` in July to `1.63M` in October even with larger multi-file refactors).
- **-93.8% smaller Codex sessions (median)** (`20.28M` → `1.25M` tokens per thread; the heaviest 10% of threads dropped from `146.1M` → `17.9M`).
- **On the exact same model (`claude-opus-5-5`, Sep → Oct 2026)**:
  - Median steps per task dropped **-94.0%** (**`591.0 → 35.5` steps**), median token usage per task dropped **-98.8%** (**`33.47M → 0.41M`**), and average context size per step shrank **-38.4%** (**`488.3K → 301.0K`**).
  - On `gpt-6-sol` (Sep → Oct), median steps per task dropped **-79.6%** (**`855.0 → 174.5` steps**).
  - When following up on work in October, continuing an existing task took **-54.4% fewer steps** than starting fresh (**`45.0 → 20.5` steps**), and committing already-checked work used **-85.6% fewer tokens** (**`2.02M → 0.29M`**).

### Why Moru Core Gets Faster the More You Use It

Static rule files never learn from yesterday's bugs. On the other hand, letting an agent rewrite its own skills without review or expiration dates quickly fills your context with outdated advice. Moru Core gets faster week after week without accumulating junk:

1. **Short project notes with an expiration date (at most 3 per task)**: When an agent tracks down a tricky root cause or project quirk that isn't obvious from the code, it saves a one-line note (`project-memory`) with clear conditions (`--applies-when` / `--not-when`) and a required review date (`--review-on`). Next time a task starts on that project, it recalls at most **3 relevant, unexpired notes**—so the agent skips the dead ends without bloating your prompt.
2. **Fix a recurring mistake once, and every project gets it (`repair-verify`)**: When the same kind of mistake or blocked step happens repeatedly across your work (`337` patterns spotted → `10` accepted → `6` promoted into shared rules), fixing and verifying the shared rule once immediately protects all **26 connected repositories** on their very next run.
3. **Real-world result: brand-new tasks got 79.5% shorter in 3 weeks**: Looking only at **brand-new (`fresh`) tasks** on the exact same model (`claude-opus-5-5`) across October 2026, the median number of steps per task dropped from **`112.0` steps in Week 1 → `48.5` steps in Week 2 (-56.7%) → `23.0` steps in Week 3 (-79.5%)** as project notes and shared fixes built up.

You can check your own monthly and weekly efficiency trends anytime (no prompts or file paths are ever exported):

```bash
python3 scripts/agent-os-status.py --efficiency-trends --all-projects --month 2026-10
```

Read the full comparison and 5-month breakdown at <https://getmoru.com/report>.

> **⚡ Powered by [Wikimap](https://github.com/dhha22/wikimap) — Zero-LLM Knowledge Index for Markdown**
> How does Moru Core pick the exact 4 rules out of hundreds in milliseconds without burning a single LLM token? Under the hood, Moru Core uses **[Wikimap](https://github.com/dhha22/wikimap)**:
> - **0 LLM tokens & sub-second incremental indexing**: Single Python stdlib file with no external vector DB or model calls; re-parses only SHA-changed files in milliseconds.
> - **CJK-safe ranked section search & Reciprocal Rank Fusion (RRF)**: Matches exact headings, tags, aliases, and sections across Korean, Japanese, Chinese, and English without loading whole files.
> - **Link graph & SHA-pinned freshness**: Tracks `outlinks`, `backlinks`, and `REQ-ID` references across documents, and automatically expires notes when source files change.
> 👉 **[Explore Wikimap on GitHub (`dhha22/wikimap`) ↗](https://github.com/dhha22/wikimap)**

## Quick Start

Reuse an existing checkout when one is on your machine or pinned in the repo. Do
not clone a second copy unless the user approves it after being told which root
was found.

**1. Download Moru Core once.** For a personal shared install:

```bash
git clone https://github.com/taehwandev/moru-core.git ~/.moru/core
```

If your team wants to pin a specific reviewed version inside a repository, add
it as a submodule after the repo owner approves:

```bash
git submodule add https://github.com/taehwandev/moru-core.git .agents/moru-core
```

**2. Set up the launcher and agent connections.**

```bash
python3 ~/.moru/core/scripts/setup-agent-hooks.py
```

This installs `~/.moru/bin/moru-hook` (shown as `<MORU_LAUNCHER>`), the
`~/.moru/moru-root` pointer, and the short connection blocks for Codex, Claude,
and AGY. You can check or repair the setup anytime with
`<MORU_LAUNCHER> setup-agent-hooks --check` and
`<MORU_LAUNCHER> setup-agent-hooks`.

**3. Check that everything is ready.**

```bash
<MORU_LAUNCHER> workflow validate
<MORU_LAUNCHER> doctor --project <TARGET_REPO>   # read-only health check
```

**Updating:** Pull updates between tasks (never in the middle of one) so rules
stay consistent during a run:

```bash
cd ~/.moru/core && git pull --ff-only && <MORU_LAUNCHER> workflow validate
```

Connected repositories automatically use the updated rules without needing
commits of their own. Release notes live in
[`.github/release-notes/`](.github/release-notes/).

## Connect A Project

1. Read the project's existing `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, or
   `.agents/` instructions first.
2. Add the short routing block from
   [`templates/repo-agents-routing.md`](templates/repo-agents-routing.md) to the
   file your agent reads (preferring `AGENTS.md`).
3. Keep committed paths portable: use `<MORU_ROOT>`, `${MORU_HOME}`, or a
   relative submodule path like `.agents/moru-core`—never your personal home
   directory path.
4. Run VibeGuard with Moru Core as the rule source:

   ```bash
   npx --yes @taehwandev/vibeguard@latest audit . --rules <MORU_ROOT>
   ```

More details on multi-repo workspaces and setup:
[agent bootstrap](docs/skills/agent-bootstrap/SKILL.md) and
[runtime setup](docs/skills/agent-runtime-integration/references/runtime-setup.md).

## Apply With Any AI Agent

Want your agent to set this up for you? Paste this into your coding agent inside
the project:

```text
Apply Moru Core to this project: https://github.com/taehwandev/moru-core
Reuse an existing local copy if there is one; ask before downloading another.
Read this repo's instructions and VibeGuard files first and ask before
replacing them. Use the Moru Core root as the VibeGuard rule source. Add the
short routing block to AGENTS.md and keep repo-specific rules in this repo.
```

Full template: [`templates/apply-moru-request.md`](templates/apply-moru-request.md).
For a one-time session without editing project files, use
[`templates/use-moru-prompt.md`](templates/use-moru-prompt.md).

## How A Task Runs

Questions that only read code are answered right away without starting a workflow.
When a task changes files, the agent runs it through the launcher:

```bash
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> \
  --command <route> --request "<USER_REQUEST>" \
  --intent <safe_slug> --target-summary "<bounded target>"
```

1. **Start** picks the right workflow path (`small-change`, `bugfix`, `feature`,
   `docs`, etc.) and checks permissions. Pass `--approved-effect git_write` only
   when the user asked to commit or push.
2. **Read** the few `required_docs` selected for that workflow; open extra
   reference docs only if a question comes up.
3. **Work and record** test results with `<MORU_LAUNCHER> gate-batch`. Run
   `<MORU_LAUNCHER> next` anytime to see the next step and exact command.
4. **Review** checks the diff, file sizes, links, and VibeGuard safety rules.
5. **Finish** confirms all required checks passed before reporting done or
   committing.

Check status is always `🐱🟢 SUCCESS` or `🐱🔴 FAIL`. To pick up an interrupted
task or do a follow-up, run `start --continue-from <run id>`. Mechanics and
recovery rules:
[scripted agent workflow](workflows/skills/scripted-agent-workflow/references/current-guidance.md)
and [executable evidence gate](docs/skills/agent-runtime-integration/references/executable-evidence-gate.md).

## Memory And Work Cards

When an agent confirms a non-obvious cause, pitfall, or design reason, it saves
a short note with `<MORU_LAUNCHER> project-memory`. Future tasks on the same
project recall up to three relevant, unexpired notes. Work cards keep unfinished
tasks visible across sessions. Both stay on your Mac. Details:
[project memory and work cards](docs/project-memory.md).

## Supported Coding Agents

- **Codex** and **Antigravity/AGY** read `AGENTS.md` directly (AGY also gets a
  `GEMINI.md` pointer).
- **Claude Code** reads `CLAUDE.md`, which imports `AGENTS.md`.
- Setup adds a short connection block to each tool's user settings and installs
  the `moru_*` helper roles.
- If [Spill](https://getmoru.com/spill) is installed on your Mac, setup connects
  task labels automatically without installing extra token hooks.

Details: [agent runtime integration](docs/skills/agent-runtime-integration/SKILL.md).

## Repository Layout

```text
AGENTS.md         Main entrypoint read by coding agents
index.md          Document catalog
common/           General engineering rules
platforms/        Android, KMP, Flutter, iOS, Swift, React Native, web, server, Python, and app guides
product-patterns/ Reusable patterns for auth, invites, billing, and credentials
workflows/        Step-by-step workflows by task type
scripts/          Launcher, hooks, routers, and validators
templates/        Copy-paste setup blocks and prompts
docs/             Reference guides and runtime setup docs
```

Start most coding work from
[`common/skills/agent-operating-skill/SKILL.md`](common/skills/agent-operating-skill/SKILL.md).

## Contributing

- Shared rules are written in clear, concise English. Translated guides (such as
  [README.ko.md](README.ko.md), [README.ja.md](README.ja.md), and
  [README.zh-CN.md](README.zh-CN.md)) are for human readers; English files
  remain the source of truth for agents.
- Link to existing rules instead of copying them.
- Only add rules that apply across projects—keep project-specific names, paths,
  and policies in their own repositories.
- Every rule document includes frontmatter (`keyflow_id`, `status`, `type`) per
  [doc conventions](common/skills/doc-conventions/SKILL.md).

## Local Hook Testing

Run the end-to-end smoke checks in a temporary sandbox:

```bash
python3 scripts/run_smoke_checks.py
```

Unit tests: `PYTHONPATH=tests:scripts python3 -B -m unittest discover -s tests`.

## Moru Maintenance Audit

Health and efficiency checks for Moru Core itself live in
[docs/maintenance-audit.md](docs/maintenance-audit.md).

## Website Deployment

The public page is <https://getmoru.com/core>, deployed on Vercel as part of the
Moru website. Public releases are tagged for meaningful updates using weekly
CalVer `vYY.WW.N` on the Korean calendar (Asia/Seoul, Monday-start weeks); see
[web deployment versioning](common/skills/web-deployment-versioning/SKILL.md)
and [release versioning](common/skills/release-versioning/SKILL.md).
