---
keyflow_id: sys_operating_collaboration_review
status: stable
type: ai-generated
---

# Parallel Work And Handoffs Details

Read only the section needed for an in-scope decision named by
[AGENTS.md](../../../../AGENTS.md); this is not another startup reading list.
Paths in code spans are relative to <MORU_ROOT>. Current user authority and
project instructions prevail.

## Parallel Work And Handoffs

Consume `parallel_execution.delegation_policy`. Keep roles in the same session
by default. Delegate only when a bounded question, risk, or decision has a
concrete benefit that exceeds coordination cost. Parallel work also needs at
least two meaningful slices, disjoint owned and forbidden scopes, a stable
shared contract, a named integration owner, and focused verification.
Independent slices alone do not require delegation. Other runtimes are optional
and need available tools and existing access; never assume subscriptions or
switch to paid APIs automatically. Record the concrete serial reason when
staying in the parent. See
`workflows/skills/multi-agent-collaboration/references/on-demand-orchestration.md`
for role selection, unavailable-provider handling, and closeout evidence.

Before any worker boundary, run the handoff hook. Only a ready, valid execution
capsule permits reuse of the parent's route, preflight, required-doc brief, and
gate context. The parent alone owns the gate ledger, integration review, and
finish. A worker handoff does not satisfy the user-facing `handoff` gate.
Reuse a valid execution capsule across same-wave workers instead of calling
`handoff` per worker, cap `handoff` calls at `<= 4` per run, and treat workers
as bounded one-shot tasks rather than persistent worker threads polled across
slices. In multi-slice or goal loops where commits are already authorized by the
user, pass `--approved-effect git_write` on the writable implementation run,
batch related slices, and use `Same-run local commit` after `finish` instead of
starting a separate `commit` lifecycle per micro-slice.

At any task boundary, when session context exceeds `~250K` tokens (or `~6`
Moru runs), use a new session or `/compact` for unrelated work. For a related
follow-up, keep needed context or rotate with `start --continue-from <run_id>`.
This is advisory; runtimes that already auto-compact need no extra action.
When finish emits a context nudge, relay one short reminder in the final reply
in the user's language; omit internal run IDs and workflow commands.
### Long-Running Multi-Runtime Builds

Use when a script, not a live parent session, runs several headless writers
(`claude -p`, `codex exec`, `agy -p`) in phases over separate worktrees with
path ownership, for example a planner plus parallel owners plus ticket rounds.

- Brief each writer as headless: no one will answer a question, so it takes the
  least-destructive default, lists it under "Assumed" in its report, starts
  Moru before its first project write and ends finished or blocked, never on a
  question. Check each worktree for its own run record after the phase; a
  writer without one skipped the lifecycle and its result is unverified.
- Liveness: measure idle time from the writer's own start and from its event
  stream when it has one (`codex exec --json` command events), never from old
  file mtimes. Kill only after a long idle window, log it, and treat the phase
  result as unverified rather than finished.
- Exit: a writer may finish its work and never exit. Tell writers to stop the
  servers, browsers and background commands they started before the final
  report; the orchestrator still needs the idle watchdog for when they do not.
- Report two results per writer: the process exit code and the run's finish
  status. A zero exit with an open run is `needs_inspection`; hand its
  remaining gates to the integrator instead of rerunning the whole slice.
- Scope resume state to the phase that set it (skip lists, continue lists);
  clear it before the next phase so a resume of phase 2 cannot shrink phase 4.
- Check ownership against the merge base of the writer's branch, not the moving
  main, or every earlier merge is reported as a foreign edit.
- Usage limits: on a limit, wait and continue the same conversation; record a
  checkpoint with `remaining_work` at the start of every long phase so a
  continuation resumes instead of restarting.
- Show the user only frames of owned work; skeleton or stub captures are
  `PLACEHOLDER` (see `common/skills/ui-visual-verification/references/current-guidance.md`
  `## Canvas, WebGL And Timeline Output`).

## Review Boundaries

Line-count review budgets apply to **Git-tracked incremental commits** (`HEAD`
present) where atomic diff history matters: plan new or substantially expanded
development files within a commit to stay within at most 300 added lines, four
top-level owners, and one public/exported top-level owner unless a stricter
repo rule applies. In **unbound or initial full-build workspaces without Git
commit history** (`!has_git_head` or non-Git directories), do not enforce
per-file line-addition caps; instead, organize code into single-responsibility
modules and enforce executable functional/visual verification gates so full
builds are never throttled or stubbed to fit a diff budget. Even in Git-tracked
repositories, never downgrade, simplify, or omit requested features or visual
fidelity to stay under 300 lines—split cohesive responsibilities into sibling
modules or sequential atomic commits instead. An owner is a type or class, a
declaration marked `export`/`public`/`pub`/`internal`, a capitalized component
or `use*` hook, or any non-private Kotlin top-level declaration; plain
lowercase functions in languages such as Python are not counted. Split
independently nameable sections before review. Tests keep their separate wider
budget.

Count task-owned changed paths before review; the default maximum is 25. Raise
it only for one cohesive mechanical migration, using the exact observed count
and a narrow owned pathspec. An added runtime file in an existing multi-role
package, or a new runtime package boundary, requires:
`owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...;
verification: ...`.

Subject unit tests mirror the production owner's logical package/folder and use
the subject name. Broad feature test locations are reserved for genuine
cross-owner contracts or integration flows.
