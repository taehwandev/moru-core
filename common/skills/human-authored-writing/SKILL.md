---
keyflow_id: sys_common_human_authored_writing_md_skill
status: stable
type: ai-generated
---

# Human-Authored Writing

Use when routed to `common/skills/human-authored-writing/SKILL.md`, when
drafting or editing user-facing READMEs, product/report pages, comparison
tables, chart labels, or localized guides, when prose needs voice or
AI-writing-signal cleanup, or when an intended reader cannot reconstruct a
technical explanation from the text.

## Core Rules

- **Lead with reader-visible actions and outcomes, not internal jargon.** Never
  expose raw internal gate names, CLI flags, validator slugs, schema keys, or
  stiff compound nouns as user-facing headings, chart labels, or table headers.
  Say what the user or system actually does in plain words first; place exact
  CLI flags or commands in parentheses or code blocks only where the reader
  needs to run them.
- **Calibrate against nearby repo copy before drafting.** Before adding a new
  page, report, or README section, read 2–3 existing user-facing pages in the
  same repository and match their vocabulary level, sentence length, and tone.
- **Translate meaning, not literal jargon calques, in localized docs.** In
  Korean, Japanese, and Chinese guides, replace word-for-word calques of
  internal English nouns with natural native developer phrasing while keeping
  every measured number and fact intact.

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
