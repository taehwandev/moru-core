---
name: bugfix-debugging
description: "Bugfix Debugging Workflow: Use when investigating a bug, regression, failing test, flaky behavior, or production-like failure."
keyflow_id: sys_workflows_bugfix_debugging_md_skill
status: stable
type: ai-generated
---

# Bugfix Debugging Workflow

The procedure is `references/current-guidance.md`.

## Review Preparation

- Before the first review, count the task-owned changed paths. If one cohesive
  bugfix legitimately exceeds the default path budget, pass a bounded maximum
  derived from the observed scope; do not discover the limit through a failed
  review or use a broad override for unrelated changes.
