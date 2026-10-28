---
keyflow_id: sys_org_guide_layer_prd
status: review
type: ai-generated
---

# Organization Guide Layer

## Decision

Moru Core should load a company's or team's shared guidance as its own layer,
between target-repo instructions and Moru's specific and common guidance. The
layer is private, optional, bound per repository, and selected by the same
deterministic route policy that selects Moru documents today.

Delivery is phased. P0 (a reference convention) ships first and needs no code.
Each later phase is independently useful and starts only after the previous
phase's acceptance criteria pass.

Implementation: `scripts/org_binding.py` (binding and manifest checks),
`scripts/org_layer.py` (selection, budget share, search, drift),
`scripts/org_cli.py` (`workflow org add|sync|status`), with tests in
`tests/test_org_layer.py` and `tests/test_org_cli.py`.

## Problem

Moru Core must stay provider-neutral, so company rules cannot live in it.
Today a team that shares rules across repositories has three options, and each
fails:

| Current option | Failure |
| --- | --- |
| Copy rules into every repo `AGENTS.md` | Copies drift; the whole text is paid in every turn's context |
| Fork Moru Core and add company rules | Upstream updates stop; company rules risk landing in a public repo |
| Put rules in user-global runtime instructions | Personal repos inherit company rules; teammates do not get them |

Repository documents are also outside the route's search root
(`scripts/workflow_route.py` searches the Moru Core root only), so a company
design guide can never be promoted into `required_docs` for UI work.

## Actors And Outcome

- **Organization guide owner**: maintains one private guide repository and
  wants every company repo and teammate to apply the same version.
- **Developer using an agent**: wants company rules applied only in company
  repos, without pasting them or paying for them in unrelated turns.
- **Product (Moru as a team offering)**: a team or company plan needs a shared
  rule layer that does not require forking or modifying the public library.

Outcome: in a bound company repo, `start` selects the company documents the task
needs, records which version was read, and stops on a mandatory-rule conflict.
In any other repo, nothing changes.

## Current Behavior

- Precedence (AGENTS.md "Priority And Scope"): runtime instructions, current
  request, target-repo instructions, specific Moru guidance, common Moru
  guidance, README.
- P0 convention (`docs/skills/agent-runtime-integration/references/organization-guides.md`):
  a repo references the org guide from its `AGENTS.md`;
  the referenced guide counts as target-repo instructions.
- Before this layer, route search, Wikimap indexing, the required-doc budget,
  and `source docs` evidence covered Moru Core documents only.

## Proposed Behavior

### Precedence

runtime instructions > current request > target repo > **organization layer**
> specific Moru > common Moru > README.

- The repo may narrow or override organization guidance.
- Items the organization marks `enforce` (security, data, deployment, cost,
  verification) are not overridden: a repo conflict stops the run and is
  reported.
- An organization conflict with Moru on those same concerns also stops.

### Guide Repository Shape

```text
<org-guides>/
  org.json                    # id, match patterns, enforce list, schema version
  AGENTS.md                   # compact organization entry
  skills/<skill>/SKILL.md
  skills/<skill>/references/current-guidance.md
  workflow-doc-surfaces.json  # same schema as Moru's; org documents only
```

Org skills use the Moru bundle shape and frontmatter so the existing
frontmatter and link validators can check them.

### Binding

- User-local `~/.moru/orgs.json` maps Git remote patterns (for example
  `github.com/acme/*`) to a local guide checkout.
- `start` resolves the target repo's remote and selects at most one
  organization. No match loads nothing.
- A repo may pin an organization and commit in a tracked `.moru-org.json` at
  its root (`.moru/` itself is ignored run state). A pin wins over pattern
  matching. A pinned commit must equal the guide checkout's HEAD exactly.
- The guide checkout must be clean. Rules are read only from a committed
  state, so the recorded commit describes exactly what was read.

### Routing (P1)

- Org documents are selected with the guide's own `workflow-doc-surfaces.json`
  and the same matcher as Moru's. They live in a separate `route.organization`
  block, not in `required_docs`: every consumer of that list resolves paths
  under the Moru rules root. Org documents are shown as `org:<id>/<path>`.
- The org entry (`AGENTS.md`) and every `enforce` document are always
  required. Surface matches follow within an org share (12 KB, 3 documents).
- The org documents' bytes and slots are paid before Moru's optional tiers,
  because the organization ranks above Moru. Moru's core, command, and owner
  contracts stay outside the budget as before, and the existing soft budget
  (the document that crosses it is admitted) is unchanged.
- `start` prints the org documents as absolute paths and the enforce stop
  rule. The route fingerprint includes the org id, commit, and document
  digests. Nothing is appended to an always-loaded file, so unbound repos pay
  no per-turn cost.

### Search (P2)

- The org checkout gets its own local Wikimap index, excluded through the
  checkout's `.git/info/exclude` so indexing never reads as a guide change.
  The refresh receipt is kept in the project's run state.
- An `analysis` route lists org search results as
  `organization.search_candidates`; `workflow query --project <repo>` prints
  them labeled `org:<id>/...`. Both remain candidates.

### Evidence

- The route manifest records each org document and the guide's `org.json`
  and surfaces file with their digests and the guide commit.
