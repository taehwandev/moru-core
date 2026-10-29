---
keyflow_id: sys_operating_document_memory
status: stable
type: ai-generated
---

# Documents And Search Details

Read only the section needed for an in-scope decision named by
[AGENTS.md](../../../../AGENTS.md); this is not another startup reading list.
Paths in code spans are relative to <MORU_ROOT>. Current user authority and
project instructions prevail.

## Documents And Search

Apply the Need-Driven Reading Contract in
`common/skills/agent-operating-skill/SKILL.md`. Read the route's
`required_docs` and explicit `requires_docs` dependencies; load
`reference_docs` only for an unresolved in-scope decision. Ordinary links,
graph neighbors, the route's provenance-only `docs` field, and spare selection
budget never form another reading queue. Generated pointer entrypoints resolve
to their reference; retain substantive entrypoint rules alongside it.

Normal implementation selection is deterministic: the command workflow,
guaranteed gate/risk contracts, and verified owner/action guidance. Preserve
required dependencies regardless of optional budget. `docs`, `prd`, and
`task` do not fill spare slots with generic intake or discipline references.
A prompt advisory suggests a route, not an actionable task; its platform cards
remain references until the request or verified owner requires them. For
`analysis`, preserve `reading_scope`: read the answering definition and only
the callers needed to resolve the question, not implementation procedures.

For unresolved guidance discovery, use `workflow query`, or Wikimap after
bounded direct evidence; its results remain candidates unless route policy or
an explicit dependency selects them. Do not reread `index.md` after routing.
It is a fallback catalog, not an additional startup requirement: use it only
for an explicit catalog task or, with user approval, when routing is unavailable.

For code-only ownership, call flow or impact, use bounded direct search first,
then one precise CodeGraph question only if a current `.codegraph` exists.
Limit results to useful files, treat returned source as read, and check
staleness after edits. Do not initialize an index during ordinary work. Stale
or absent graphs fall back to direct evidence; an empty search is terminal
without a new lead. A missing required document
invalidates the manifest and stops work.
## On-Demand Project Memory And Work Cards

`<MORU_LAUNCHER> project-memory` keeps agent-written project guidance in a
user-local store shared by linked worktrees. Task start does not scan, recall,
or maintain that store. Use explicit `project-memory recall` only for a concrete
missing project fact; its results are reference, never authority. Reuse retained,
unchanged readings and analysis before searching again. Moru never captures
on its own:
Claude and Codex keep durable project knowledge here, not in runtime-private
memory (for Claude, this overrides `~/.claude/projects/*/memory`, which keeps
only user, feedback, and reference entries). Capture only a verified root cause,
pitfall, decision reason the code does not show, or a fact the user asks to
remember, when confirmed or at finish, with `--project`, `--source` and a
future `--review-on`. When verified, include the applicability and known
exceptions with `--applies-when` and `--not-when`; compare recalled conditions
with current evidence before using the advice. Correct with
`capture --replaces <id>` or `retire <id>`.
Never capture secrets, transcripts or speculation, and never sync it or put its
content in a continuation packet. Run `project-memory consolidate` only when
reviewing the store is useful. Permanent rules belong here or in
shared guidance, task state in checkpoints, and user preferences in runtime
memory.

For costly repeated source analysis, an agent may explicitly capture a verified
conclusion with `--analysis-question`, `--analysis-context` and tracked source
paths. If that captured analysis is missing from current context, explicit recall
with the same question, context and scope can return bounded candidates. Recheck
external assumptions and current instructions; never query merely at task start.
See the analysis-candidate contract in `docs/project-memory.md`.

Start also lists up to three other open work cards as reference context. When
one names work already finished elsewhere, run `<MORU_LAUNCHER> work-cards close
<work id>`. Keep prompts, transcripts and logs out of `--target-summary`.
Storage, ranking and resume mechanics: [docs/project-memory.md](../../../../docs/project-memory.md).

When changing document routing, read
`docs/skills/agent-runtime-integration/references/document-routing-changes.md`.

PRDs, specs and ARDs follow `common/skills/doc-conventions/SKILL.md`; report
their output path.
