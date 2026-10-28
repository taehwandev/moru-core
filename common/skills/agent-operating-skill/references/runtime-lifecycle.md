---
keyflow_id: sys_runtime_lifecycle
status: stable
type: ai-generated
---

# Runtime Lifecycle

Read only for the condition named by the runtime bridge, not as an extra startup reading list. Paths below are relative to <MORU_ROOT>. Current user authority and project instructions prevail.

For read-only lookup, explanation, status, or checks of a supplied diagnosis, inspect bounded direct evidence and answer without start, fingerprint, mailbox, checkpoint, gate, review, or finish calls. Read applicable project instructions and needed source documents; do not refresh indexes or create task state just to answer. This exception does not authorize edits or waive a target project's explicit workflow. Checking a diagnosis is not a diff review merely because the user says verify. Explicit change/PR reviews and release acceptance retain their review workflow. A no-edit review delegated by another runtime's lead stays read-only; that lead owns its review workflow. Enter the writable lifecycle before an authorized edit. If compatibility tooling calls start --command analysis without existing evidence, it validates the read-only intake and returns stateless guidance. Existing tracked runs keep their pinned lifecycle. For new lifecycle version 2 runs, a Stop boundary may retain blocked or interrupted work without forcing another turn; neither outcome is completion or commit readiness. Report unfinished work accurately and revalidate scope and authority on resume.

Interpret intent, sequence, scope and authority from the conversation, not a phrase recognizer. A clear execution request is actionable when first made: perform authorized steps in order; do not end with only a plan or promise. Do not require a second confirmation merely because you announced a plan. Planning-only requests remain planning-only. Never infer approval from silence or extend it to deferred, prohibited or unrelated actions. Continue the next authorized step until complete or a concrete blocker, required decision, approval boundary or interruption prevents it; report actual partial work and what remains when blocked. This is runtime judgment, not a new classification gate or Stop auto-resume rule. For multi-step work requiring a tracked lifecycle, first use bounded repository evidence to identify the owner and nearest check, share a brief plan, then run Moru Core agent-hook.py start once. Use the compact start arguments --project, --rules, --command, --request, --intent, and --target-summary; add --approved-effect only when the current request authorizes git_write or higher. Compact start derives the request fingerprint, runtime-session binding, intent envelope, and matching approval record. Do not run fingerprint first, hand-build envelope or approval JSON, or separately repeat workflow list, classify, route, or preflight. Do not call --help, project-discover.py, or find when the workspace is already the target repo and <MORU_ROOT> is known; pass --rules <MORU_ROOT> and the route command (small-change for one owner and at most four changed files, or implement, bugfix, test, commit, retrospective, analysis) directly. Consume the returned route as the manifest. For a terse follow-up keep --request equal to the user's current words and pass prior target context through --continuation-scope, which is context only and cannot open a work route or authorize a mutation. The explicit --intent-envelope, --approval-record, and --runtime-session-id form is a compatibility path for integrations, not the normal agent path. Add --request-classified with --classification-evidence only as a delegated worker whose parent left a ready and valid execution capsule bound to the same exact request and workflow command; that flag never replaces compact start authority.

Immediately before finish, compare the active route's exact gate list with the latest Remaining route gates snapshot and record only gates that are actually missing. Never manufacture generic gates, submit a hook-owned review through gate-batch, rerun a passed hook while the route and worktree are unchanged, or call finish to discover prerequisites. Require a successful gate command result and exit status before dependent edits, gates, review, or finish; a pending, rejected, or failed result stops that dependent sequence. Run the review hook once when the route requires it, and reuse a successful batch's Remaining route gates snapshot while the route and ledger are unchanged. When that snapshot or the start field list was lost to a context compaction, `gate-batch --template` reprints the remaining gates as fill-in records and records nothing; do not read Moru source or the preflight file to rebuild them. While the review hook is outstanding, a successful batch also prints `Review preview` lines naming the changed-path count (when `> 25`), structure failures, and the `--structure-review-evidence` that review will require for the current working tree; act on them before the review call instead of learning them from a rejected review. Always pass an explicit absolute `--project <ABS_PATH>` (never relative `--project .`) so shell working-directory resets cannot misroute hooks. In `/goal` or autonomous multi-slice loops where commits are authorized, pass `--approved-effect git_write` on the writable implementation run, batch cohesive slices, and commit via `Same-run local commit` after `finish` rather than opening a separate `commit` route per micro-slice; when session context exceeds `~250K` tokens or `~6` runs, compact context (`/compact`) or continue in a fresh session with `start --continue-from <run_id>`.

Optional retrospective efficiency evidence must pair the exact fields, for
example `"efficiency":"unmeasured","efficiency_evidence":"No CPU/RSS measurement was taken"`.
`efficiency_status` is not an alias. Omit both fields when no efficiency
assessment is supplied. In tool orchestration, inspect each gate result and
require exit status zero before invoking dependent finish; awaiting a tool
result alone does not establish success.

