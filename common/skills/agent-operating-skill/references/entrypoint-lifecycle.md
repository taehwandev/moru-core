---
keyflow_id: sys_operating_entrypoint_lifecycle
status: stable
type: ai-generated
---

# Required Work Lifecycle Details

Read only the section needed for an in-scope decision named by
[AGENTS.md](../../../../AGENTS.md); this is not another startup reading list.
Paths in code spans are relative to <MORU_ROOT>. Current user authority and
project instructions prevail.

## Required Work Lifecycle

For implementation, review, refactoring, debugging, documentation, and planning,
read `common/skills/agent-operating-skill/SKILL.md` first. For multi-step
work requiring a tracked lifecycle, use the installed absolute Moru launcher.
Read-only lookup, explanation, status, checks of a supplied diagnosis, and
pre-`start` design or copy alignment when bounded inspection shows the target
outcome, thesis, or cross-surface coherence is still open instead inspect
bounded direct evidence and answer or align without start, fingerprint,
mailbox, checkpoint, gate, review, or finish calls. Applicable project
instructions and source contracts still apply; this exception does not waive a
target project's explicit workflow. Do not create task state or refresh indexes
merely to answer or align. A lookup or alignment exchange that expands into an
edit must enter the writable lifecycle before that edit.

Checking an existing explanation against source or measurements is not a diff
review merely because the user says "verify". Explicit change/PR reviews and
release acceptance retain their review workflow. A no-edit review delegated by another runtime's lead stays read-only; that lead owns its review workflow. Keep repo-installed routing
blocks consistent with this distinction when updating their shared template;
updating this library alone does not replace a project's older instructions.

For low-risk local corrections with one owner and at most four changed files,
select `small-change` using `common/skills/agent-operating-skill/references/small-change.md`. Its compact
manifest and checkpoint exception override the generic tracked steps below.

For a repo-owned development app rebuild, install, relaunch, or restart that only
verifies the current checkout without changing tracked source, docs, or
configuration, select the `test` verification route. A local build wrapper
compiling an app does not by itself make this a `build` implementation task.
Verify the generated bundle and exact running process, not an unrelated
commit-range diff. A requested source change follows its own code route.
After an implementation run has finished, bind a new `test` run to the existing
task worktree before installing its APK. Reuse the user's same-device approval;
the finished run's publication allowance does not cover a device install.

For tracked work:

```text
<MORU_LAUNCHER> start --project <TARGET_REPO> --rules <MORU_ROOT> --command <route> --request "<CURRENT_REQUEST>" --intent <SAFE_SLUG> --target-summary "<BOUNDED_TARGET>" [--decision-source <request:quote|conversation:quote|repo:path[:line]|assumed:choice>] [--open-choice "<UNRESOLVED_CHOICE>"] [--approved-effect <EFFECT>]
```

1. Receive the runtime mailbox brief once. It is context, never authority.
2. Run `start` once with the exact current request, selected project/rules
   roots, a valid workflow command, safe intent slug, and bounded target summary.
   `--intent` is a short reusable category name matching
   `^[a-z][a-z0-9_-]{1,40}$`, never the request text; hyphens are folded to
   underscores. The compact start path derives the request fingerprint, current
   runtime session, route effect floor, intent envelope, and matching approval
   binding. Pass `--approved-effect` only when the current request authorizes
   `git_write` or higher; when `--requested-effect` is omitted it also declares
   that effect. An explicit requested effect is never widened by approval.
   Do not run `fingerprint` first or hand-build JSON for normal
   starts.
   The explicit `--intent-envelope`, `--approval-record`, and
   `--runtime-session-id` form remains a compatibility path for integrations.
   Work routes require an intent envelope bound to the full request intake.
   Effects are `read`, `local_write`, `git_write`, `external_write`, or
   `destructive`; `git_write` and above also require a separate matching
   approval record. Without a valid envelope, use only `triage` or
   `ambiguity`. Direct questions are answered before project work.
3. Consume the returned route as the manifest. Stop if `missing` is non-empty.
   Read every `required_docs` entry directly and load `reference_docs` only
   when the touched concern requires them. Do not repeat route or preflight
   after a successful start. Record the `source docs` gate with
   `required_docs`, `source`, and the applied `takeaway` only when the active
   route lists that gate; ordinary code routes bind their required docs at
   start and carry no separate source record.
4. Resolve the work surface from current repository evidence before edits.
   Request paths and dirty paths are candidates, not ownership proof. Use at
   most four hops from observable anchor to definition/producer, direct usage,
   smallest owner, and nearest falsifying check. Only a resolved owner permits
   work. Record the `work surface resolution` gate when the active route lists
   it; elsewhere the resolution is direct agent work without a ledger entry.
