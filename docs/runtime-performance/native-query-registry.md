---
keyflow_id: sys_runtime_native_query_registry
status: review
type: ai-generated
---

# Native query ingress and prepared registry reads

## Scope

Extend the existing Claude/Codex pretool boundaries and the runtime-session
resolver in three ordered slices. This adds no inventory unit: coverage remains
17/53, including partial migrations. The existing selective-measurement policy
applies; behavior checks establish compatibility, with no new numerical latency,
CPU, memory or token-saving claim.

1. Recognize literal `rg` regex arguments and explicit file globs, including
   `rg -n 'foo|bar' src`, `rg --files --glob='*.rs' src` and `--` before paths.
2. Recognize quoted absolute Git `-C` paths, a single log format with an optional
   count of 1–1000, and two bounded revisions followed by a diff summary flag.
3. Read prepared run-registry snapshots through Rust and remove eager registry,
   capsule and IPC imports from the runtime-session read path.

## Query contract

`LiteralArgs` recognizes complete literal words, not shell programs. Limit input
to 16 KiB and 20 words. Quoting may wrap an entire argument or a value attached
to `--glob=`, `--format=` or `--pretty=`. Reject expansion, command substitution,
quote concatenation, operators, redirection, executable quoting and quoted flags.
Double-quoted backslashes decline; single-quoted regex backslashes are literal.

The file-query owner still validates actual paths separately from pattern/glob
metadata. Paths retain the existing no-parent-traversal grammar and executable
shadow/source/environment checks. Unknown flags and `rg --pre` use canonical
Python. The parser never runs the requested command.

Git retains its closed command/flag vocabulary. Log formats are nonempty and at
most 512 bytes; duplicate formats/counts decline. Revision pairs accept `HEAD`,
`HEAD~N`, `HEAD^N` with N from 1–1000, or 7–64 hexadecimal characters. Named refs,
external diff/config/output flags and arbitrary shell syntax use Python. These
are native pretool decisions, not new execution or write authority.

## Prepared registry contract

`--registry-read-probe` is private bounded JSON ingress, with no public command
alias. Source/root/environment matching uses the same callback guard as the
other private protocols. Input, registry and output are each bounded to 1 MiB.
Unsupported input exits 125 silently, including when hook soft-fail is enabled.

The caller provides its canonical state directory, state names and content-free
evidence keys. The native owner opens existing regular, non-symlink project and
registry lock files in canonical Python order. Locks are nonblocking and never
created. It then opens a bounded regular registry descriptor with
`O_NOFOLLOW | O_NONBLOCK`. Missing, busy, symlinked, malformed, oversized or
unsupported state declines to Python, preserving legacy initialization, waiting
and errors. Integers beyond lossless JSON representation and floating-point row
values also decline rather than silently changing copied metadata.

The three read operations preserve distinct canonical behavior:

- `active` returns every selected row in original order, including older rows.
- `bindings` chooses the latest row per evidence key before state filtering;
  terminal and claiming rows suppress older active rows. First-key insertion
  order and the legacy `preflight.json` binding are preserved.
- `latest` returns the last matching run ID regardless of state, or JSON null.

Missing `resume_generation` defaults to zero; explicit null stays null. Empty
arrays and null are successful results, distinct from native decline. No run
count ceiling is added, and no snapshot survives the call.

Python retains all claims, transitions, ownership checks, session/generation
selection, worker exclusions and cancellation transactions. Static state names
have one lightweight owner; the canonical evidence-key function moves to the
shared state-read module and remains re-exported by the registry. Evidence-key
calculation never starts a subprocess per candidate. Native JSON transport is
shared with completion probes, without changing their fallback or admission.

## Verification and delivery

`test_native_pretool_queries` exercises both generated provider entrypoints with
Python absent from PATH, plus adversarial shell/option neighbors and forced
Python parity. `test_native_registry_read` uses the actual private protocol and
adapter to check ordering, defaults, legacy bindings, terminal/claim suppression,
257 unfinished rows, empty/null results, unsafe files, busy locks, malformed
input, exact fallback and fresh-process import isolation. Read-only snapshots
must leave bytes and directory contents unchanged.

Existing pretool, runtime-session, registry, completion, Stop and next suites
remain the authority regressions. Both new suites run in the four-host native
distribution workflow. The transported-consumer smoke exercises all three
registry operations and representative query forms without a compiler or Python
on PATH. A local pass does not attest execution on the other CI hosts.

Main integration, remote availability and actual installed activation remain
separate checks. Installation uses the verified host/source-matching bundle and
the existing stable launcher; preserve runtime settings and the durable root
pointer. No package release, tag, new service or installer dependency is added.
