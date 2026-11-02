---
keyflow_id: sys_runtime_native_project_registry
status: review
type: ai-generated
---

# Native registered-project discovery

## Three related changes

Extend the shared engine from `d6ca3422` to registries containing project entries.
The generated CLI and Python entry builder now use the same native path for
registered discovery rather than deferring merely because `projects` is nonempty.

1. Process `root`/`path` with Python truthiness and precedence, skip malformed
   entries and disable only an exact boolean `true`. Resolve existing project
   directories or files through the previous filesystem owner. Expand `$name`
   and `${name}` once, preserve unknown variables and then expand current-user
   `~`. Normalize empty results to `.` and remove redundant path components,
   matching `Path` construction. Environment registry/search roots share this
   expansion; explicit CLI registry paths keep their literal-path contract.
2. Match project names and aliases with the existing strict boundaries and
   normalized multiword forms. Generic names such as `web` are accepted as
   explicit aliases. Preserve the registration score and one name/alias boost.
3. Add registry candidates before cwd and scan candidates. Merge confidence by
   maximum and preserve ordered unique reasons, markers, sources and aliases.
   An initial alias list retains duplicates until a later merge deduplicates
   the whole joined list, including when the incoming aliases are empty.

Matching and merging now have one candidate owner; registry read/path processing
has a separate owner. The filesystem engine, output rendering and source guard
remain shared. The Python entry builder still supplies its single registry
snapshot; the native path neither rereads it nor caches it between calls.

## Compatibility and verification

Workspace groups, explicit request-path grammar, named-user homes, non-ASCII
case transformations and uncommon alias/error shapes retain Python. Source or
environment drift still replays Python; forced Python remains available. No new
crate, service, database dependency, daemon or permission decision is introduced.
The later [workspace-group extension](native-workspace-discovery.md) supersedes
this increment's group deferral while retaining Python scope/checkpoint policy.

The final default build passes 26 Rust tests. The focused registry/discovery
command passes all 51 Python tests, covering real text/JSON and exit parity,
native execution without Python on PATH, path precedence, disabled identity,
generic/Unicode aliases, symlink merges, duplicate ordering, ambiguity, fresh
registry reads, variable/home expansion, literal unknown variables, nonrecursive
substitution and registered entry-manifest parity with one registry snapshot.
Negative cases retain Python error/compatibility behavior.

Transporting the default archive to a fresh temporary root/home passes all
50 checks. Four added registered-discovery checks run with an empty PATH:
text/JSON alias selection using an environment path, ordered merging and an
ambiguous alias. The four-host CI command includes the registry suite; this
local check does not establish a remote run or another host's result.

No latency, CPU/RSS or cost experiment is repeated, and no new numerical speed
or savings claim is made. The source receipt still binds all 335 Python modules;
the extracted Rust owners add no inventory entry or new fully migrated boundary.

This increment remains on the local performance branch. It does not update
main, push, tag, release or activate a globally installed runtime. The report is
in review state for the next authorized integration step.
