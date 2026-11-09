---
keyflow_id: sys_native_memory_files
status: review
type: ai-generated
---

# Native project-memory record reads

The ordinary project-memory reader and sorted store scan now execute filesystem
reads, UTF-8/JSON decoding, record validation and SHA256 integrity checks in Rust.
The Python owner still resolves the store/repository and owns capture, retirement,
source hashing, analysis evidence binding, rendering and write authority. Unit16
remains partial; its earlier lexical/ranking engine is documented in
[native-memory-recall.md](native-memory-recall.md).

The record contract retains exact filename/ID binding, Python's schema equality
(including `true` and `1.0`), supported statuses, scope, Unicode printable/length
checks, dates, falsey replacement metadata, unique source paths, blob syntax,
analysis conditions and the original digest field set. Digest serialization uses
sorted keys, default separators and unescaped Unicode. Unknown metadata, key
order, duplicate-key placement and supported integer/float/bool types survive.
Malformed records still produce no record. Invalid JSON/UTF-8 is distinguished
from an unsupported native decoder profile.

The scan enumerates its own directory descriptor, sorts matching `.json` names,
reads children relative to that descriptor and counts rejected entries exactly
once. Hidden files, final symlinks and directories retain the source decisions.
No record, lock, marker, registry or directory is created or changed. A changed
directory identity or unsupported entry declines the whole query rather than
returning an incomplete result.

Native admission opens components with NOFOLLOW and CLOEXEC, checks file identity
and kind, rejects inherited descriptor namespaces and does not consume FIFO or
device input. Ancestor links and search-only directory profiles may defer because
the guarded native open needs stronger permissions than the source read. Files
above 1 MiB, unsupported integer/nonfinite/surrogate metadata, Unicode versions,
date spellings and packet limits also defer. The original reader handles these
profiles, including its original failures; they are outstanding migration scope.

## Verification

- 109 Python 3.9 memory/source/ledger cases passed, including 12 real native file
  and scan cases. The actual helpers succeed with Python `read_text`, `_digest`
  and the per-file `read_record` loop disabled.
- Nine Rust memory tests passed, including the existing four ranking tests and
  five file/validation tests. The canonical Unicode/quote digest vector comes
  from the original Python implementation.
- Three selected Python 3.14 cases passed for unsupported metadata, profile
  fallback, exceptional filesystem admission and malformed response handling.
- 195 transported macOS ARM64 checks passed. Four new record/scan/integrity/missing
  store queries execute with empty PATH and retain input bytes.

All fixtures are synthetic temporary records. Actual installation is verified
separately after immutable main integration. Exact-batch Linux acceptance,
remaining exceptional profiles and complete Python retirement stay open.
