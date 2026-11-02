---
keyflow_id: sys_runtime_native_workspace_discovery
status: review
type: ai-generated
---

# Native workspace-group discovery

Extend the [registered-project engine](native-project-registry.md) to workspace
groups. The generated discovery CLI and the Python entry builder now share
native group candidate lookup. This extends inventory units 3 and 26; it does
not add a unit or make either entrypoint wholly native.

## Behavior and ownership

Groups contribute candidates after ordinary registrations and cwd, before
search-root scanning. Preserve the existing scores, ordered unique aliases,
source/reason order and single final name boost. A group alias contributes each
eligible member with the group score; a matching member role, name, resolved
basename or explicit alias receives the member score. Equal candidates remain
ambiguous. A group name alone does not designate its first member as primary.

Normalize non-list group/member/alias containers as the Python group owner does.
Ignore non-object groups and members, and disable only exact boolean `true`.
Names use `name`, then `id`, then `workspace`; member roles use `role`, then
`name`. Share the existing registry owner's Python truthiness, root/path
precedence and one-pass environment/current-home expansion. Keep nearest project
lookup, files, links, marker facts, candidate merging and rendering with their
existing owners. Read each caller-supplied registry snapshot once, without a
cross-call cache.

The new `discovery_groups.rs` owns only candidate projection. The entry builder's
Python `workspace_scope_manifest` still owns primary/secondary guidance,
available modes and the checkpoint before secondary writes. No scope or launch
authority moves into Rust. Supported public discovery works without Python or
Git on PATH; entry-manifest construction itself still runs in Python.

## Compatibility boundary

Explicit request paths/quotes, named-user homes, uncertain filesystem/encoding
inputs, non-ASCII case transformations and truthy non-string group names retain
Python. Do not approximate Python `str()` for arbitrary group-name values.
Unsupported public input replays Python before output; a private probe declines
without output and lets its existing Python caller continue. Source/environment
drift and forced-Python rollback keep their existing guards.

No dependency, installer schema, service, database, daemon, paid call or mutable
runtime state is added. The generated ingress already admits discovery; fresh
source hashes bind the new Rust owner and the changed Python adapter.

## Verification and delivery

Locked offline Rust tests pass all 28 checks. The focused group, registry,
discovery, entry and discovery-adapter regressions cover 60 distinct Python
tests. The initial command passed 59 and exposed one incorrect fallback
expectation: an already-matched group name short-circuits later aliases in
Python too. Correct the fixture so its Unicode alias is actually evaluated,
retain a separate unused-alias success check, and rerun that one affected test.
The corrected case passes; the unchanged 59 results are reused. No production
change or full rerun was needed for that test correction.

The generated CLI is checked for exact text/JSON, status and exit codes,
group-only ambiguity, member targeting, name/id/role precedence, exact disabled
identity, malformed containers, root/path truthiness, environment/home/relative
paths, file and symlink resolution, missing/unmarked members, fresh registry
reads and registry/cwd/group/scan merge order. Entry-manifest tests tripwire the
Python candidate fallback, compare the complete manifest and require one
registry snapshot while preserving scope/checkpoint guidance.

A fresh archive transported to an isolated source root and home passes all
55 consumer checks. Two new cases compare actual Python and native output for
group ambiguity and member selection; native execution has an empty PATH,
without Python, Git or developer tools. Existing bundle checks remain intact.
The four-host CI command now includes the group suite; this local result does
not attest execution on another host or a remote CI run.

Follow the programme's selective-measurement policy: no repeated latency,
CPU/RSS or cost experiment and no new numerical speed/savings claim.

This report and source remain on the local performance branch for the next
authorized integration step. Main integration, remote publication, release and
global runtime activation are separate actions.
