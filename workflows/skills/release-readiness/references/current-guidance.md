---
keyflow_id: sys_release_readiness_workflow
status: stable
type: human-reviewed-needed
---

# Release Readiness Workflow

Use before packaging, deploying, publishing, tagging, migration rollout,
signing, or handing off release-sensitive work.

## Reading Scope

Use the route's `required_docs` and explicit `requires_docs` dependencies as
the mandatory reading manifest. Reuse complete, unchanged readings already
retained in the living session. The references below are decision aids, not a
second startup manifest or a recursive queue of cards and their references:

- Deployment and versioning contracts selected by the route remain required.
- Read the commit and worktree contracts before source-control changes when
  their applicable guidance is not already retained.
- Open CI/CD, dependency, compatibility, generated-file, runtime-URL, security,
  verification, or platform guidance only for a concrete unresolved decision
  or a changed risk owned by that contract. Follow any explicit required
  dependency it declares; do not browse `index.md` after successful routing.

For an existing pipeline with unchanged security and packaging policy, inspect
its repo-owned release checklist, configuration, commands and artifact inputs.
Creating another local candidate does not by itself require rereading every
general verification, security and generated-file card. This bounds reading
only: signing, secret, authority, isolation, rollback and post-release checks
below still apply.

## Steps

1. Identify artifact, source revision, version scheme, target environment,
   release owner, and rollback or forward-fix path.
2. Inspect final diff for secrets, local config, generated files, migrations,
   dependency churn, and contract changes.
3. Reuse valid verification as below; run missing or invalidated build, package,
   migration, signing, or smoke checks.
4. Verify tag, version, source revision, and artifact provenance match when tags
   are part of the release process.
5. Verify environment config, secret injection, callback URLs, app ids, domains,
   and package identity when relevant.
6. Record user-visible changes, breaking changes, security impact, operator
   action, and known residual risk.
7. Confirm post-release smoke, logs, monitoring, or health checks can detect
   failure.
8. Confirm CI/CD gates, publish/deploy permissions, and rollback automation are
   scoped to the intended branch, tag, environment, or approval path.

## Release Orchestration Context

Keep execution proportional as well as the document manifest. Before another
check, inspect the existing runner's coverage: a verification command may
already build the release bundle and run its resource and runtime checks.
Run only the still-missing checks, and use the resulting bundle for packaging
when its source, flags, identity and provenance match. Do not rebuild merely
to advance a phase or recreate evidence that is already valid.

Use consistent literal runner and environment prefixes for required native
permissions, as specified by the runtime recovery contract. Keep one pending
request and resume its handle with bounded waits; repeated one-second polls
and gaps spent re-planning the next resolved action add no verification.
Batch independent reads within output limits, recover only missing ranges,
and record simultaneously ready gates together. Use the printed remaining
gate template after context loss rather than reconstructing it from hook
source. None of these shortcuts admits a denied command or weakens a check.

Carry one release context through commit, review, packaging, tagging and
publication: revision, version, artifact, target, verification and recovery path.
Reuse unchanged required-document readings and existing evidence; do not
reconstruct them or manually repeat hashes already checked by the hooks.

On retry, apply `common/skills/testing/references/final-check.md`: reuse observed
passes only for matching covered inputs and relevant environment. Review the
correction and its affected boundary; unchanged covered code retains its prior
review. A follow-up request or commit alone does not invalidate verification.
Reuse an unchanged retained package when its verified source, build flags,
version, toolchain and relevant environment still match. Revision changes require
rechecks only where embedded metadata, signing or provenance depend on them;
source equality alone cannot prove those inputs match. Rebuild for changed or
unverified inputs, missing/changed artifacts, or an explicit rebuild request. Conflicts,
changed dependencies/configuration, new findings or uncertain evidence require
affected checks again. Failed or pending checks never count as passing.

Keep pending source review scoped to its commit unit. Pre-existing structural
debt requires a split only when this diff grows responsibility or public owners,
or the release cannot be verified without it. Follow the commit workflow for
same-run commits and exact fast-forward review reuse; do not start another
implementation cycle solely for a publication substep.

Keep one ledger linking original and reused results. Use validated references
to prior successful document and local verification records where supported,
instead of rewriting their evidence. Reuse requires matching covered inputs;
failed, pending, changed or unverifiable records remain unsatisfied. A new run
does not inherit all gates: current authorization, mutable remote checks and
the required review still apply. If documentation is unchanged, retain the
checked source and reason, not a bare unchanged assertion or a new wording
crafted only to pass validation.

Use the shared work-continuity contract in `AGENTS.md` for every authorized
follow-up action. `start --continue-from <previous run id>` preserves work
identity; `--reuse-inputs` permits automatic carry of eligible local records
whose captured dependencies still match. Do not reconstruct a release-only
reuse checklist. Existing `reuse_from` gate references remain compatible, but
are not the normal continuation path. Unknown toolchains, changed artifacts,
revision-sensitive packaging, or unverified external inputs require affected
checks. A local pass on a different compiler never proves the CI repair.
For unchanged documentation, retain `inspected` and `coverage` fields rather
than rewriting a narrative to satisfy a validator.

Refresh mutable remote refs, release/assets and target permissions before
publication. Check existing production authority against the next action using
the release deployment approval and recovery rules; a changed SHA alone does
not require renewed confirmation. Preparation gates establish readiness only:
planned smoke, handoff text or a successful tag push cannot establish deployment
success.
After execution, collect this attempt's CI/deployment result, artifact provenance
and required live smoke before claiming release completion. Report pending or
failed publication explicitly; never copy a prior attempt's success forward.
Local passes do not replace signing, notarization or publication checks for the
artifact newly produced by CI. A pass on a different local toolchain does not
verify a CI compiler workaround; describe it as a candidate until the affected
CI build passes. Once the exact deployment is identified, monitor
one authoritative status source at bounded intervals. Pending is not failure;
do not restart source review while waiting. Inspect bounded relevant logs on
failure, stalled progress or explicit request, rather than dumping full build logs.

## Verification

Release evidence should cover the artifact that will actually ship:

- source revision, version, tag, build number, package id, artifact name, and
  release channel agree
- build/package/sign/notarize/publish dry run or release command completed for
  the intended target
- migration, backfill, seed, generated artifact, or config change has rollback
  or forward-fix evidence
- secrets, env injection, callback URLs, app ids, domains, permissions, and
  signing material are supplied through the intended deployment mechanism
- smoke, health check, logs, metrics, crash reporting, or rollback monitor can
  detect the primary failure modes

Do not treat a local typecheck or formatter as release evidence when packaging,
deployment, signing, migration, or external configuration changed.

## Stop If

- The release artifact or target environment is unclear.
- The version scheme, reset rule, or version/tag/artifact relationship is
  unclear.
- A tag will be created, moved, pushed, or published but repo-local tag policy,
  current branch/remote, or worktree state has not been checked.
- A migration, signing, secret, or deployment change lacks a recovery path.
- Required verification cannot run and no owner has accepted the release risk.