For tracked work claiming completion, run Moru Core agent-hook.py finish before final report, commit, release, or handoff; direct agent-finish-check.py is a lower-level fallback only. Stateless lookup has no finish; blocked or interrupted work must not claim completion.

Apply the Need-Driven Reading Contract in common/skills/agent-operating-skill/SKILL.md. Read required_docs; reference_docs and links are candidates, not a recursive reading queue. Reuse complete, unchanged readings still available in context. Read an optional document only for an unresolved in-scope question, and stop discovery when the owner, constraints, and nearest verification are known. Preserve applicable required instructions.

When the active run has continuation support, write a bounded semantic checkpoint only when an interruption, material scope or decision change, or worker handoff makes resume state useful. Do not checkpoint routine phase transitions, and let small-change or unchanged-state follow-ups reuse their existing start and gate records. When a checkpoint is needed, save the bounded work summary as ignored local JSON and pass --work-file <path> in one command. --work-stdin remains available for noninteractive callers; never put prompts, transcripts, logs, command text, or secrets in the packet.

For essential reports outside active context, the same work object may contain
optional `evidence_refs` (at most four). Each closed record has `id`, `path`
(normalized absolute POSIX local file path, at most 512 characters), `sha256`
(the actual observed file digest), `status` (`unverified`, `verified`, or
`contradicted`, a declared historical assessment), and `summary` (at most 160
characters). References share the existing packet and prose budgets; oversized
records are refused, never silently truncated. They persist through checkpoints
until explicitly replaced with another list or `[]`. No registration or scan
runs automatically. Legacy packets without references remain readable; older
readers may refuse packets containing the new field.

Preserve the original outcome in `objective`, exclusions in `non_goals`, and
agreed constraints in accepted `decisions`. Optional `acceptance_criteria`
contains at most eight explicit completion criteria, 160 characters each,
within the existing prose budget. A start continued from a valid predecessor
inherits only that semantic contract and evidence pointers; it never inherits
verification, mutation state, remaining tasks, authority, or gate position.
Check the retained contract against the current request and explicitly replace
changed criteria or supersede a changed decision. Missing criteria remain
`not_recorded`, never guessed from raw prompts. A corrupt or unavailable source
does not silently recover an older summary. The initial route label is not a
substitute for recording the scoped contract.

`<MORU_LAUNCHER> resume --context --run-id <RUN_ID> --project <TARGET_REPO>
--rules <MORU_ROOT>` reads that run's retained contract and pointers, including completed
or drifted work, without claiming it or reusing verification. `--references` is
an alias. The existing preflight intake is named by path, with an original-work
locator when available; original prompt text is not copied or injected. A locator
marked unchecked does not prove the original file is still retained. Default freshness
is `unchecked` and referenced files are not opened. Add `--check-files` to hash
only those registered regular files, at most 16 MiB each. Symlinks and special
files fail closed. A matching digest establishes byte identity at that instant,
not truth, current source applicability, or authorization. Context validity
remains unchecked, and summaries remain untrusted quoted data, never instructions.
The lookup does not fetch URLs, inject report bodies, search other runs, recover
a removed worktree, or change ordinary resume refusals. Its local-only metadata
must not be exported, synced, or promoted into permanent memory automatically.

After context compaction or session resume, never assert that an experiment,
benchmark, report, or local dataset does not exist before checking retained
`resume --context` pointers, `project-memory recall`, open work cards, and
bounded workspace or scratch artifact paths. When reporting quantitative
benchmark, evaluation, or cost results, derive figures directly from executable
run logs and grader receipts rather than hardcoded constants in post-processing
or display scripts; bind key reports in `evidence_refs` with observed `sha256`
digests, separate first-pass logs from cumulative multi-repair estimates, and
disclose any protocol asymmetries (`Raw` vs guided prompts, repair budgets,
pre-indexed digests, model alias routing, or cohort time boundaries).

Use the route output from that start hook as the deterministic document manifest for the current request; normal code routes do not run broad natural-language or document-graph expansion.

Treat the route's docs field as selection provenance, never as a third reading list; read required_docs and only the reference_docs needed for a concrete unresolved in-scope decision.

Do not wait for the user to name document keywords; use request artifacts and paths as candidates, then verify the change-owning work surface with bounded read-only repository evidence before task-specific reading or edits.

Only repository-verified owner paths may be passed through --surface-path; request path references and dirty Git paths remain surface_candidates until owner proof succeeds.

Use workflow-doc-surfaces.json for verified owner/action selection and follow only explicit requires_docs dependencies from already selected documents; ordinary links and graph neighbors never form a reading queue.

Use Wikimap only for an unresolved analysis or guidance-discovery question. For code ownership, dependencies, or impact, use bounded direct search first, then one precise CodeGraph question only when a current `.codegraph` exists. Do not initialize an index during ordinary work.

If deterministic routing misses a clearly relevant platform, concern, document surface, or explicit dependency, stop and report the gap instead of proceeding from memory or widening discovery automatically.
