---
keyflow_id: sys_web_deployment_versioning
status: stable
type: human-reviewed-needed
moru_card_contract: strict
---

# Web Deployment Versioning

Use when choosing, documenting, reviewing, or automating version, release, build,
deployment, rollback, or changelog policy for a web app, website, frontend,
server-rendered web surface, or static site.

## Use When

- A web app deploys often from `main`, trunk, merge queue, preview builds, or
  CI/CD automation.
- A team needs to decide whether every web deployment should bump the public
  version.
- A web release needs history, rollback, support triage, changelog, cache
  invalidation, or observability correlation.
- A repo-local release guide mentions web deploy ids, release notes, tags,
  build metadata, or version display.

Use `common/skills/release-versioning/SKILL.md` first for the general scheme. This card
adds the web-specific rule: every production deploy must be traceable, but not
every deploy needs a user-facing release version.

## Inspect First

- Existing repo-local release docs, changelog, tags, deployment platform, CI
  workflow, merge queue, and rollback guide.
- Whether production deploys happen on every merge, on a schedule, manually, or
  through release branches.
- Where the running web app exposes provenance: deployment dashboard, logs,
  health endpoint, support panel, build metadata, source map release, or
  monitoring release id.
- Whether the repo has cache, service worker, CDN, browser storage, API
  compatibility, or migration behavior that needs a schema or compatibility
  version separate from release notes.
- Whether the web artifact is also a package, SDK, plugin, generated client, or
  public API contract. Those may still need SemVer.

## Decision Rule

Separate these identifiers instead of forcing one number to do every job:

| Identifier | Required For | Bump Rule |
| --- | --- | --- |
| Source revision | every build and deploy | Git commit or immutable source ref |
| Build or artifact id | every built artifact | CI run id, artifact digest, or deploy platform id |
| Deployment id | every environment deployment | one id per production/staging deploy |
| Public release version | user-facing release notes, support, product history | only when grouping meaningful shipped changes |
| Compatibility or schema version | cache, service worker, browser storage, API contract | only when compatibility behavior changes |

For continuous web deployment, prefer:

```text
public release version: optional release train, using YY.WW.N for app/date-based releases
deployment id: every production deploy, such as <timestamp>-<short-sha> or provider deploy id
source revision: exact commit SHA
```

Do not bump the public release version on every main merge unless the project
actually communicates, supports, rolls back, and reports every merge as a
separate product release.

## Process

1. Choose the release unit: continuous deploy, daily train, weekly train,
   monthly release, manual release, or package publication.
2. Choose the public version scheme only for the release unit. Use SemVer for
   compatibility-sensitive packages or APIs; use weekly CalVer `YY.WW.N` for
   app display versions and date-oriented product release tags. Preserve legacy
   monthly versions only as historical records under the canonical migration
   rules.
3. Require an immutable deployment id for every environment deployment,
   regardless of whether the public release version changes.
4. Tie the deployment id to source revision, build artifact, environment,
   deployed-at timestamp, deploy actor/automation, and rollback target.
5. Expose provenance where operators can inspect it. A user-visible footer is
   optional; a support/debug endpoint, monitoring release id, deployment
   dashboard, or build metadata is usually enough.
6. Record changelog or release notes only for the public release version. Link
   the deployment ids included in that release train when the repo supports it.
7. Keep cache, service-worker, browser-storage, API, and feature-flag schema
   versions separate from the public release version.
8. Document the repo-local contract: version scheme, deploy id format, country
   calendar and timezone, reset rule, tag policy, metadata location, rollback
   lookup, and release-note rule. Weekly CalVer follows the configured country's
   week rules and starts the release count at `0`; pin the same settings in
   local tools and CI according to the release versioning card.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "Main deploys every time, so every merge needs SemVer." | Track every deploy with a deployment id; reserve SemVer or CalVer for meaningful release units. |
| "Web has no versions because it is always latest." | Require source revision, build id, and deployment id for rollback and support history. |
| "The hosting provider already has deploy history." | Document the provider id and how it maps to source revision, artifact, environment, and rollback. |
| "package.json version is enough." | Verify that the deployed artifact, monitoring, support, and release notes actually use that value. |
| "This was only a config or flag change." | It still needs deployment provenance if it reached an environment. |

## Red Flags

- `latest`, `production`, or a mutable branch name is the only deploy identity.
- A public release tag moves after deployment.
- The deployed site cannot answer which source revision is running.
- Release notes mention a version that does not map to deploy ids or commits.
- Service worker, cache, local storage, or API compatibility changes are tied
  only to a marketing version.
- Rollback requires guessing from CI history or chat messages.
- Preview, staging, and production use incompatible version formats.

## Do Not

- Do not use public SemVer as the only deployment id for high-frequency web
  deploys.
- Do not hide every production deploy behind one evergreen "web version".
- Do not move old release tags to newer commits after deployment.
- Do not count failed builds or failed deploy attempts as released versions;
  keep their attempt identifiers separate from the weekly release count.
- Do not use four-digit years such as `2026.27.1` for CalVer release tags; use
  `26.27.0` or `v26.27.0`, and start the weekly release count at `.0`.
- Do not expose secrets, internal paths, branch names, account names, or private
  operator notes in public version metadata.
- Do not make a shared Moru Core card define one vendor's deployment
  workflow; keep provider-specific setup in repo-local docs.

## Stop If

- The team has not chosen whether the release unit is deploy, daily/weekly
  train, monthly train, manual release, or package publication.
- The artifact id, deployment id, and public release version are being treated
  as the same thing but the platform distinguishes them.
- The version would collide with an existing tag, release note, artifact, or
  deployment record.
- A weekly public release version uses a four-digit year, substitutes a month
  for the configured week, has a negative deployment count, or skips `.0` for
  the first release of a week.
- Rollback or support lookup cannot map a running site to source revision and
  artifact.
- A cache, service worker, browser storage, API, or migration change needs a
  compatibility version that is not defined.

## Verification

For a web versioning policy or automation change, verify:

- an empty week's first published version is `.0`, subsequent deployments
  increment the highest published count, and the next week resets to `.0`
- route/concern loading includes this card for release or shipping work
- repo-local release docs define release unit, public version scheme, deploy id
  format, timezone, metadata location, rollback lookup, and release-note rule
- a deployed artifact or dry-run artifact can be traced to source revision,
  build/artifact id, environment, and deployed-at timestamp
- monitoring, source-map upload, support diagnostics, health endpoint, or
  deployment dashboard can identify the running revision
- changelog/release notes map to public release versions, not every deploy,
  unless the repo explicitly chose deploy-per-release

For Moru Core changes, run `python3 scripts/workflow.py validate`, the
nearest routing tests, and `git diff --check`.

## Report

Report:

- selected release unit and why
- public version scheme, if any
- deployment id source and format
- where source revision and artifact provenance are visible
- cache/schema/API compatibility version decision
- release-note and rollback lookup rule
- verification commands or manual deployment metadata checks run
