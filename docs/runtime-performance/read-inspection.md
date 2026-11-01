---
keyflow_id: sys_runtime_read_inspection
status: review
type: ai-generated
---

# Read-only inspection batch

## Three owned changes

The baseline is performance-branch commit
`c93515051a22012277fa4a92a2efff1eb3d347c1`. This batch covers all three agreed
candidates, with separate behavior checks and measurements:

1. Extend the existing native pretool `FileQuery` to literal-file `tail`,
   `tail -n N`, `wc` with at most one of `-l/-w/-c/-m`, and bounded
   `sed -n 'A,Bp'` or `sed -n 'Ap'`. Tail counts remain within 0–1,000,000;
   sed addresses are 1–1,000,000 in ascending order. Existing literal quoting,
   path, local-executable, transcript and source checks still apply. Following
   a file, arbitrary sed scripts, writes, expansion, pipelines and uncertain
   paths retain Python handling. The hook classifies requests; it does not run
   these shell commands. Reported gains are hook overhead, not faster file I/O.
2. Remove mutation/capture modules from basic status startup. The unchanged
   state-location functions and JSON decoder now live in `agent_state_read.py`.
   Original registry, scheduler, IPC and capsule owners re-export them. Status
   keeps the same project lock, nested file locks, API contract, counters,
   malformed-JSON handling, UUID and UTC timestamp. Existing lock-file creation
   behavior is retained; this is not a new lock-free snapshot.
3. Remove memory/capsule and registry startup imports from card listing. The
   unchanged repository-key lookup and per-invocation Git memo now live in
   `agent_repository_key.py`, re-exported by project memory. Work cards use that
   owner directly; settled-state policy is still imported from the registry
   when liveness processing needs it. SQLite schema, read-only URI, WAL fallback,
   migrations, retention, updates and liveness decisions are unchanged.

Only the first slice expands Rust execution. The other two remove unnecessary
Python imports without adding another SQLite library or porting transactional
policy. No runtime dependency, daemon, worker, cache of authority, or skipped
source digest is introduced. The exact-source guard now covers 334 Python files
and seven directory shapes, including the two new shared source owners.

## Protocol and cache correction

`benchmark_native_sha.py --capture` froze the baseline's source receipt and both
executables before edits. Each variant validates its own exact source and
artifact hashes; the baseline has 367 build inputs and the candidate has 369.
The two added inputs are the extracted Python owners. Native build/setup is
excluded. Both variants run actual generated launchers in separate equal-length
temporary homes, over one synthetic Git project. No live project, mailbox,
transcript, memory or user card store is read.

The accepted comparison has prepared Python bytecode: each real callback is
warmed with its actual interpreter, source root, temporary HOME and explicit
isolated cache prefix. Verbose probes then prove status and card-owner cache
hits in both variants. The report hashes all 153 reference and 112 candidate
cache files. Measured calls disable bytecode writes; cache hashes are unchanged
after timing. Candidate pretool callbacks also pass with an empty PATH.

This extra control was necessary. An earlier `compileall` attempt prepared
neither adjacent caches nor the callbacks' HOME-specific Apple Python cache.
Its raw report is retained as `read-inspection-warm-invalid-prefix.json`, with
an explicit invalid-control assessment, and is excluded from warm acceptance.
The initial unprepared-bytecode run is also retained separately. A regression
test now requires actual cache files, including under a redirected parent
environment; a successful preparer exit alone cannot pass.

There are 24 samples per variant for each of eight cases: 384 timed callbacks
in one completed accepted run. Order is balanced AB/BA and seeded. Filesystem
caches are warm, and the host is unreserved. CPU is serial child user+system
time; RSS is BSD `time`'s command maximum, not a concurrent process-tree sum.
Only the validated status UUID/timestamp fields are normalized. Card and
pretool bytes must match exactly. Synthetic project/card state file names and
contents must match their post-warmup hashes after all timed reads.

## Accepted local results: 2026-11-01

Host: macOS 27.0.1 ARM64, Rust 1.94.1 and Apple Python 3.9.6. These are bounded
single-host callback measurements, not whole-agent or token savings.

