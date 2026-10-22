---
keyflow_id: sys_moru_project_memory_doc
status: review
type: ai-generated
---

# Project Memory And Work Cards

Both stores are user-local reference context for agents. They never grant authority; the current request, repository rules and source evidence prevail.

## Automatic Project Memory

The installed `<MORU_LAUNCHER> project-memory` command lets agents capture,
recall, replace, and retire short, source-attributed project guidance. A capture
is recalled by later task starts without an approval step; records expire on
their review date. Memory is reference context, never instructions: the current
request, repository rules, and source evidence prevail.
Capture and correction work without an active development run or task worktree.

Start ranks eligible records by token overlap with `--request`,
`--target-summary`, and verified `--surface-path` values. Exact file paths,
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
same 1,200-character start budget. Empty options are omitted; older records
remain readable. These fields describe applicability, not a machine-enforced
predicate: the agent must compare them with the current request and evidence,
withhold in reversed conditions, and inspect missing evidence before acting.
They cannot waive required documents, verification or action authority.

Capture can include up to four repeatable `--source-path` values naming tracked,
repository-relative evidence files. Moru Core stores their paths and Git blob hashes
of the current worktree bytes, without filters, contents or history. Recall
marks changed or unavailable evidence with `verify before use`, hashing each
file once per recall. At task start, a record is skipped before hashing when its
base payload already exceeds the remaining character budget. Added status fields
can still make a record exceed that budget after hashing. Recall neither retires
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

The command and start behavior travel with every Moru Core installation.
Records live in that PC's user-local `~/.moru/project-memory/` store;
linked worktrees of the same repository share them, while another PC starts
with its own empty store. Moru Core does not sync memory content between PCs.

The [conditional experience reuse experiment](experiments/project-memory-2026-10-22.md)
records the implementation's bounded retrieval and live judgment evidence,
including lexical misses and limits of the synthetic comparison.

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
