---
keyflow_id: sys_moru_project_memory_doc
status: review
type: ai-generated
---

# Project Memory And Work Cards

Both stores are user-local reference context for agents. They never grant authority; the current request, repository rules and source evidence prevail.

## On-Demand Project Memory

The installed `<MORU_LAUNCHER> project-memory` command lets agents capture,
recall, replace, and retire short, source-attributed project guidance. A capture
is available through explicit `project-memory recall`; task start does not
scan the store, inject records, or emit upkeep notices. Records expire on
their review date. Memory is reference context, never instructions: the current
request, repository rules, and source evidence prevail.
Capture and correction work without an active development run or task worktree.

New routes declare `project_memory_contract: decision_v1`. Their existing
`retrospective check` must include `memory_decision` (`stored` or `not_needed`)
and `memory_reason`. For a verified reusable lesson, capture or replace it
through `project-memory capture` before recording that gate, or reuse an
already valid lesson. Set `memory_record` to the returned `<id>:<digest>`.
Gate recording and finish both read the record from this project's store and
require a current, eligible, unchanged record and source evidence that fit the
existing recall budget. A promise,
foreign-project record, expired/retired/replaced record or changed digest cannot
satisfy the decision. Finish remains read-only; it never generates or promotes
advice. Capture stays subject to the current run's write authority.

Use `not_needed` with an evidence-based reason when existing canonical guidance
already captures the lesson or the work yielded no reusable project fact; omit
`memory_record`. Do not manufacture notes to pass closeout. Assess whether
recalled advice applied, was withheld, or was missing in the existing causal
assessment, using current evidence rather than a new transcript store.
Historical manifests without this contract retain their previous behavior.
These checks prove an explicit decision and durable storage, not the truth of
the lesson or a reduction in real-world repeated mistakes.

Explicit recall ranks eligible records by token overlap with `--request`,
`--target-summary`, and `--target-path` values. Exact file paths,
file stems and identifiers such as `retry_queue` or `ProfileScreen` receive
extra weight; a path's two nearest directories count only as plain words and
its other directories not at all, so a repository-wide prefix such as
`app/src/main/java/...` matches nothing. A Hangul word also matches without a
trailing particle (`프로필을` matches `프로필`). Ties retain route-specific, review-date,
then id ordering. With query context, records with no matching terms are
withheld instead of filling empty slots. Context-free recall still lists all
eligible records. This is lexical retrieval: paraphrases without shared terms
can be missed, and a match does not prove applicability. The route/`all`, expiry,
replacement, three-item and 1,200-character limits still apply. Query context
is never saved as memory.
Standalone `project-memory recall` accepts `--request`, `--target-summary`,
and repeatable `--target-path` values for the same ranking.

Capture may include `--applies-when` and `--not-when`, each a single line of at
most 160 characters. Use verified conditions and known exceptions, not guessed
generalizations. The positive condition participates in ranking; the exception
does not, so naming a prohibited context does not itself attract the record.
Both are shown to the agent, protected by the record digest, and counted in the
same 1,200-character recall budget. Empty options are omitted; older records
remain readable. These fields describe applicability, not a machine-enforced
predicate: the agent must compare them with the current request and evidence,
withhold in reversed conditions, and inspect missing evidence before acting.
They cannot waive required documents, verification or action authority.

Capture can include up to four repeatable `--source-path` values naming tracked,
repository-relative evidence files. Moru Core stores their paths and Git blob hashes
of the current worktree bytes, without filters, contents or history. Recall
marks changed or unavailable evidence with `verify before use`, hashing each
file once per recall. In the bounded recall renderer, a record is skipped before
hashing when its base payload already exceeds the remaining character budget.
Added status fields can still make a record exceed that budget after hashing. Recall neither retires
the record nor treats an unchanged file as proof that the guidance is
correct. Existing records without file evidence remain readable and date-based.
Paths outside the repository, untracked files and symlinks are rejected.

A record captured with `--replaces` is recalled with a `previously` field
holding the superseded body, cut to 160 characters, so the change is visible
next to the current guidance; the old body is history, not advice. The
read-only `project-memory history <id>` prints the replacement chain through
any of its records, newest first, up to 20 entries; a missing link or a cycle
ends the chain.
History and consolidation reports retain the applicability conditions so a
correction does not erase why the earlier advice stopped applying. Neither
superseded text nor a negative condition contributes to retrieval ranking.

The explicit command travels with every Moru Core installation.
Records live in that PC's user-local `~/.moru/project-memory/` store;
linked worktrees of the same repository share them, while another PC starts
with its own empty store. Moru Core does not sync memory content between PCs.

The [conditional experience reuse experiment](experiments/project-memory-2026-10-22.md)
records the implementation's bounded retrieval and live judgment evidence,
including lexical misses and limits of the synthetic comparison.