| Generated callback | Wall median, before → after (ms) | Reduction | CPU median, before → after (ms) | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Claude tail pretool | 65.09 → 15.15 | 76.7% | 59.90 → 12.28 | 79.5% |
| Codex wc pretool | 66.58 → 15.49 | 76.7% | 61.38 → 12.68 | 79.3% |
| Claude sed pretool | 68.89 → 18.12 | 73.7% | 63.92 → 15.38 | 75.9% |
| Already-native cat control | 15.33 → 15.64 | -2.0% | 12.31 → 12.73 | -3.4% |
| Basic status | 57.56 → 45.42 | 21.1% | 52.81 → 40.68 | 23.0% |
| Validated status | 59.04 → 46.78 | 20.8% | 53.89 → 41.61 | 22.8% |
| Empty card list | 65.25 → 50.56 | 22.5% | 59.36 → 45.24 | 23.8% |
| 100-card list, including settled | 83.61 → 69.12 | 17.3% | 74.96 → 59.67 | 20.4% |

The new file-query paths, basic status and empty card lookup meet the programme's
20% and 5 ms wall-median targets. The 100-card list improves by 14.49 ms but
misses the 20% wall target. The already-native control has no improvement:
median wall rises 0.31 ms and CPU rises 0.42 ms. Keep these negative results;
do not classify every path as faster or infer statistical significance.

| Callback | Wall p95, before → after (ms) |
| --- | ---: |
| Claude tail | 68.63 → 16.64 |
| Codex wc | 76.20 → 18.44 |
| Claude sed | 78.02 → 20.40 |
| Native cat control | 18.99 → 18.14 |
| Basic status | 67.12 → 51.67 |
| Validated status | 71.25 → 68.54 |
| Empty cards | 74.16 → 63.74 |
| 100 cards | 102.16 → 90.13 |

Process RSS medians fall from approximately 21.3–21.4 MiB to 2.3 MiB for newly
native file queries, 16.3 to 13.8 MiB for basic status, 17.9 to 15.2 MiB for empty
cards, and 18.6 to 16.0 MiB for 100 cards. This is per-command process RSS.
The launcher grows by 16 bytes, from 880,496 to 880,512 bytes.

## Evidence and repeatability

The accepted ignored report is
`.moru/performance/read-inspection-cache-comparison.json`, SHA-256
`9105a900b68753044c8b0f6bc4892d766ddf03dfa5d8e0e07c7ec8e0bdabbe38`.
It contains every sample, four cache-hit proofs, cache/source/binary/utility
hashes and unchanged state evidence. Baseline launcher SHA-256 is
`aa4475c454e80a2a6522b1c7df0bcfead01b5354b47cac2344d43cf697d3be9b`;
candidate launcher SHA-256 is
`4ff1e1adb423cb166daa8c205b2df07cb6ff094eb8d1e56898887d6e229af84d`.

The unprepared-bytecode report is
`.moru/performance/read-inspection-comparison.json`, SHA-256
`289e5254d95ae6e05ba5a9cf297876a3d3c54778d8272beec45f420365c46a32`.
Its original measurement utilities are frozen under
`.moru/performance/read-inspection/utility-unprepared`. Its larger absolute
gains do not replace the accepted warm-cache results.

```sh
# Before edits/rebuilding: freeze the baseline in a new experiment directory.
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_sha.py \
  --capture .moru/performance/read-inspection-cache/reference
# After building the default candidate; preserve existing experiment directories.
PYTHONPATH=scripts:tests python3 -B tests/benchmark_read_inspection.py \
  --reference .moru/performance/read-inspection-cache/reference \
  --output .moru/performance/read-inspection-cache-comparison.json \
  --samples 24 --budget-seconds 90 --prepare-bytecode
```

## Verification and delivery boundary

Focused shared-state, registry, scheduler, IPC, project-memory, capsule,
observability and work-card suites pass 247 tests. Rust passes all 20 tests,
including the new positive and unsafe-neighbor grammar cases. The two added
Python query tests also prove native-only positive execution and Python
handling for unsafe neighbors. Transporting the default archive to a fresh
temporary root/home passes 33 checks, including the new queries without Python.

The existing four-host CI definition now includes the lightweight read-owner
and benchmark-cache regression tests. Its local command passes all 157 tests in
343.258 seconds; together with the focused suites, 371 distinct current Python
tests pass (33 tests overlap between the two groups). Editing CI does not prove
a remote run. This batch remains a local
performance-branch change without main integration, push, release or global
launcher activation. Status and cards still require Python; consumer native
installation needs no new compiler or runtime package.