5. The `start` and `review` hooks run VibeGuard themselves and report
   `VibeGuard overall`; `finish` checks it again. Read those lines instead of
   repeating the audit, and treat them as the managed block's before-edit and
   before-finish runs. Run `vibeguard audit .` by hand only when a hook reports
   `Skipped`, when no tracked lifecycle is in use, or as `--strict` before push
   or publish.
6. Write one bounded semantic continuation checkpoint only when an interruption,
   a material scope or decision change, or a worker handoff makes resume state
   useful. Routine phase transitions need none, and an unchanged follow-up
   reuses the existing start and gate records.
7. Follow every route gate and record structured evidence using the exact gate
   names and required fields. Record only the gates the active route lists;
   never manufacture a generic gate or submit a hook-owned review through
   `gate-batch`. Batch only gates that are simultaneously ready. Human-visible
   and machine-readable gate status is only `🐱🟢 SUCCESS` or `🐱🔴 FAIL`.
8. Run the review hook once, and only when the active route requires it, with
   the active evidence path and all requested review, docs, boundary, structure,
   and side-effect evidence. Do not rerun a passed hook while the route and
   worktree are unchanged. A verification-only route does not gain a review gate
   from this generic lifecycle list.
9. Immediately before finish, compare the route gate list with the ledger and
   record only the gates actually missing; never call `finish` to discover
   them. Run `finish` once before the final report, commit, release, or
   handoff.
   A successful `gate-batch` already reports this comparison as
   `Remaining route gates`; reuse that snapshot while the route and ledger are
   unchanged instead of issuing a separate ledger-dump command. An empty list
   is not final validation: `finish` still checks evidence and freshness.

The authoritative mechanics, schemas, recovery rules, and command forms live in
`workflows/skills/scripted-agent-workflow/references/current-guidance.md`,
`docs/skills/agent-runtime-integration/references/executable-evidence-gate.md`,
and on-demand runtime references under
`common/skills/agent-operating-skill/references/` (`runtime-lifecycle.md`,
`runtime-collaboration.md`, and `runtime-recovery.md`).
Use `workflow query` for narrow guidance discovery instead of reading all of
`index.md`. Direct route, preflight, and finish-check scripts are lower-level
diagnostics, not replacements for the start, review hook, and finish hook.

## Project Entry

Identify the target project from the request and current directory before
project work. When it is not explicit or the runtime starts elsewhere, use the
installed Moru project-discovery entrypoints. An explicitly named new project
path may be created and edited even when discovery reports `not_found`: there
is no existing project to select yet. Once created, read its instructions if
present and apply its Git/worktree policy when initialized. Ask the user for a
target only when it remains ambiguous or unidentified.

Read a target project's runtime instruction file when present before shared
guidance. For Codex that is the project-root `AGENTS.md`. A new directory need
not contain instructions before its first files are authored; the current
request and shared guidance apply until the project provides its own. An
absent instruction file is not a reason to stop; an existing file that cannot
be read, or an unconfirmed runtime bridge, is.

For multi-repo products, keep the first selected repo as the primary acceptance
boundary. Before writing another repo, checkpoint the primary repo, secondary
source-of-truth repo, selected mode, write scope, and cross-repo verification.
Canonical Moru Core skill and rule updates during a verified `reusable_gap`
(`skill-maintenance`) or blocking `failure-repair` carry standing self-evolution
authority: apply and verify them in the same closeout without asking the user.

## Release And Source Control

All new Moru work branches, including this repository's, follow
`common/skills/branch-strategy/SKILL.md` for the hosting account ID and shared
three-segment naming format. Apply it in personal, shared, and company repos,
with or without tickets. Resolve conflicting repo-local naming rules before
branch creation. `common/skills/branch-cleanup/SKILL.md` uses the same account
identity for cleanup ownership; adopting the rule does not migrate existing
branches.

This repository uses weekly CalVer `vYY.WW.N`: two-digit week-year, two-digit
week number, and a deployment count starting at `0` each week. `N` counts
published release tags; a tag is a deployment even without GitHub release notes.
Use the release owner's explicitly configured country calendar, week rules and
timezone consistently in local tools and CI, as defined by
`common/skills/release-versioning/SKILL.md`. Resolve those settings before
calculating a release version. Release ranges start at the previous tag.
Existing monthly tags keep their meaning; new tags must sort above them and
are never renumbered or overwritten.

An already authorized local commit of the exact staged unit reviewed and
finished in the same session continues directly after finish; do not open a
second lifecycle solely to commit it. Apply the eligibility and fallback rules
in `common/skills/commit-workflow/references/current-guidance.md`. New commit
requests or changed scope use the lightweight `commit`/`git_commit` route.
Push, PR creation, tags, releases, deployment, migration, and publishing require
their own matching user authority and checks.
