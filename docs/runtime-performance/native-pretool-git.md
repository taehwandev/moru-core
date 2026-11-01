---
keyflow_id: sys_runtime_native_pretool_git
status: review
type: ai-generated
---

# Native Git inspection and release-consumer coverage

## Scope

The next bounded batch extends the existing pretool boundaries without adding
an inventory unit. It classifies exact forms of `git ls-files`, cached/stage or
others/exclude-standard listing, oneline log with an optional 1–1000 count,
stat/name-only show with an optional 7–64 digit hexadecimal revision, tag listing
with optional descending version sorting, and name-status diff/cached diff.
The existing single absolute `-C` directory selector remains supported.
Queries are classified, never executed by the callback.

Unknown flags, output/exec/textconv/ext-diff options, arbitrary revisions,
unsupported counts, quoting and shell syntax retain raw Python replay. A local
`git` entry in either payload or actual process cwd also selects Python,
preserving the existing runtime-alias resolver and path-error boundary. The
same source/environment and Codex transcript checks remain authoritative.

## Verification

The affected suites cover **102 distinct Python tests and 10 Rust tests**.
The 100-test combined run had one sandbox error when an existing statusline
timeout test queried its own synthetic process with `ps`; that selector passed
with the required process-read permission. Two additional focused Git checks
passed. Six new Git methods cover 17 supported forms across both runtimes,
44 unsupported neighbors across both runtimes, local regular/launcher/loop
entries, different process/payload cwd, both transcript/error boundaries and
non-option symlink errors. Positive entrypoint checks remove Python/Git from
PATH; all negative forms compare real Python exit/stdout/stderr and preserve
write denial. No Git query is executed by these policy checks.

The release pipeline now runs the pretool/file/Git/mailbox/Stop suites on the
existing four host runners. Changes to guarded runtime Python and native test inputs now also
trigger that existing matrix. Permissions, runners and explicit publication
ownership remain unchanged. The transported consumer smoke copies all receipt
sources and the exact guarded directory shape, including empty non-Python
directories. Its first expanded attempt correctly fell back when those empty
directories were missing; restoring the directory contract made all **19
transported checks pass**. No source guard was weakened.

The consumer verifies lookup/status/pretool with empty PATH, then prepares
isolated guidance/locks and verifies quiet mailboxes/Stop with Git-only PATH.
It retains the source's Python compatibility implementation and uses no live
session, mailbox or transcript. CI only builds/tests/uploads development
artifacts; explicit release promotion still owns durable public assets.

## Local paired measurement

Use five workloads, 24 balanced AB/BA pairs per workload, one warm-up per
variant, prepared isolated bytecode, warm filesystem and an unreserved Mac.
The bounded run completed in 15.21 seconds on the same Darwin arm64/Python 3.9.6/
Rust 1.94.1 host. The actual generated callback is compared against forced Python with identical
input and exact output. CPU covers serial child work; BSD time reports
per-process maximum RSS, not aggregate tree memory.

| Callback | Wall median Python → native, ms | Wall p95 Python → native, ms | CPU median Python → native, ms | RSS median Python → native, MiB |
| --- | ---: | ---: | ---: | ---: |
| Claude log | 74.622 → 22.447 | 78.112 → 25.296 | 67.615 → 19.280 | 21.30 → 2.33 |
| Codex tracked files | 79.307 → 22.572 | 90.879 → 29.815 | 70.264 → 19.157 | 21.45 → 2.33 |
| Claude show | 74.514 → 23.440 | 78.478 → 24.530 | 67.520 → 20.244 | 21.23 → 2.31 |
| Codex tag list | 74.586 → 23.666 | 79.356 → 25.453 | 67.985 → 19.656 | 21.50 → 2.33 |
| Quoted compatibility control | 76.983 → 81.968 | 96.414 → 110.915 | 69.777 → 73.444 | Not compared |

Selected native wall medians improve by 68–72%, exceeding the programme's
20%/5 ms target. The control retains a **4.99 ms wall/3.67 ms CPU increase** and
a slower p95; it is not described as faster. Replay RSS is not compared because
of the extra parent process. No live command-frequency, whole-agent or token
savings claim follows from these local callbacks.

Raw samples and source/utility/toolchain/host hashes are retained in ignored
`.moru/performance/native-pretool-git.json`. The measured native launcher is
830,352 bytes with SHA-256
`5a522c7cdcf20402e00363800859b203d2af30a7538db72d1730330e654d036a`.
All 365 source inputs and the binary match. Cross-host behavior and release
availability require the actual CI jobs and public asset readback, independently
of this local measurement.

```sh
python3 -B scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_pretool_git test_native_pretool test_native_pretool_files test_native_mailbox test_native_stop test_native_bundle test_native_stable_launcher test_checkout_identity_runtime test_native_statusline
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --workloads git --samples 24 --budget-seconds 90 --output .moru/performance/native-pretool-git.json
python3 scripts/native-runtime-bundle.py pack --bundle .moru/native-consumer.tar.gz
PYTHONPATH=scripts:tests python3 -B tests/smoke_native_bundle.py --bundle .moru/native-consumer.tar.gz
```
