---
name: agent-skill-card-anatomy
description: "Agent Skill Card Anatomy: Use when creating, updating, or reviewing a Moru Core common card, workflow, platform card, product-pattern card, or agent-facing template."
keyflow_id: sys_common_agent_skill_card_anatomy_md_skill
status: stable
type: ai-generated
metadata:
  internal: true
---

# Agent Skill Card Anatomy

Use when creating, updating, splitting, or reviewing Moru Core common
cards, workflow cards, platform cards, product-pattern cards, or agent-facing
templates.

## Read

- `references/current-guidance.md` for strict card sections, rationalizations,
  red flags, stop conditions, and bundle layout rules.
- `docs/skills/moru-skill-bundle-migration/SKILL.md` before
  broad structure or router changes.

## Process

1. Confirm the card has a clear trigger and exclusion.
2. Keep `SKILL.md` small: entry criteria, read routing, decision/process, stop
   signals, verification, and report shape.
3. Move long examples, deep checklists, and source coverage into focused
   `references/` files.
4. Preserve or add verification evidence for any route or policy the card
   controls.

## Do Not

- Do not add a new card when an existing source of truth should be tightened.
- Do not copy vendor or repo-local policy wholesale into shared guidance.
- Do not let a compatibility stub become the real guidance source.

## Verification

- For document-only changes, run workflow validation and diff hygiene checks.
- When a route should load the card, add or update route/test evidence that the
  route returns the `SKILL.md` entrypoint.
