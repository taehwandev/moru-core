---
keyflow_id: sys_850baab06765
status: stable
type: ai-generated
---

# Repo Agent Routing Template

Add this to repo-local agent instructions for Codex, Claude,
Gemini/Antigravity/AGY, or another coding agent runtime. Prefer `AGENTS.md` as
the canonical file when the runtime reads it. If `CLAUDE.md`, `CODEX.md`,
`.agents/README.md`, or Antigravity CLI docs already exist, update their pointer
in the same pass or point them back to `AGENTS.md`; do not create duplicate
runtime-specific files only for this block.

```text
Shared Moru Core library:
<MORU_ROOT>/AGENTS.md
<MORU_ROOT>/index.md
<MORU_ROOT>/scripts/agent-entry.py
<MORU_ROOT>/scripts/project-discover.py
<MORU_LAUNCHER>

Use repo-local instructions first. If this block is being installed into a
personal or global runtime instructions file, and the runtime starts outside the
target repo or the request does not name one clear repo, run
`agent-entry.py` or `project-discover.py` first. Ask for a target if it remains
ambiguous or unidentified. An explicitly named path for a new project may be
created and edited when discovery says `not_found`; no existing repo or
instruction file exists to select yet. Read its instructions once present and
apply its Git/worktree policy after initialization. If `agent-entry.py`
returns `selected`, prefer
starting or relaunching the runtime with that selected repo as the primary
workspace. For Codex, use `codex -C <TARGET_REPO>`; add
`--add-dir <MORU_ROOT>` only when the task needs the shared
Moru Core root in the session workspace. Repo instruction files define
behavior; runtime launch options define filesystem scope. Before work in a
target project, explicitly read its instruction file when present for this
runtime: Codex-style agents read `AGENTS.md`, Claude reads `CLAUDE.md` when
present, Codex-specific setups read `CODEX.md` when present,
Gemini/Antigravity/AGY reads `AGENTS.md`, and generic agents read their
configured project instruction document or `.agents/README.md` when used.
If the request names a product/workspace alias that may map to multiple repos,
use the local `~/.moru/projects.json` workspace group when available.
Do not guess a single repo from the alias alone. If work starts in one primary
repo and investigation shows a secondary repo must be written, stop before that
write and record a workspace scope checkpoint: starting primary, secondary or
source-of-truth repo, selected mode (`primary-led secondary read`,
`primary-led secondary write`, or `multi-session`), write scope, session model,
and cross-repo verification. When finish-check evidence is used and a secondary
repo was written, pass it as `workspace scope checkpoint=<evidence>`,
`scope expansion checkpoint=<evidence>`, or
`cross-repo scope checkpoint=<evidence>`.
Use the workflow router for narrow selection. Do not read `index.md` after
successful routing; it is a fallback catalog, not another startup requirement.
Do not create repo-local skill documents merely to copy shared Moru Core
behavior. Keep repo-local skills, workflows, wiki pages, or runbooks only when
they contain product-specific facts, commands, domain policy, or verification
that cannot be shared safely.
VibeGuard is required before documentation, code, config, dependency, data,
deployment, or credential changes. In a tracked lifecycle the start and review
hooks run it with <MORU_ROOT> as the rule source and report `VibeGuard overall`;
read that line instead of repeating the audit, and run the package command
yourself only when a hook reports `Skipped`, when no tracked lifecycle is in
use, or as `--strict` before push or publish.
The VibeGuard site is a human reference and does not need to
be fetched by the agent. Do not run VibeGuard `setup` or `update` blindly. If
this repo already has custom agent instructions,
`.vibeguard.json`, `VIBEGUARD.md`, or a managed VibeGuard block, ask a short
application drill first: add pointer vs merge vs pin; audit-only vs refresh
with update vs first-time setup; apply now vs prepare instructions only.
Default to preserving current guardrails and running audit only unless the user
chooses to refresh the managed block.
Read-only lookup, explanation, status, and checks of a supplied diagnosis use
bounded direct evidence without start, fingerprint, mailbox, checkpoint, gate,
review, or finish calls. Applicable project instructions and source contracts
still apply. Checking a diagnosis is not a diff review merely because the user
says "verify". Explicit change/PR reviews and release acceptance retain their
review workflow. A no-edit review delegated by another runtime's lead stays read-only; that lead owns its review workflow. Enter the writable lifecycle before any authorized edit.
The lifecycle and gate requirements below apply only to tracked work, not these
read-only answers. When updating an installed routing block, replace its older
blanket multi-step requirements and check local adapters for contradictions;
preserve product-specific contracts, safety rules and metering integration.
For tracked multi-step tasks, run `<MORU_LAUNCHER> start` once with `--request
"<USER_REQUEST>"`; it runs workflow routing/preflight and reports the required
hooks for the route. Do not separately repeat workflow list, classify, route, or
preflight. Use the start output as the command manifest before selecting task
documents, editing, reviewing, committing, or reporting completion. If the
current user message is a direct question, answer it before routing or editing.
Do not wait for the user to name document keywords. Let routing/search infer
the work surface from the request, platform, concern, and touched files; use
`workflow-doc-surfaces.json` and the local document graph as inputs; read the
route's `required_docs` before editing or reviewing; and treat graph neighbors as
`reference_docs` unless the route promotes them to `required_docs`. If
routing/search misses a clearly relevant platform, concern, or document
surface, stop and report the gap instead of proceeding from memory. Reading the
selected `required_docs` is a direct agent responsibility; do not add a second
document-confirmation step.
After the start hook and required-doc reading, consume
`parallel_execution.delegation_policy`. When the runtime exposes workers and
the multi-agent collaboration skill identifies at least two meaningful slices
with disjoint scopes, a stable contract, an integration owner, and focused
verification, delegate automatically without waiting for explicit user
multi-agent wording. Use Codex native workers, Claude Agent/Task workers, or
the Gemini/AGY Antigravity agent runner according to the active runtime.
Otherwise record the concrete serial reason. At each parent-to-worker boundary,
run `<MORU_LAUNCHER> handoff`; it refreshes the provider-neutral, content-free
execution capsule and validates it once. A ready and valid handoff lets the
worker reuse the parent's route, preflight, and required-doc manifest and skip
duplicate startup. An invalid handoff is a successful fallback decision that
requires the worker's normal lifecycle; never reuse mismatched capsule state.
A no-edit review delegated by another runtime's lead is not such a worker: it
needs no handoff or fallback lifecycle and writes no project state.
The parent is the sole gate-ledger owner. Workers use worker-specific evidence
paths, return scoped evidence, and never overwrite the parent ledger, including
after an invalid handoff fallback. For a Codex leaf, use `dispatch --execute`
only when isolation is explicitly required. A matching parent profile or
unavailable parent profile information both stay in the current process or use
a native worker; neither condition starts a fresh Codex process.
If the direct question asks how to start app, product, or feature work, answer
with the PRD -> ARD -> implementation path before lower-level coding steps. If
the work then proceeds into code, use the `product` route unless an existing
PRD/ARD or repo-local instruction makes the slice clearly trivial.
Documentation enforcement for the active tracked route is owned centrally by
the shared Moru Core finish-check across all runtimes; this pointer does not
add a documentation gate or approval round to read-only answers.
Do not duplicate or restate these rules in repo-local files; keep only this
pointer. The source of truth and the exception process are
`<MORU_ROOT>/workflows/skills/documentation-update/SKILL.md`; add
exceptions there rather than self-judging. Load that card when the active route
requires it or an unresolved documentation decision needs its contract.
If the workflow router or start hook cannot run, stop and report the blocker
before continuing. Keep its gate execution ledger current; each required gate
must have evidence before completion. Show a short gate signal after each
completed or failed gate or task step. Completion requires every required gate
to be 🐱🟢 SUCCESS. Use only two cat signal badges in human-visible reports:
🐱🟢 SUCCESS means executed with evidence, and 🐱🔴 FAIL means blocked, failed,
missed, or missing evidence and triggers missed-gate recovery: stop
finalization, preserve the first failed checkpoint, roll back only dependent
agent-made changes when safe, and run the retrospective workflow. Improve and
verify the owning Moru Core doc, hook, validator, or test before resuming
that checkpoint. One repair cycle is allowed; stop on the same failure or an
unsafe or ambiguous repair. Do not report any third gate state.
When the wrapper scripts are available, keep the existing start evidence,
run `<MORU_LAUNCHER> review` after the scoped diff is ready, and run
`<MORU_LAUNCHER> finish` before final report, commit, release, or handoff. Pass
evidence for every route gate to the finish check. The wrappers write local
evidence under
`.moru/`; this directory is runtime evidence and should usually be
gitignored. When executing wrapper commands from an agent runtime, resolve
`<MORU_ROOT>` to an absolute path first; do not leave `$HOME`,
`${HOME}`, `~`, or a relative path in the executable command. Missing wrapper
evidence or missing route gate evidence is
non-compliant even when the final files look correct. VibeGuard `Needs review`
must be reported explicitly and can pass the finish check only with an
`--allow-vibeguard-review` reason. `--request-classified` must include
`--classification-evidence` and is honored only for a delegated worker backed by
a ready and valid parent execution capsule; every other caller passes
`--request "<USER_REQUEST>"` and lets the classifier run. Work routes require
resolved-scope evidence such
as `clear-scoped`, `answered ... separate actionable`, or `blockers resolved`,
not weak markers such as `classified`, `done`, `clarified`, or `no blockers`.
If a request asks for Grill-Me or classification returns `grill_me: true`,
missing Grill-Me protocol or `/grilling` session evidence is 🐱🔴 FAIL and
requires missed-gate recovery.
Do not load every shared document by default.
Replace `<MORU_ROOT>` with a portable root reference. In committed
repo-local instructions, use `${MORU_HOME}` for shared local installs
or a repo-relative pinned path such as `.agents/moru-core`; do not commit a
personal absolute path such as `/Users/.../moru-core`. Full local paths
belong only in shell environment setup, one-shot prompts, or uncommitted
user-level runtime bridges. Use legacy `${KEYFLOW_AGENT_ROOT}` only when the
environment already provides it.
Keep repo paths, commands, components, role matrices, and domain terms in this repo.
```

