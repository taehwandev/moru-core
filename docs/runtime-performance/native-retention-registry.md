---
keyflow_id: runtime_perf_native_retention_registry
status: stable
type: ai-generated
---

# Native retention registry snapshots

The shared run-evidence retention reader now reads and validates ordinary
registry state maps in the existing `RegistryRead` native owner. This advances
inventory unit51; the public pruning CLI, planning/classification, identity
checks, locks, deletion and maintenance orchestration remain Python work.
Neither this kernel nor source integration completes a public runtime unit.

## Contract and authority

`--registry-read-probe retention-states` accepts a canonical absolute state
directory, the caller's state vocabulary and its integer-decoder limit. The
limit must match the compiled parser contract. The bounded1MiB reader opens
only `run-registry.json`, without creating or acquiring locks. Ordinary registry
snapshot operations keep their different existing-lock contract.

The existing Python-compatible JSON parser preserves schema equality for1,
`true` and1.0, ignored nonfinite/large numbers and last-key JSON semantics.
Ordered ID/state pairs preserve the original map's insertion order. Invalid
schema, rows, states or duplicate IDs return an explicit unreadable result;
no row is dropped to make a malformed registry look valid.

Unrepresentable inputs, parser uncertainty, file/encoding/profile limits and
symlinks decline quietly with125. The original reader then preserves caught
JSON/UTF-8/IO failures and uncaught integer-digit-limit errors. A parse decline
is not silently converted into an empty or unreadable registry. Modified JSON
decoders, file readers or schema settings keep reference behavior; custom
ordinary state vocabularies are transported explicitly.

The native owner cannot prune, initialize a registry, create lock files,
claim a run or change retention policy. Python retains the typed removal
preview and its observations. Application still rechecks live registry state
and evidence identity under both original locks before deleting anything.

## Verification and remaining work

The immutable original `agent_run_evidence.py` at
`61b69b2db57c7cbe32af4ac7af23fc733ba007cf` supplies the reader and preview oracle.
The affected Python suite passed41 cases:9 new native retention cases,
7 existing registry-read cases,22 retention/maintenance cases and3 ledger
cases. The `registry_read::retention` Rust selector passed all four owner cases.

A real observer records one native request, no Python registry file read and
no reference reader replay. A forced-Python negative control records both
Python operations. The native state map also feeds the original typed retention
preview: the running run stays protected and the completed run is classified
identically, with no deletion. Existing regressions cover resume after preview,
modified/replaced evidence, unreadable registries and both deletion locks.

Only synthetic registry/run fixtures are used. No real pruning, release build,
archive, hosted dispatch, provider call or installed-runtime change is part of
this source batch. Portable and installed acceptance remain separate. No
latency, CPU, RSS or cost improvement is inferred from passing parity tests.

The full56-unit ledger keeps all supporting Python sources and the external
Wikimap source. No Python source is retired here. Full native public pruning
and maintenance still require the remaining CLI/IO/policy/locking migration,
complete caller proof and final delivery acceptance.
