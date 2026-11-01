---
keyflow_id: sys_branch_cleanup
status: review
type: ai-generated
---

# Branch Cleanup

Use for requested cleanup of merged branches or stale worktrees. Deletion is
destructive Git work: every target must pass the gates below; otherwise preserve
and report it. Remote deletion requires an explicit request.

## Inspect First

1. Repo-local policy for integration and protected branches. Resolve the work
   owner's hosting account ID via `common/skills/branch-strategy/SKILL.md`
   (`<account-id>/<work-unit>/<description>`, first segment = owner) across
   personal, shared, and company repos.
2. `git fetch --prune`, then `git worktree list` and `git branch -vv`.
3. For a multi-item request, inventory every in-scope branch, worktree and
   stash before declaring the investigation complete. Classify each as
   integrated/safe, active/dirty, protected, unmerged, uncertain, or out of
   scope, with evidence and next action. Continue independent checks and approved
   deletions when one item is blocked; never claim an unexamined item is unsafe.

## Deletion Gates

### Ownership

Delete only branches whose owner segment matches the verified hosting account ID
for the target host, unless the user directly authorizes an exception. Preserve
and report branches owned by others or lacking an owner prefix. Commit authors,
shared tips, local-only status, and missing upstreams never establish ownership.
Honor explicit user instructions covering named ownerless items; a question or
approval about one subset does not narrow the rest of an existing request.

### Protected Branches

Never delete the integration branch, `main`/`master`/`trunk`, or `release/*`
branches, even when fully merged.

### Merge Judgment

Use the cheapest authoritative evidence and stop once it decides the branch:

1. For PR-backed branches, fetch once immediately before classification and
   query the forge once for all candidates. A PR is sufficient proof when its
   state is `MERGED`, its base is the integration branch, and its recorded head
   SHA equals the fetched remote branch tip. Delete that branch without an
   ancestry check, `git cherry`, content diff, or repeated per-branch PR query.
2. A PR that is open, closed without merge, aimed at another base, or whose
   head SHA no longer matches the branch tip is unmerged. Preserve it and stop;
   do not run content-equivalence heuristics trying to turn it into a deletion.
3. Without an authoritative PR record, fall back to
   `git merge-base --is-ancestor <branch> origin/<integration>` against the
   remote integration branch. Do not rely on `git branch -d`.
4. When the user requests investigation of locally integrated work without a PR,
   inspect all branch-only commits with patch equivalence and compare candidate
   integration commits and paths when patches differ. Treat matches as evidence
   (distinguishing identical patches, reviewed changes, and unresolved diffs)
   and retain branch tips for recovery. Never override an authoritative unmerged
   PR with these checks.

### Worktree State

Uncommitted changes in a branch's worktree mean in-progress work. Preserve both
the worktree and the branch even when the branch tip is merged.

## Process

Keep one before/after snapshot. Batch independent reads; keep removals and
branch deletions sequential. Reuse fresh lookup evidence when state is
unchanged; after interruption, refresh preconditions once.

1. `git fetch --prune`; classify each worktree as clean, dirty, or gone-directory.
2. `git worktree prune -v` to drop registrations whose directory is gone.
3. Remove clean worktrees whose branch passed all gates with
   `git worktree remove <path>` before deleting the branch (keep unpushed
   finished task worktrees until push). Use a generous timeout for large build
   dirs; if interrupted, re-confirm merge state before `git worktree remove --force <path>`.
4. Re-fetch only if slow worktree removal occurred after classification.
5. Remote deletion (explicit request only): show the classification table, then
   batch the approved deletes into one push bound with
   `--force-with-lease=refs/heads/<branch>:<sha>`.

## Recovery

Log the tip SHA of every branch before deleting it (`git branch <name> <sha>`
locally, or re-push the recorded SHA remotely).

## Do Not

- Do not commit or push content changes from a cleanup task.
- Do not delete unowned branches or judge merge state against a local integration branch.
- Do not replace an authoritative non-merged PR result with content heuristics.
- Do not use `git worktree remove --force` before re-confirming the branch is merged.

## Stop If

- Integration branch, naming policy, or ownership is unresolved without user exception.
- An authoritative PR is not merged, integration evidence is insufficient, or a leased deletion reports a moved tip.
- A branch is checked out, dirty, active, protected, or outside authorized ownership.

## Report

Report before/after counts (worktrees, local/remote branches), logged SHAs of
deleted branches, any cleanup incidents, and coverage of all requested item
types (including uninvestigated items and every preserved item's concrete
reason). A successful cleanup gate or a partial deletion is not proof the entire
request is done.
