---
keyflow_id: sys_runtime_native_project_discovery
status: review
type: ai-generated
---

# Native project filesystem discovery

This report retains the scope and checks of commit `d6ca3422`. The subsequent
[registered-project extension](native-project-registry.md) supersedes its
registered-entry deferral; its original evidence below remains unchanged.

## Three related changes

Move directory traversal, project-marker facts and nearest-parent project-root
lookup into the common native launcher. The filesystem owner uses a FIFO queue,
stable lowercase directory ordering, the existing exact skip names, caller depth
and the existing 1,500-visit limit. It follows directory symlinks, preserves BFS
path spelling, discards a partial directory listing on iteration failure and
skips individual metadata failures. It does not prune a discovered project.
Instruction/marker names and their order remain identical to the Python owner.

Resolve symlinks component by component rather than using Darwin `realpath`,
which changes the case of supplied path components. This preserves Python's
case-sensitive output spelling even on a case-insensitive filesystem. Missing,
permission-dependent, looping or more-than-40-link resolution defers to Python.
Python-compatible whitespace trimming and conservative Unicode handling keep
name matching and sorting aligned with the existing implementation.

The generated `project-discover` entrypoint now reaches Rust in ordinary auto
mode. Both text and sorted ASCII-escaped JSON preserve output and status codes,
including the generated launcher's existing soft-fail convention. The Python
entry builder passes its already-read registry snapshot through one private
stdin probe, so it can share the engine without another registry observation or
a subprocess for each directory. Registry/scope/launch effects remain with their
original Python owners. A forced Python backend bypasses the adapter.

## Supported scope and conservative fallback

Native discovery accepts ordinary requests, cwd parent lookup, bounded search
roots, configured/environment search roots, optional default-home roots and
registries without project entries or workspace groups. It reproduces the
existing cwd/search-root scores, merges, name boosts, tie ordering and selection
threshold. The exact runtime source guard binds all 335 Python files and seven
source directory shapes, including the new adapter.

Explicit request-path grammar, registered project entries/aliases, workspace
groups, variable expansion, non-ASCII case transformations, unusual CLI forms,
uncertain resolution and source/environment mismatches retain Python. The
private probe declines with no stdout; ordinary public calls replay the original
Python CLI. A process-local replay marker prevents that CLI from starting the
same declined probe again. No registry, filesystem or authority result is cached between calls.
No new crate, service, daemon, compiler requirement for consumers or permission
decision is introduced. These three responsibilities extend two existing entry
boundaries, with no additional inventory unit.

## Verification and evidence boundary

The final default Rust build passes 25 tests. The final native discovery and
stable-launcher command passes 29 Python tests, covering actual Python/native
text/JSON parity, selected/ambiguous/not-found exits, no-Python operation,
Unicode, case-insensitive spelling, symlinks/cycles, skip/depth/visit bounds,
registry roots, one registry snapshot, entry-manifest parity, source drift,
environment and unsupported-input fallback. Existing discovery suites were
also exercised; their only initial failure was the new copied-source fixture,
which needed the producer's empty directory shapes. That fixture is corrected
and covered in the passing final native suite. A separate parity failure exposed
the Darwin case-normalization difference; the component resolver and regression
case now cover it.

Packaging the default build and transporting it to a fresh root/home passes
46 consumer checks. Four added discovery checks run with an empty PATH: native
text/JSON parent lookup, ambiguous scanning and not-found depth handling. These
checks also cover the real generated dispatch header, not only a direct binary
call. The four-host CI command includes the new discovery suite; local execution
does not establish a remote run or another host's result.

Following the [programme policy](prd.md#behavior-acceptance-and-selective-measurement),
this batch takes no new latency, CPU/RSS or cost measurements and makes no new
numerical performance claim. Earlier comparison evidence remains unchanged.

The implementation, review and default bundle are local to the dedicated
performance worktree, based on main `876823d7`. This increment does not publish
main, push, tag, release or replace a globally installed runtime. Consumer
installation still needs a matching host/source bundle; Python remains available
for the documented compatibility scope.
