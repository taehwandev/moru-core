---
name: scripted-agent-workflow
description: "Scripted Agent Workflow: Use when an agent task should be resolved by an executable workflow route instead of only by reading prose."
keyflow_id: sys_workflows_scripted_agent_workflow_md_skill
status: stable
type: ai-generated
metadata:
  internal: true
---

# Scripted Agent Workflow

Use when routed to `workflows/skills/scripted-agent-workflow/SKILL.md` or when work needs this Moru Core guidance area.

## Read

- `references/current-guidance.md` for the route and gate contract this skill runs.
- `references/evidence-wrappers.md` for the wrapper commands and what each writes.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area,
   and `references/evidence-wrappers.md` when it changes a wrapper entrypoint.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for
  `references/current-guidance.md` and `references/evidence-wrappers.md`.
