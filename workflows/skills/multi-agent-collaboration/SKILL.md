---
keyflow_id: sys_workflows_multi_agent_collaboration_md_skill
status: stable
type: ai-generated
---

# Multi-Agent Collaboration

Use when routed to `workflows/skills/multi-agent-collaboration/SKILL.md` or when work needs this Moru Core guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Delegation Rule

When a route requires this skill, consume its `parallel_execution` policy. If
the runtime exposes workers and two or more meaningful slices meet the detailed
scope, contract, integration, and verification rules, delegate automatically;
explicit user multi-agent wording is not required. Otherwise record the
concrete serial reason. Map the execution primitive to the active runtime:
Codex native workers, Claude Agent/Task workers, or the available
Gemini/Antigravity/AGY agent runner.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
