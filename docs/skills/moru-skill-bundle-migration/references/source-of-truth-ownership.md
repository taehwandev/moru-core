---
keyflow_id: sys_moru_source_of_truth_ownership
status: review
type: human-reviewed-needed
---

# Source-Of-Truth Ownership

Use this when restructuring Moru Core guidance, moving flat docs into skill
bundles, cleaning duplicated rules, or deciding where a topic belongs.

The goal is to prevent agents from reading several stale versions of the same
rule. A reusable rule should have one canonical owner. Other files may route to
that owner or link to it, but they should not restate the operational rule in
different words.

## Ownership Rule

Use this invariant:

```text
one reusable rule = one canonical owner
```

The canonical owner is the most specific document that can own the rule after
removing repo names, service names, product policy, local paths, commands,
accounts, vendors, and one-off examples.

### Agent-Agnostic Single Ownership

When Codex, Claude, Antigravity/AGY, or another runtime needs the same
operational knowledge, maintain that knowledge once in the most specific
provider-neutral canonical owner. Real runtime-specific adapter or
configuration files may contain only:

- discovery or registration needed for that runtime to find the owner
- invocation syntax, hooks, or permission wiring
- behavior that is genuinely unique to the runtime and cannot be expressed in
  the provider-neutral owner

Runtime files must link to or resolve to the canonical owner. They must not
carry independent copies of the shared rule, checklist, examples, or
references. A generated runtime entrypoint is an adapter, not a second source
of truth; it must identify its upstream owner and be refreshed by the owning
installer instead of edited independently.

A runtime skill directory symlink contains no runtime-owned files. Editors and
file browsers may show the canonical `SKILL.md` and `references/` below the
runtime path after following the link; those entries are views of the same
canonical files. For a committed link, verify one mode `120000` Git index entry
at the runtime path and zero tracked descendants below it. Only genuine adapter
or configuration files outside that link may own unavoidable runtime wiring.

For repo-local skills, prefer this shape:

```text
.moru/skills/<skill>/   # one canonical, commit-worthy source
.<runtime>/skills/<skill>        # repo-relative link or thin runtime adapter
```

The `.moru` directory may also contain local workflow evidence, but
that evidence is not part of the canonical skill and must remain ignored. Use
an allowlist tracking policy so `skills/<skill>/**` is portable while
preflight, gate, review, cache, and receipt files stay local.

Preferred ownership order:

1. Repo-local instructions own repo paths, commands, product policy, domain
   vocabulary, and service setup.
2. Product-pattern skills own reusable product invariants such as billing,
   invitations, permissions, or credentials patterns.
3. Platform skills own platform-specific implementation rules and verification.
4. Workflow skills own agent process, gates, evidence, review, release, and
   handoff behavior.
5. Common skills own reusable engineering rules that cross platforms.
6. `docs/skills/...` owns Moru Core maintenance, runtime integration, and
   documentation-system rules.
7. `index.md`, README summaries, and router metadata own
   discovery only; they should not own detailed operational rules.

## Placement Decision

Before moving or editing duplicated guidance, write a short ownership decision:

```text
rule/question:
canonical owner:
reason this owner is most specific:
files to link or remove:
route/index updates:
verification:
```

Use `SKILL.md` for the default entrypoint only. It may name the rule and point
to the exact reference, but the detailed rule belongs in `references/` unless it
is short enough to be required for every use of the skill.

Use a focused reference file when the guidance includes examples, checklists,
source maps, version-sensitive details, audit drills, migration steps, or
special cases. Name the file by the decision it supports, such as
`source-of-truth-ownership.md`, `route-boundaries.md`, or
`release-measurement.md`.

## Duplicate Audit

Run this drill before creating a new card or splitting an existing one:

1. Search for the rule's nouns, gate names, stop signals, and verification
   phrases across `common/`, `workflows/`, `platforms/`, `product-patterns/`,
   `docs/`, `AGENTS.md`, `index.md`, and `workflow-doc-surfaces.json`.
2. Group matches by the question they answer, not by exact wording.
3. Pick the canonical owner using the ownership order above.
4. Preserve the strongest decision rule, stop condition, and verification
   requirement in the canonical owner.
5. Replace duplicate operational prose with one of:
   - a short `Read` bullet that names the canonical owner,
   - an index or routing summary that describes discovery only,
   - deletion after routes and links target the canonical owner.
   Runtime-specific copies of an otherwise identical skill must be replaced by
   repo-relative links or thin adapters whose only content is the unavoidable
   runtime mechanic.
6. Update route surfaces, concern mappings, and tests so agents load the owner,
   not a stale compatibility path.
7. Run route smoke and validation before reporting completion.

## Compatibility Stubs

Flat `.md` compatibility stubs are temporary exceptions, not the normal
Moru Core layout. Prefer deleting them after internal routes, links, tests,
and required-document manifests target the canonical bundle.

Keep a flat stub only when a named downstream repo instruction, runtime bridge,
or external published link still requires the exact legacy path. A retained stub
must stay short and may include:

- frontmatter that marks it as a compatibility entrypoint,
- the canonical `SKILL.md` path,
- the detailed reference path,
- a verification note saying routes should load the canonical bundle.

A stub must not include copied checklists, stop conditions, examples, or source
coverage. If the stub needs those details to be useful, the canonical bundle is
not wired clearly enough. If no named compatibility dependency remains, remove
the stub instead of keeping a second retrieval target.

## Router And Index Summaries

`index.md`, workflow concern maps, and `workflow-doc-surfaces.json` may describe
why a document is discoverable. They should not become alternate sources of the
rule. Keep their wording short enough that changing the canonical owner does not
require updating several narrative copies.

When a request names folder structure, `SKILL.md`, `references/`, skill bundles,
source-of-truth cleanup, duplicated guidance, or misplaced docs, routing should
load `docs/skills/moru-skill-bundle-migration/SKILL.md` before edits.

## Stop If

- Two canonical docs would still answer the same rule after the cleanup.
- A compatibility stub is retained without a named compatibility dependency.
- A compatibility stub contains the full rule instead of a pointer.
- A routing or index summary restates a rule in enough detail to drift.
- A moved rule loses a stronger stop condition, verification requirement, or
  source constraint.
- A third-party skill or vendor workflow is copied instead of distilled into a
  reusable Moru Core rule.
- Codex, Claude, and Antigravity/AGY each retain a full copy of the same skill
  or operational knowledge instead of resolving to one canonical owner.
- The cleanup would delete a compatibility path still referenced by runtime
  bridges, downstream repos, or tests before those references are updated or
  explicitly accepted as broken external compatibility.

## Verification

For each cleanup slice:

1. Run `python3 scripts/workflow.py validate`.
2. Run a route smoke using the user language that triggered the cleanup and
   confirm the canonical owner appears in `required_docs`.
3. Check that duplicate files now link to the canonical owner or have been
   removed rather than restating the rule.
4. Run the relevant tests for workflow routing when route surfaces changed.
5. Run `vibeguard audit . --rules .`.
6. If graphify output is maintained for the repo, run `graphify update .` after
   modifying docs or scripts.