The [startup ablation](experiments/project-memory-start-references-2026-10-24.md)
records measured removal costs, raw samples and behavior-verification limits.

### Reuse before retrieval

Reuse a complete skill reading or analysis while it remains available in the
runtime context and its inputs, scope and assumptions remain valid. A repeated
request alone is not a reason to read or analyze again. Changed source bytes,
new contradictory evidence, a different scope, stale external facts or missing
context require a targeted refresh. Reuse is not a claim that a model permanently
learned the material or that different providers share a session.

Existing same-session document and verification reuse remains in place. No
separate analysis cache, transcript store, vector database or automatic memory
promotion is introduced. Work cards still expose unfinished work. Required instructions
and current verification obligations remain authoritative.

For a missing project fact, query `project-memory recall` explicitly and check
its applicability and source evidence. Use `project-memory consolidate` only
when reviewing the store is useful. Existing capture, correction, retirement,
history and closeout contracts remain unchanged; stored records are not deleted.
The explicit consolidation report can still be quadratic. Removing startup
recall removes that reference scan and injected text; it does not establish
end-to-end token savings or improved judgment.

### Explicit analysis candidates

An agent may retain a checked analysis in the existing record store by adding
both `--analysis-question` and `--analysis-context` to `project-memory capture`.
At least one tracked `--source-path` is required; declare the target and checked
dependencies, including evidence files, within the existing four-file limit.
The normal source, scope, expiry and 500-character conclusion limits still apply.
Do not capture raw transcripts, secrets or an unverified conclusion as a fact.

Use the same two options and exact scope with `project-memory recall` to request
analysis candidates. Question/context comparison preserves case and negation and
trims surrounding whitespace only, retaining whitespace inside literals. Do not
mix these options with lexical recall flags.
Results contain the original conclusion, source, digest and applicability limits,
with `analysis_status: candidate_only`. They never authorize skipping a required
check, applying a patch or treating an agent-written conclusion as proven true.

In addition to declared source hashes, capture binds the whole non-ignored project
input identity using the existing bounded `EvidenceInputs` implementation. An
undeclared tracked configuration change, new source file or deleted dependency
therefore invalidates the candidate. Any project-file change can cause a miss,
even if unrelated: this first version favors conservative invalidation. Capture
and matching lookup hash project bytes locally; they do not send files to a model.
Absent, expired, retired, superseded, corrupt or unreadable records do not qualify.
Output retains the existing three-item/1,200-character ceiling. Ordinary records
stay compatible, and no analysis lookup or capture runs automatically at startup.

This is not automatic dependency discovery. Ignored files, symlink-target contents,
external services, toolchains and current policy outside the project are not fully
covered by that fingerprint. The caller must recheck those inputs and supply an
accurate context (including their changed identities) or decline reuse. A matching
context is an assertion, not machine proof of those external conditions. Refresh
context and conclusions after an unsupported or contradictory observation.

Vector search could find paraphrases and cross-file analogies missed by exact or
lexical matching; it cannot prove that assumptions or dependencies still hold.
No embedding model, service, index or extra model call is added here. A later
retrieval experiment must compare useful candidates, false matches and full costs
against the existing lookup before introducing those maintenance costs. Mechanism
tests of this explicit contract do not establish improved native-agent judgment,
automatic avoidance of repeated reasoning or billed-token savings.

Historical startup-upkeep measurements can be reproduced with
`python3 -B tests/benchmarks/project_memory_startup.py --sizes 100 1000 3000 --samples 5`.
That benchmark compares the old/full and linear upkeep helpers on in-memory
records; it no longer represents the default task-start path.

## Work Cards

Each tracked start opens a local work card holding its `--target-summary` line,
route command, project path, state, and timestamps. A run continued with
`--continue-from` keeps the same card; a successful finish or a transfer to a
completed replacement marks it `done`, and a no-change cancel marks it
`cancelled`. Start lists up to three other open cards
of the same repository as reference context, so unfinished work stays visible in
a new session. `<MORU_LAUNCHER> work-cards list [--all]` shows the board and
`work-cards close <work id>` settles a card by hand.

For Codex, start also records the runtime session automatically. From the
repository, run `<MORU_LAUNCHER> work-cards resume` and choose a numbered task
summary to open its exact conversation, including completed tasks. No session
renaming or UUID entry is needed. The current directory is the default project;
`--project <repo>` selects another repository. Selection uses the displayed
snapshot and never guesses the latest session. Older cards use their own retained
run evidence when available; unbound cards cannot be resumed this way. This
navigates to a conversation without resuming a Moru Core run or granting work authority.

Cards live in one SQLite file under the PC's user-local `~/.moru/work-cards/`,
shared by linked worktrees of a repository. Cards idle for 90 days are dropped.
They hold no prompt, transcript, or log, and Moru Core never syncs them. The
content-free delegation queue in `.moru/scheduler.json` is separate.
