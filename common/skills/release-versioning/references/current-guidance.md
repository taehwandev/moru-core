---
keyflow_id: sys_release_versioning
status: stable
type: human-reviewed-needed
---

# Release Versioning

Use when choosing, changing, reviewing, tagging, or documenting a release,
deployment, package, app, build, or artifact version.

## Default

Versioning is an artifact-local contract. Document the scheme for each released
artifact in the repo-local release instructions and keep it stable. App display
versions and date-based release versions use the weekly contract below;
compatibility-sensitive packages keep their separate SemVer contract.

The shared default is:

- Use SemVer for libraries, SDKs, APIs, plugins, generated clients, and packages
  where compatibility expectations matter.
- Use weekly CalVer `YY.WW.N` for app display versions, date-based release tags
  and operational artifacts: two-digit year, country-configured week, and a
  release count that starts at `0` for each week.
- Treat existing monthly or one-based date versions as legacy contracts. Migrate
  them with release owner approval and a migration note; do not recommend them
  for new app or date-based release versions.

## Supported Schemes

### SemVer

Use `MAJOR.MINOR.PATCH` when consumers need compatibility signals.

```text
2.4.7
2.5.0-rc.1
```

- Increment `MAJOR` for breaking changes.
- Increment `MINOR` for backward-compatible features.
- Increment `PATCH` for backward-compatible fixes.
- Keep compatibility-sensitive package and dependency versions in SemVer.
  If platform tooling constrains an app's version fields, document a compatible
  representation or separate monotonic build number while keeping the app
  display version in `YY.WW.N`.

### Legacy Date-Based Versions

Existing `YY.MM.N` versions or date-based counts starting at `1` must not be
silently reinterpreted as weekly versions. Preserve published versions and
tags. Before changing the scheme, document the transition, version ordering and
update-client behavior, and obtain release owner approval. New app and
date-based release contracts use `YY.WW.N` with the first weekly deployment at
`.0`.

### Weekly CalVer

Use `YY.WW.N` for app display versions and date-based release tags.

```text
26.21.0
26.21.1
26.22.0
```

- `YY` is the two-digit week-year from the configured calendar, including its
  year-boundary rule. Do not use `YYYY.WW.N`, `YYYY.MM.N`, or any four-digit
  calendar year in a release tag.
- `WW` is the two-digit week number from the release owner's configured country
  or region. Use that calendar's first weekday and minimum days in the first
  week; do not force ISO weeks or a Monday start. Week numbering follows the
  selected calendar and is not shifted to zero-based numbering.
- `N` starts at `0` each week and increments for each released artifact or
  production deployment, as defined by the repo.
- If the current week has no published version, choose `N = 0`. Otherwise,
  choose one more than the highest published `N` for that week. Do not initialize
  an empty week's count to `1`; a new week starts again at `.0`.
- `N` should not be zero-padded unless the
  repo-local release contract explicitly requires padding.
- Use the timezone configured for the release owner together with the country
  calendar. Document both explicitly; a country can have multiple timezones.
- Pin the same region, calendar, week rules, and timezone in local tools and CI.
  Do not use a runner's default locale or timezone as the release policy.
  If the settings are unavailable or conflict, resolve them before calculating
  the version rather than silently falling back to UTC or ISO weeks.

## Required Repo-Local Contract

Every repo that uses calendar or custom versioning must document:

- scheme name: `semver` or `calver-weekly`; identify legacy/custom formats and
  any app platform representation separately
- pattern and examples
- country/region, calendar source, first weekday, minimum days in the first
  week, week-year boundary rule, and timezone for weekly versions; timezone
  and calendar source for other date-based versions
- whether `N` counts published artifacts or successful production deployments;
  attempt identifiers are separate
- reset rule for `N`
- tag prefix, such as `v26.21.0`, and whether package metadata omits `v`
- prerelease format, such as `26.21.0-rc.1`
- build metadata or monotonic build number when stores or platforms require it

## Rules

- Do not mix `YY.MM.N` and `YY.WW.N` for the same artifact.
- Do not use four-digit years for date-based release tags. `2026.27.1` and
  `v2026.27.1` are wrong when the scheme is CalVer; use `26.27.1` or
  `v26.27.1`.
- The first released artifact for a week is `.0`; the next is `.1`. The next
  week resets to `.0`. Failed builds, failed deployments and unpublished
  artifacts do not advance this count.
- Do not switch schemes without a migration note and release owner approval.
- Do not infer month versus week from shape alone; read the repo-local contract.
- Use the release owner's configured country calendar and timezone for weekly
  versions. Do not assume UTC, PST, or Monday as a shared default.
- A settings or format change needs a migration note covering existing tags,
  version ordering, and update clients. Never renumber published versions or
  overwrite a tag to adopt the new defaults.
- Decide whether the date comes from release cut, artifact publication, or
  production deployment, and keep that rule stable.
- Count only published artifacts or successful deployments. Keep failed-build
  and deployment-attempt identifiers separate from the weekly release count.
- Keep package version, tag, artifact name, release notes, and deployment record
  consistent.
- If a SemVer-only tool rejects zero-padded date fields, document a compatible
  platform representation while keeping the app display version in `YY.WW.N`.

## Tag-Time Guards

When the repo tracks the build version in a version file or manifest, that
tracked file is the single source of truth. A release tag records a release
point; it never changes the build version. Run these guards, in order, before
creating a release tag, and block the tag when any guard fails:

1. Validate the tag against the scheme's strict format regex before any other
   check; this catches truncated or over-long versions such as `v3.1` or
   `3.1.0.0`.
2. Refuse computed bump arguments (`major`/`minor`/`patch`) at tag time.
   Version bumps happen only as a reviewed file-change commit before tagging;
   require the explicit version the tracked version source already carries.
3. Block the tag unless the tag version equals the tracked version at the
   target commit.
4. Monotonic guard: the new version must sort strictly above the latest
   existing tag under the scheme's ordering. Equal or lower is blocked to
   prevent version regressions in stores, package registries, and clients.

## Examples

Use weekly CalVer:

```text
scheme: calver-weekly
pattern: YY.WW.N
country/region: explicitly configured by the release owner
calendar: configured country calendar, including week-year rules
first weekday: from the configured calendar
minimum days in first week: from the configured calendar
timezone: explicitly configured IANA timezone
release count: starts at 0 each week
release unit: weekly release train artifact
example: v26.21.0
```

Use SemVer:

```text
scheme: semver
pattern: MAJOR.MINOR.PATCH
release unit: published package
example: v2.4.7
```

## Stop If

- The artifact, package, app display version, build number, tag, and deployment
  id are being treated as the same thing but the platform distinguishes them.
- A date-based release tag uses a four-digit year, an unspecified week/month
  basis, a negative weekly release count, or skips `.0` for the first release
  of a week.
- The country calendar, week rules, or timezone for a weekly version is missing
  or differs between local tools and CI.
- The repo already uses a different scheme and no migration approval exists.
- The version would collide with an existing tag, artifact, package, or
  deployment record.
- Tooling rejects the chosen version format.
