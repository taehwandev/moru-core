---
keyflow_id: runtime_perf_native_codex_statusline
status: stable
type: ai-generated
---

# Native Codex status-line text merge

Inventory unit52 now executes its deterministic text transformation in Rust.
The existing setup wrapper still owns reading the config, dry-run admission,
directory creation and writing. The direct Python CLI and setup orchestration
remain open migration responsibilities; this is not complete unit acceptance.

## Boundary

`CodexStatusLine` owns assignment/table scanning, quoted-array scanning, conflict
decisions and minimal text edits. Its private syntax and rendering modules share
that owner. It does not parse or rewrite unrelated TOML, read config paths,
write files, install anything, launch Python or call a provider.

The source-bound private `--setup-probe codex-status-line` request accepts only
`{"text": "..."}`. It returns a versioned result with `status` (`ok`, `missing`
or `changed`) and `text`. Input is bounded to1MiB. Unknown operations, malformed
payloads and source/environment mismatches decline quietly with exit125 before
any config effect. Hook soft-fail does not turn private protocol refusal into a
successful response.

The Python wrapper reads with its original UTF-8/newline semantics before the
request. Only `changed` can reach the original dry-run/write branch. A failed
optional request or an invalid response invokes the reference transformation;
the native child has no file side effects to replay. Modified helper bindings,
function code/defaults, constants, regex or JSON rendering retain the reference
path. Unsupported text, including unpaired surrogates, also retains fallback.

## Behavior preserved

- An unset status line receives the original model/directory defaults and two
  quota items. Existing selections keep their order; existing quota items are
  not duplicated.
- Comments, indentation, literal/basic quotes and unrelated bytes survive the
  same minimal edit. The original scanner's acceptance of malformed TOML is
  preserved rather than silently replaced by a general TOML serializer.
- Duplicate assignments/tables, non-string items and unprovable shapes retain
  `missing` without a write. Existing complete arrays retain `ok` without a
  write. Dry-run creates neither the config nor its parent directory.
- UTF-8/read errors precede native work. A later write failure remains a write
  failure; the optional text engine does not own or suppress it.

## Observed verification

The immutable original source at `159bd28e87778fb144d5af24cb5e4784bf3f53af`
supplies the output oracle.31 fixed configurations in both dry-run/write modes
and160 seeded configurations give222 complete status/file-byte comparisons.
The tests execute that original source rather than using the new reference
helper as the only oracle.

The final affected Python run passed27 cases:10 native integration cases,
8 existing setup cases,3 full-inventory checks and6 existing private-protocol
dispatch checks. The latter cover completion, registry reads, transcripts,
card reads/writes and overhead after extracting the launcher's private probe
dispatcher. Four Rust owner cases passed.

A real profiling observer records one native request and zero calls to the
Python scanner/render helpers. A forced-Python negative control observes those
calls, so output equality alone cannot conceal Python replay. Source mismatch,
schema refusal, custom callbacks and file errors have dedicated cases.

A temporary local debug consumer passed8 setup checks plus48 existing memory
checks with an empty executable PATH and unchanged consumer file bytes. The
debug fixture binds587 runtime source inputs. Actual runtime and config hashes
remain unchanged. This is not a release build, distribution archive, Linux
acceptance or installed-user-runtime verification. No per-file timing or
resource-saving benchmark was requested or inferred.

## Remaining delivery

The full ledger retains56 units:1 locally verified native unit,24 partial,
30 planned and1 external review. It still accounts for379 owned Python sources
and the external Wikimap source; no source was retired by this batch.
Portable two-host and actual installed acceptance remain required. Release,
push and installation holds remain separate from source/test/local-main work.
