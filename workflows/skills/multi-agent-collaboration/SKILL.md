---
name: multi-agent-collaboration
description: "Multi-Agent Collaboration: Use when work is split across subagents, multiple agents, delegated roles, parallel tasks, or a builder/verifier pair."
keyflow_id: sys_workflows_multi_agent_collaboration_md_skill
status: stable
type: ai-generated
---

# Multi-Agent Collaboration

Use when routed to `workflows/skills/multi-agent-collaboration/SKILL.md` or when work needs this Moru Core guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- `references/on-demand-orchestration.md` for role selection, execution choice,
  access failures, and closeout evidence.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Delegation Rule

When a route requires this skill, consume its `parallel_execution` policy. Keep
roles in the same session by default. Delegate on demand for a concrete benefit
that exceeds coordination cost, with available tools and existing access.
Independent slices alone do not require delegation. Otherwise record the
concrete serial reason. Map the selected execution primitive to the active runtime:
Codex native workers, Claude Agent/Task workers, or the available
Gemini/Antigravity/AGY agent runner.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
