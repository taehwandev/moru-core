---
name: doc-conventions
description: "Document Conventions: Output path and naming rules for generated documents (PRD, spec, ARD). An agent must follow these rules when creating documents, unless the target repo's own instructions override them. Repo-local rules always win."
keyflow_id: sys_common_doc_conventions_skill
status: stable
type: human-reviewed
---

# Document Conventions

Use when creating, reviewing, routing, or naming generated project documents such as PRDs, specs, ARDs, feature folders, and module implementation docs.

## Read

- `references/current-guidance.md` for generated document path, naming, and override-order rules.
- Repo-local document instructions before applying these shared defaults.

## Process

1. Check repo-local document paths and naming rules first.
2. Use the feature-folder convention only when repo-local instructions do not define a different location.
3. Keep project-level PRD, spec, and ARD files together unless the document is explicitly module implementation detail.
4. Report the created or changed document path, status (`draft`, `review`, or `stable`), and next step.

## Do Not

- Do not create empty placeholder documents.
- Do not put project-level PRDs inside module implementation folders.
- Do not override repo-local document conventions with this shared default.

## Verification

- Confirm generated document paths match repo-local rules or this fallback.
- Confirm route/index references load this `SKILL.md` entrypoint: `rg -n "common/skills/doc-conventions/SKILL.md|Document Output Conventions|planning_change_documentation" AGENTS.md workflow-doc-surfaces.json index.md`
- For routing changes, run a route smoke and confirm this path appears: `python3 scripts/workflow.py route docs --request "기획 변경 문서 정리" --concern skills`