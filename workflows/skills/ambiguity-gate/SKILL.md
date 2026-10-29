---
name: ambiguity-gate
description: "Ambiguity Gate: Use before PRD, ARD, task breakdown, implementation plan, or code work when the request has unknowns that could change behavior, scope, risk, or verification."
keyflow_id: sys_workflows_ambiguity_gate_md_skill
status: stable
type: ai-generated
---

# Ambiguity Gate

Load `references/current-guidance.md` only when the task needs blocker
discovery, an alignment brief or a Grill-Me session.

## Evidence Contract

Prefer the structured fields and values that `start` prints for `ambiguity
check` and `alignment brief`; existing finish-valid prose stays compatible.
Record `ambiguity check` success only when no blocker remains; an `alignment
brief` must be user-visible before edits, not a private or later note. Judge
blockers from epistemic state after bounded inspection, never prompt keywords:
settled requests (including coupled in-scope consistency fixes) proceed
directly, whereas open UX flows, unsettled prose thesis/voice, or unapproved
sibling-page expansions require pre-edit alignment per `AGENTS.md`. These
records do not replace the direct-answer-first rule or a required Grill-Me
session.
