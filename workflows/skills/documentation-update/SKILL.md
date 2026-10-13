---
keyflow_id: sys_workflows_documentation_update_md_skill
status: stable
type: ai-generated
---

# Documentation Update Workflow

Use when routed to `workflows/skills/documentation-update/SKILL.md` or when work needs this Moru Core guidance area.

## Read

- `references/current-guidance.md` for the detailed guidance for this skill.
- Related `SKILL.md` entrypoints named by the reference before loading their detailed references.

## Process

1. Read this entrypoint first to confirm this guidance area applies.
2. Open `references/current-guidance.md` only when the task actually touches this area.
3. Follow the reference's decision rules, stop conditions, and verification requirements before editing, reviewing, or reporting completion.

## Do Not

- Do not look for legacy flat compatibility paths; load this skill bundle as the canonical context-loading target.
- Do not load broad references for unrelated work just because this skill was nearby in the route.

## Verification

- If route wiring changes, confirm the route loads this `SKILL.md` entrypoint.
- If detailed guidance changes, validate links and frontmatter for `references/current-guidance.md`.
- If this entrypoint is an intentional route required-doc update, record final
  documentation evidence for this exact path after editing and record it again
  if the file changes later. This receipt is available only when the active
  route itself requires the `documentation` gate.