For one-shot runtime prompting without editing repo instructions, use
`templates/use-moru-prompt.md`.

Core direct routes:

```text
Document index: <MORU_ROOT>/index.md
Agent operating skill: <MORU_ROOT>/common/skills/agent-operating-skill/SKILL.md
Task intake/effort routing: <MORU_ROOT>/common/skills/task-intake-effort-routing/SKILL.md
Stack discovery: <MORU_ROOT>/common/skills/stack-discovery/SKILL.md
LLM discipline: <MORU_ROOT>/common/skills/llm-coding-discipline/SKILL.md
Code conventions: <MORU_ROOT>/common/skills/code-conventions/SKILL.md
Code structure/ownership: <MORU_ROOT>/common/skills/code-structure-ownership/SKILL.md
Reusable code design: <MORU_ROOT>/common/skills/reusable-code-design/SKILL.md
Component API design: <MORU_ROOT>/common/skills/component-api-design/SKILL.md
State modeling: <MORU_ROOT>/common/skills/state-modeling/SKILL.md
Error modeling: <MORU_ROOT>/common/skills/error-modeling/SKILL.md
Tool failure recovery: <MORU_ROOT>/common/skills/tool-failure-recovery/SKILL.md
Agent interaction: <MORU_ROOT>/common/skills/agent-interaction/SKILL.md
LLM wiki documentation: <MORU_ROOT>/common/skills/llm-wiki-documentation/SKILL.md
Editing safety: <MORU_ROOT>/common/skills/agent-editing-safety/SKILL.md
Worktree hygiene: <MORU_ROOT>/common/skills/worktree-hygiene/SKILL.md
Defensive boundaries: <MORU_ROOT>/common/skills/defensive-boundaries/SKILL.md
UI visual verification: <MORU_ROOT>/common/skills/ui-visual-verification/SKILL.md
Workflow and lifecycle wrapper: <MORU_LAUNCHER>
  (aliases: workflow, start, handoff, gate, review, finish, agent-entry,
  project-discover, agent-preflight, agent-finish-check, agent-os-status,
  agent-os-watchdog, agent-os-maintenance, workflow-dispatch)
Android architecture: <MORU_ROOT>/platforms/android/skills/android-architecture/SKILL.md
Android Compose UI: <MORU_ROOT>/platforms/android/skills/android-compose-ui/SKILL.md
Android module/package structure: <MORU_ROOT>/platforms/android/skills/android-module-structure/SKILL.md
Android ViewModel/state: <MORU_ROOT>/platforms/android/skills/android-viewmodel-state/SKILL.md
Android state/data: <MORU_ROOT>/platforms/android/skills/android-state-data/SKILL.md
Android DataStore persistence: <MORU_ROOT>/platforms/android/references/android-datastore.md
Android background work: <MORU_ROOT>/platforms/android/skills/android-background-work/SKILL.md
Android security: <MORU_ROOT>/platforms/android/skills/android-security/SKILL.md
Android review: <MORU_ROOT>/platforms/android/skills/android-review/SKILL.md
KMP architecture: <MORU_ROOT>/platforms/kmp/skills/kmp-architecture/SKILL.md
KMP module/source-set structure: <MORU_ROOT>/platforms/kmp/skills/kmp-module-structure/SKILL.md
KMP Compose UI: <MORU_ROOT>/platforms/kmp/skills/kmp-compose-ui/SKILL.md
Flutter architecture: <MORU_ROOT>/platforms/flutter/skills/flutter-architecture/SKILL.md
Flutter project/package structure: <MORU_ROOT>/platforms/flutter/skills/flutter-project-structure/SKILL.md
Flutter widget UI: <MORU_ROOT>/platforms/flutter/skills/flutter-widget-ui/SKILL.md
iOS target/package structure: <MORU_ROOT>/platforms/ios/skills/ios-module-structure/SKILL.md
iOS SwiftUI UI: <MORU_ROOT>/platforms/ios/skills/ios-swiftui-ui/SKILL.md
iOS UIKit UI: <MORU_ROOT>/platforms/ios/skills/ios-uikit-ui/SKILL.md
Web React UI: <MORU_ROOT>/platforms/web/skills/web-react-ui/SKILL.md
Server API implementation: <MORU_ROOT>/platforms/server/skills/server-api-implementation/SKILL.md
Application command/UI: <MORU_ROOT>/platforms/application/skills/application-command-ui/SKILL.md
Auth/RBAC implementation: <MORU_ROOT>/product-patterns/skills/auth-rbac-implementation/SKILL.md
Invitation implementation: <MORU_ROOT>/product-patterns/skills/invitation-implementation/SKILL.md
Billing/entitlements implementation: <MORU_ROOT>/product-patterns/skills/billing-entitlements-implementation/SKILL.md
Agent task lifecycle: <MORU_ROOT>/workflows/skills/agent-task-lifecycle/SKILL.md
Request triage workflow: <MORU_ROOT>/workflows/skills/request-triage/SKILL.md
Agent handoff/continuation: <MORU_ROOT>/workflows/skills/agent-handoff-continuation/SKILL.md
Scripted agent workflow: <MORU_ROOT>/workflows/skills/scripted-agent-workflow/SKILL.md
Ambiguity gate: <MORU_ROOT>/workflows/skills/ambiguity-gate/SKILL.md
Product architecture delivery: <MORU_ROOT>/workflows/skills/product-architecture-delivery/SKILL.md
Development cycle: <MORU_ROOT>/workflows/skills/development-cycle/SKILL.md
Multi-agent collaboration: <MORU_ROOT>/workflows/skills/multi-agent-collaboration/SKILL.md
Multi-perspective review: <MORU_ROOT>/workflows/skills/multi-perspective-review/SKILL.md
Retrospective learning: <MORU_ROOT>/workflows/skills/retrospective-learning/SKILL.md
Planning/research workflow: <MORU_ROOT>/workflows/skills/planning-research/SKILL.md
Documentation workflow: <MORU_ROOT>/workflows/skills/documentation-update/SKILL.md
Feature workflow: <MORU_ROOT>/workflows/skills/feature-implementation/SKILL.md
Bugfix/debugging workflow: <MORU_ROOT>/workflows/skills/bugfix-debugging/SKILL.md
Refactor workflow: <MORU_ROOT>/workflows/skills/refactor-cleanup/SKILL.md
Release readiness workflow: <MORU_ROOT>/workflows/skills/release-readiness/SKILL.md
Review/commit workflow: <MORU_ROOT>/workflows/skills/review-and-commit/SKILL.md
```

The direct routes above are optional candidates, not a startup reading queue.
Use the workflow router for selection instead of copying the full shared library
into repo-local instructions.
