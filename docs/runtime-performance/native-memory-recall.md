---
keyflow_id: sys_native_memory_recall
status: review
type: ai-generated
---

# Native project-memory recall

The Rust memory owner computes lexical terms, eligibility, weighted relevance
and stable selection order from the original owner's supplied records. It
returns indices; the Python bridge returns the same original record objects.
The [native file reader](native-memory-files.md) now handles ordinary stored
record decoding, validation and sorted scans; the [source verifier](native-memory-source.md)
handles ordinary candidate-file checks and bounded Git calls. Capture, storage
writes, analysis binding, rendering, retirement and authority remain with their
original owners. [Source-status aggregation](native-memory-status.md) batches
uncached evidence in Rust; cache-only aggregation remains Python. Unit16 is partial.

[Replacement-history traversal](native-memory-history.md) also executes in Rust;
record admission and projection of the original metadata remain Python-owned.

[Analysis identity and candidate selection](native-memory-analysis.md) use the
native exact-match kernel; freshness, budgets and write authority remain Python-owned.

The lexical contract retains Python word classes and full case folding,
path/filename alternatives, nearest directories and stems, identifier weights,
Korean particle variants and stop words. Builder-generated Unicode data is
version bound; an interpreter using a different database retains Python
compatibility. Exact path matches include absolute query suffixes. Exceptions
and superseded bodies never become positive lexical matches.

Selection preserves active/pending/approved statuses, durable replacement
exclusion (including retired successors), scope, strict expiry, duplicate-ID
dictionary scoring, relevance-before-scope/date/id ordering and stable ties.
Context-free inspection keeps unrelated eligible records. No result limit or
new relevance threshold is introduced.

The lexical operations accept terms/recall queries, a closed top-level schema
and a bounded JSON packet under the existing exact-source/environment guard.
They read no memory store; separate record/scan operations have guarded file
reads. Neither path can write, invoke a provider, capture advice or grant
authority. Unsupported values, Unicode profiles, date forms,
custom objects, surrogates and transport failures decline to the original path;
fallback retains source errors and evaluation order. No user memory is used
as a fixture or changed by this migration.

## Verified local source and bundle

- 100 distinct Python 3.9 cases: the initial 96-case memory/ledger suite passed
  95 cases; a hardcoded equal-score order was corrected to the source's ID tie
  order and its case passed. One added fallback-profile case and three source
  receipt cases passed. The changed inactive-row assertion also passed.
- Four selected Python 3.14 cases verify compatibility refusal and original
  errors. Its initial inactive-row fixture incorrectly demanded native execution
  despite a different Unicode database; the corrected caller-result assertion
  passed. Other three cases had passed on the initial run.
- Four Rust tests pass for actual selection, replacement/expiry, duplicate-ID
  scoring, path/particle weighting and date/schema refusal.
- 191 transported macOS ARM64 checks pass, including four real native memory
  queries with empty PATH. The lexical corpus includes 80 deterministic mixed
  script cases plus focused path, casing, Korean and identifier examples.

Actual installation is checked separately after immutable main integration.
Exact-batch Linux acceptance, exceptional profiles and complete Python retirement
remain open; these local results do not establish complete unit migration or
cross-host performance.
