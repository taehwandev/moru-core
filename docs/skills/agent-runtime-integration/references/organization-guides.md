---
keyflow_id: sys_agent_runtime_organization_guides
status: draft
type: ai-generated
---

# Organization Guides

Use this when a company or team wants shared rules applied across several
target repositories.

When several repositories of one company or team share rules (design system,
security baseline, naming, deployment policy), keep them in one private
organization guide repository instead of copying them into each repo or
forking Moru Core. Moru loads such a guide as its own layer
(`docs/org-guide-layer/prd.md`):

- Register it once per machine:
  `<MORU_LAUNCHER> workflow org add --id <id> --remote <guide repo> --match <host/owner/*>`.
  `workflow org sync` updates it on request; `workflow org status --project <repo>`
  shows which guide a repo binds to. A repo can pin a guide and commit in a
  tracked `.moru-org.json`.
- `start` then lists the guide's entry, enforced documents and matching
  documents as `org:<id>/<path>` with absolute paths. Read them like required
  docs. A missing, ambiguous, modified or mis-pinned guide stops the run, and
  `finish` fails if the guide changed while the run worked.
- The guide repository mirrors Moru's shape: `org.json`
  (`schema_version`, `id`, `enforce` items with a `concern` and `doc`),
  `AGENTS.md`, `skills/<skill>/...`, and `workflow-doc-surfaces.json`.

Without registration, or for a runtime that does not run Moru's `start`,
connect it by reference:

- The target repo's `AGENTS.md` names the guide by a repo-relative or
  documented checkout path and the sections that apply, for example
  "UI work: read `<ORG_GUIDES>/skills/design-system/SKILL.md`". Do not paste
  the guide's text into the repo instructions or into Moru Core.
- A referenced organization guide counts as target-repo instructions. The
  repo's own text wins over the guide it references; the guide wins over
  specific and common Moru guidance.
- When the guide marks a rule as mandatory for security, data, deployment,
  cost, or verification and the repo conflicts with it, stop and report the
  conflict instead of choosing a side.
- A personal or unrelated repository never inherits organization rules from
  user-global runtime instructions; only repos that reference the guide use it.
- Keep organization guides out of public repositories, Moru Core, synced
  settings, and project memory.
