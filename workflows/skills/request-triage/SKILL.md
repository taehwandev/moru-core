---
name: request-triage
description: "Request Triage Workflow: Use when the agent needs to decide whether a user request is clear, whether a Grill-Me /grilling session is needed, and what effort level or route should be used before planning or implementation."
keyflow_id: sys_workflows_request_triage_md_skill
status: stable
type: ai-generated
metadata:
  internal: true
---

# Request Triage Workflow

Use when the active route selects this skill or when judging whether a request
is ready for a writable route versus Grill-Me / co-design alignment.

## Process

1. Attribute every user-visible behavior, UX flow, or prose/thesis decision to a
   verified source before starting a writable route:
   - `request:<quote>` — verbatim substring from `--request`
   - `conversation:<quote>` — confirmed answer in `--continuation-scope`
   - `repo:<path[:line]>` — existing repository file/line constraint
   - `assumed:<choice>` / `--open-choice "<choice>"` — unconfirmed agent assumption
2. Do not auto-fill an `assumed` choice or attribute an agent inference to
   `request:`. When any user-visible choice is `assumed` or bounded inspection
   reveals coupled adjacent/sibling surfaces outside the named target, align
   before writable `start` (or on read-only `triage`/`ambiguity`): share repo
   findings, a concrete 2–3-line sample or design sketch, and focused Grill-Me
   decision questions, then pass the user's answer in `--continuation-scope`
   with `--decision-source conversation:<quote>`.
3. When all choices are backed by `request:`, `conversation:`, or `repo:` and
   no open choices remain, proceed directly on the matching route with zero
   extra confirmation ceremony.

Read `references/current-guidance.md` for applicable decision rules, stop
conditions and verification before acting. Open related cards only for
in-scope work, starting with their `SKILL.md`. Use this canonical bundle,
not legacy flat paths. When changing routing, confirm it selects this
entrypoint; when changing guidance, validate the reference's links and
frontmatter.