- `finish` fails when the guide HEAD moved, the checkout gained uncommitted
  changes, or a recorded document changed, comparing against the checkout
  recorded at start rather than re-resolving the binding. This check runs on
  every route, not only routes with a `source docs` gate.

### Distribution (P3)

- `workflow org add --id <id> [--remote <url>] [--root <path>] --match <pattern>`
  clones (or registers an existing) guide checkout, validates its manifest,
  and writes `~/.moru/orgs.json`.
- `workflow org sync [--id <id>]` fetches and fast-forwards; it refuses a
  modified checkout and leaves the checkout unchanged when offline.
- `workflow org status [--project <repo>]` lists guides and a repo's binding.
- Sync runs only on request; `start` stays offline.
- VibeGuard is not extended. Its rule library only quotes titles and excerpts
  from one `--rules` root and enforces nothing from them, and pointing that
  root at a guide would replace Moru's own rule source. Conflict handling stays
  the agent's detect-and-stop contract above.

## In Scope

- P0 reference convention (shipped with this PRD).
- P1 binding, precedence and conflict rules, route merge, evidence.
- P2 org search index.
- P3 install, sync, and status commands.

## Out Of Scope

- Hosting, accounts, license keys, billing, or a server-side guide registry.
- More than one organization per repository.
- Editing or validating the organization's content policy.
- Changing how target-repo instructions are loaded.
- A VibeGuard rule source for organization guides (see P3).
- Same-session reuse of org document readings; every run lists them as unread.

## States

| State | Behavior |
| --- | --- |
| No `orgs.json` or no matching pattern | Current behavior; no org fields in output |
| Match, checkout present | Org entry and selected docs in the route manifest |
| Match, checkout missing or unreadable | `missing` lists the org root; run stops like a missing required doc |
| Repo pin set, commit is not the checkout HEAD | Stop with the pinned id and commit; never fall back to another commit |
| Guide checkout has uncommitted changes | Stop; rules are read only from a committed state |
| Several patterns match | Stop and report the candidates; never pick silently |
| `org.json` invalid or unknown schema version | Stop and report the file; no partial load |
| Repo conflicts with an `enforce` item | Stop and report both sources |
| Org conflicts with Moru on a protected concern | Stop and report both sources |
| Org doc changed after it was read | `finish` fails on freshness, like a changed Moru doc |
| Offline | Use the local checkout; P3 sync reports it could not update |

## Data, Privacy, And External Surfaces

- Org content stays in the local checkout. It is never written to Moru Core,
  public repos, Spill or settings sync, project memory, continuation packets,
  or mailbox messages.
- Route manifests and evidence store org paths and commit SHAs, not content.
- Sync uses the user's existing Git access. No new credential storage.
- No paid service, model call, or server is added.

## Acceptance Criteria

P1:

1. Given no `~/.moru/orgs.json`, when `start` runs in any repo, then the route
   manifest equals the current output.
2. Given `orgs.json` maps `github.com/acme/*` to a valid checkout and the repo
   remote is `github.com/acme/web`, when a UI task starts, then the org
   design-system document selected by org `workflow-doc-surfaces.json` appears
   in `organization.required_docs` with its digest and the guide commit, and
   `start` shows it as `org:acme/...` with its absolute path.
3. Given the same mapping and a repo whose remote is `github.com/me/side`, when
   `start` runs, then no org document or org entry appears.
4. Given `.moru-org.json` pins a commit that is not the checkout HEAD, when
   `start` runs, then the run stops naming the org id and commit.
5. Given two patterns match the remote, when `start` runs, then the run stops
   listing both candidates.
6. Given an org `enforce` item and a repo instruction that contradicts it, when
   the agent detects the conflict, then the documented stop condition applies
   and the agent reports both sources.
7. Given an org document read in a run changes before `finish`, when `finish`
   runs, then it fails on freshness.
8. Given Moru and org documents both qualify, when the route is built, then
   the org documents' bytes and slots are charged to the existing budget and
   cap before Moru's optional tiers, Moru's mandatory contracts are not
   displaced, and an unbound route selects exactly what it did before.

P2:

9. Given a bound repo, when `workflow query` matches text in the org guide,
   then the result is labeled with the org id and remains a candidate.

P3:

10. Given a guide remote, when the sync command runs offline, then it reports
    that the update failed and leaves the existing checkout unchanged.

## Open Decisions

- Product packaging: whether the organization layer is part of the free
  library or a team offering, and how that is licensed. Blocks public
  positioning only.
- Whether `enforce` should cover concerns beyond the five protected concerns
  (implemented: the five only).
- Whether the repo pin file is required for company repos (implemented:
  optional).
- Sync at `start` (implemented: only on request).
- Whether org documents should join same-session reading reuse.

## Verification Signals

- Route fixture tests for every row in States, including the unchanged
  manifest for unbound repos.
- Budget test with Moru and org documents competing for `required_docs`.
- Finish freshness test for a changed org document.
- Privacy test: no org content in evidence, checkpoints, or mailbox files.

## Design Review

Reviewed with Codex before implementation. Adopted: a separate route block
rather than mixing `org:` paths into `required_docs`; org-first budget
charging without displacing Moru's mandatory contracts; an exact HEAD pin with
a clean checkout; dropping the VibeGuard source; drift checked against the
start-time checkout on every route; a run-state receipt for the guide index.

## Next Route

Commit and publish when authorized; then the open decisions above.
