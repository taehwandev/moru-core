---
keyflow_id: sys_ci_cd_automation
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# CI/CD And Automation

Use when creating, changing, reviewing, or debugging CI pipelines, release
automation, scheduled jobs, build matrices, checks, deployment automation,
package publishing, or repository workflow files.

The goal is deterministic automation that protects the product without hiding
release, credential, cost, or environment risk.

## Use When

- A task changes workflow files, release scripts, package publishing, deploy
  steps, scheduled automation, build matrices, or check requirements.
- A local command must match CI behavior.
- A release or merge gate depends on automation evidence.
- CI failures need triage before code changes.

For ordinary local tests, use `common/skills/testing/SKILL.md` and
`common/skills/verification-policy/SKILL.md`.

## Inspect First

- Existing CI workflow files, repo scripts, package manager, lockfiles, and
  tool versions.
- Required secrets, permissions, environments, caches, artifacts, and runners.
- Branch, tag, release, pull request, and schedule triggers.
- Existing release, deployment, and generated-file policy.

## Decision Rule

Automation should be the smallest repeatable gate that proves the risk it
guards. Separate build, test, package, publish, and deploy steps so failures are
diagnosable and rollback is realistic.

## Process

1. Identify the event that triggers automation and the artifact or decision it
   produces.
2. Map secrets, permissions, network access, cache writes, artifacts, and cost.
3. Reuse repo scripts where possible; avoid duplicating command logic in CI.
4. Add deterministic versions, caches, and timeouts only when the repo supports
   them.
5. Keep deploy or publish behind explicit environments, protected branches,
   tags, approvals, or dry runs as appropriate.
6. Verify locally when possible and with CI evidence when the runtime requires
   the real runner.

## Scheduled Documentation Generation

When automation generates or refreshes documentation, wiki pages, search
indexes, API references, screenshots, or other derived docs, treat the job like a
build pipeline:

- Name the source revision, generator version, input scope, output location, and
  publication target.
- Keep generation, validation, and publication as separate phases so a bad
  output cannot silently replace the last good artifact.
- Use atomic publish or revisioned output when readers consume the generated
  docs.
- Validate citations, source paths, links, navigation, excluded files, and
  freshness metadata before publication.
- Apply rate limits, retry cooldowns, queue limits, and cost controls for
  scheduled or on-demand generation.
- Report stale-generation and failed-generation states where maintainers can act
  on them.

Do not add recurring model calls, scheduled repository scans, public repository
creation, or private-source indexing without explicit approval and a documented
permission boundary.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "It works locally, so CI is fine." | Check runner OS, secrets, cache, working directory, and installed versions. |
| "CI will catch it." | Add the correct local or focused check before relying on broad CI. |
| "One workflow can do everything." | Split stages enough that test, package, publish, and deploy failures are clear. |
| "The token is already configured." | Verify permissions and never print or commit secret values. |

## Red Flags

- CI duplicates commands that already exist in repo scripts.
- A deployment or publish job runs on every branch or pull request.
- A job needs broad permissions without explanation.
- Cache keys can restore incompatible dependencies or generated artifacts.
- A check passes without exercising the artifact that will ship.

## Do Not

- Do not add network, package publish, deploy, or credential-changing behavior
  without explicit approval and repo-local policy.
- Do not make CI green by weakening tests, hiding failures, or ignoring exit
  codes.
- Do not store secrets in workflow files, logs, cache keys, artifacts, or test
  fixtures.
- Do not use CI as a substitute for local source, package, and command
  discovery.
- Do not add recurring paid or long-running automation without cost awareness.

## Stop If

- Required secrets, environments, publish targets, or permissions are unclear.
- The workflow can deploy, publish, migrate, or mutate external state without an
  approval gate.
- The runner cannot reproduce the repo's documented build or test command.
- The change may increase paid usage and the user has not approved it.

## Verification

Use local command parity checks, workflow syntax validation, dry runs,
repository check results, artifact inspection, and release smoke checks. For
deployment or publish automation, verify rollback or forward-fix evidence.

## Report

Report the changed trigger, guarded risk, commands or CI checks run, secret or
permission assumptions, artifact evidence, and residual risk when real CI could
not be executed locally.
