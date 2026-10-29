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

1. Repo-local policy for the integration branch and protected branches. Resolve
   the work owner's hosting account ID using
   `common/skills/branch-strategy/SKILL.md`; its shared format is
   `<account-id>/<work-unit>/<description>`, where the first segment is the
   owner. Apply the same identity rule in personal, shared, and company repos.
2. `git fetch --prune`, then `git worktree list` and `git branch -vv` for the
   current state.
3. For a multi-item request, inventory every in-scope branch, worktree and
   stash before declaring the investigation complete. Classify each as
   integrated and safe, active or dirty, protected, unmerged, uncertain, or
   outside the approved scope, with the evidence and next action. Continue
   independent checks and approved deletions when one item is blocked. Do not
   turn an unexamined item into a claim that it is unmerged or unsafe.

## Deletion Gates

### Ownership

Delete only branches whose owner segment matches the verified hosting account
ID for the target host, using Branch Strategy's identity sources, unless the
user directly authorizes an exception. Branches owned by someone else are
preserved, regardless of merge state or how abandoned they look. Branches with
no owner prefix have an unknown owner and are preserved by default. Report both
kinds when noticed.

Commit author names/emails, a shared tip, local-only status, and the absence of
an upstream do not establish branch ownership or override this gate. A generic
cleanup request does not waive it. Preserve legacy branches with an unknown
owner and report them for a separately scoped ownership/migration decision.
Honor a user's explicit instruction covering named ownerless items or overriding
this restriction; a question or approval about one subset does not narrow the
rest of an existing request. Keep other people's work and active work protected.

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
3. When no authoritative PR record exists, fall back to
   `git merge-base --is-ancestor <branch> origin/<integration>`. Judge against
   the remote integration branch because the local one may lag.

Do not rely on `git branch -d`'s own merge judgment. A squash or rebase merge is
handled by the authoritative PR result above; without that result, preserve it
unless the ancestry fallback passes or the user explicitly approves a separate
manual recovery decision.
When the user requests investigation of locally integrated work without a PR,
inspect all branch-only commits with patch equivalence and, when patches differ,
compare the candidate integration commits and affected paths. Treat matches as
evidence, not proof of safe removal: distinguish identical patches, reviewed
integration changes, and unresolved differences, and separately check active
work. An explicit user instruction may authorize a reviewed manual decision;
retain the exact branch tips for recovery. Never override an authoritative
unmerged PR with these checks.

### Worktree State

Uncommitted changes in a branch's worktree mean in-progress work. Preserve
both the worktree and the branch even when the branch tip is merged.

## Process

Keep one bounded before/after snapshot. Batch independent identity, branch,
worktree and status reads; keep removal and branch deletion sequential. Reuse
fresh evidence from the preceding lookup when targets and state are unchanged;
after an interruption, refresh deletion preconditions once, not the whole intake.
Required deletion gates still apply to every target.

1. `git fetch --prune`; classify each worktree as clean, dirty, or
   gone-directory.
2. `git worktree prune -v` to drop registrations whose directory is gone.
3. Remove clean worktrees whose branch passed all gates with
   `git worktree remove <path>`, before deleting the branch itself. Keep a
   task worktree whose finished commit is unpushed until the push. Removal of
   large build outputs can take minutes per worktree; use a generous command
   timeout. An interrupted removal leaves a half-deleted tree; if that
   happens, re-confirm the branch is merged, then finish with
   `git worktree remove --force <path>`.
4. If slow worktree removal occurred after classification, fetch once more and
   reclassify affected tips. Otherwise do not repeat an unchanged check.
5. Remote deletion, only on explicit request: show the classification table,
   then batch the approved deletes into one push. Bind every deletion to the
   fetched tip with `--force-with-lease=refs/heads/<branch>:<sha>` so a
   concurrently moved branch is refused atomically instead of requiring a
   second fetch/query/check loop.

## Recovery

Log the tip SHA of every branch before deleting it.

- Local branch: recover the SHA from the cleanup log or `git reflog`, then
  `git branch <name> <sha>`.
- Remote branch: re-push the recorded SHA.

## Do Not

- Do not commit or push content changes from a cleanup task.
- Do not delete a branch another person owns, whatever its merge state.
- Do not replace an authoritative non-merged PR result with content heuristics.
- Do not judge merge state against a local integration branch.
- Do not use `git worktree remove --force` before re-confirming the branch is
  merged.

## Stop If

- The integration branch cannot be determined, or repo-local naming policy
  conflicts with the shared format.
- Ownership cannot be determined and the user has not authorized an exception.
- An authoritative PR is not merged, the available integration evidence does
  not establish the approved manual decision, or a leased deletion reports a
  moved tip.
- A branch is still checked out, or the target is dirty, active, protected, or
  not covered by the user's ownership authorization.

## Report

After cleanup, report:

- before and after counts for worktrees, local branches, and remote branches
- every preserved item with its reason (dirty worktree, unmerged, not owned,
  protected)
- the logged SHAs of deleted branches
- any incident during cleanup (timeout interruption, concurrent tip movement);
  never hide one
- coverage of all requested item types, including which items were not yet
  investigated, and the concrete reason for every preserved item. A successful
  cleanup gate or a partial deletion is not proof the entire request is done.
