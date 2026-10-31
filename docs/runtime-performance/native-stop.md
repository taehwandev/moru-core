---
keyflow_id: sys_runtime_native_stop
status: review
type: ai-generated
---

# Native quiet and settled Stop callbacks

## Authority and state boundary

The third ordered increment handles ordinary quiet `claude-stop-gate` and
`codex-stop-gate` calls. Rust proves that no output or state change is required;
it never continues, interrupts, settles or finishes a task. The current Python
owners retain every active-run and work-continuity decision, including the
new rule that recorded remaining work receives one bounded continuation.
This adds partial coverage for inventory units 22 and 25, not full policy ports.

Native requires a valid source/environment snapshot, a canonical Git project,
quiet project/reference mailbox state and existing nonblocking locks. Shared
`LocalState` owns bounded regular-file reads, symlink rejection and compatible
locks for mailbox and Stop consumers. No files or locks are created natively.
Any queued message/lease, task record/budget, missing or busy lock, source drift,
unknown state or uncertain path replays raw input once to Python. Even a disabled
Stop gate must acknowledge shown messages; mailbox eligibility is checked first.

The exact registry must be absent or contain only terminal `completed`,
`cancelled` or `failed` rows. Any other row, even for another session or an older
claim, conservatively selects Python. A cheap preliminary history check only
rejects candidates before the source scan; it cannot admit a native result.
Admission repeats the history check under the existing project/registry locks.
Active, paused, resuming, claiming, blocked, interrupted, reconciliation and
unknown states therefore keep Python's current authority and effects.

Claude's legacy edit marker must be absent, already covered by a newer/equal
finished/settled marker, or already reported by a newer/equal stop-blocked marker.
New edits and the shared legacy finish-file fallback remain on Python. Indexed
session projects are checked too, with an 8 KiB/eight-root native bound; ambiguous
or noncanonical index entries select Python. Timestamps use monotonic ordering
of the same filesystem values, without inventing a new completion receipt.

The native payload boundary is an absolute existing cwd, ASCII alphanumeric/
hyphen/underscore session id up to 128 bytes and at most 64 KiB JSON. Unsupported
inputs/arguments preserve Python behavior. The selected project must have an
ordinary local `.moru` directory, distinct from global state, proving it is the
same opted-in nearest Git root selected by the Python adapters.

## Verification

The affected run passed **151 Python tests and 10 Rust tests**. Eleven new
methods invoke actual generated callbacks and compare exact output and resulting
state for quiet/terminal history, no registry, finished/settled/already-reported
edits, new edits, active remaining work in both runtimes, approval/user-stop/
retry flags, global blockers, versioned interruption, legacy closeout, shown
message acknowledgement with the gate disabled, malformed/unknown registry
state, another indexed project's edits, lock absence/symlinks/contention and
unsupported inputs. Positive checks remove Python from PATH while retaining Git;
negative checks require exit 127 without native mutations before real replay.

The comparison harness preserves private file/directory modes and marker
timestamps when restoring fixture state. Its first clone attempt reset those
properties, causing the existing secure continuation reader to reject restored
packets; correcting the fixture restored the expected continuation/interruption
comparisons. This was a harness error, not a native-policy correction.
Only generated clock fields are normalized for serial effect comparisons.
No live messages, sessions or transcripts are read or changed by the tests.

The later early-rejection refinement repeats the same final locked predicate.
All 11 affected Stop tests and 10 Rust tests passed again. The matching
artifact measurement is recorded below;
unchanged mailbox/legacy/continuity checks retain their completed evidence.

## Measurement and delivery

Measurements use the same generated callback in auto and forced Python modes,
balanced AB/BA pairs, prepared isolated bytecode, warm filesystem, serial child
CPU and BSD time per-process peak RSS on the local host. Ordinary quiet/settled
cases are measured alongside a real active-work continuation fallback with
exact block output; differential tests verify its still-active run. This checks the cost of
handing unfinished work back to Python, not only a cheap syntax rejection.

On Darwin 27.0.1 arm64, Python 3.9.6 and Rust 1.94.1, 24 balanced AB/BA pairs per
case plus one warm-up per variant completed in a **21.38-second bounded run**.
Run duration includes fixture preparation; callback timers exclude it. No other
verification or provider call was started during the measurement.

| Callback | Wall median Python → auto, ms | Wall p95 Python → auto, ms | CPU median Python → auto, ms | Reported peak RSS median Python → auto, MiB |
| --- | ---: | ---: | ---: | ---: |
| Claude no work | 87.540 → 34.104 | 90.772 → 37.640 | 79.872 → 27.632 | 18.42 → 4.02 |
| Codex no work | 86.546 → 34.184 | 88.843 → 36.332 | 79.584 → 27.956 | 17.92 → 4.02 |
| Claude settled edits | 91.319 → 36.411 | 146.654 → 46.853 | 84.310 → 28.855 | 18.41 → 4.02 |
| Claude indexed settled project | 89.024 → 34.871 | 91.463 → 37.804 | 81.676 → 28.775 | 18.39 → 4.02 |
| Active remaining-work fallback | 124.155 → 130.916 | 137.112 → 141.222 | 106.586 → 110.359 | Not compared |

Quiet/settled medians improve by 60–61%, exceeding the 20%/5 ms selected-path
target. Active-work replay costs an additional **6.76 ms wall (5.4%) and
3.77 ms CPU (3.5%)** in this run. Those costs remain part of the tradeoff; the
fallback is not described as faster. Actual callback mix was not collected, so
these results do not establish net session-wide savings. The preliminary
registry check keeps obvious unfinished work off the expensive source scan.
RSS is the tool's per-process maximum, not an aggregate process-tree total;
replay RSS is deliberately not compared.

Raw samples, platform and source/utility hashes are retained in ignored
`.moru/performance/native-stop.json`. The final measured launcher is 830,368
bytes, SHA-256
`bb5ebb22d2c62c41eb19ae8e1669d8196b18f25f03dd28e62d6e9ba5b35e359a`.
All 365 receipt inputs and binary hashes match. Its source guard still covers
332 Python files in seven directories; no cross-call cache was introduced.

```sh
python3 -B scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_stop test_native_mailbox test_agent_stop_continuation test_agent_run_interruption test_claude_stop_gate test_codex_stop_gate test_agent_work_completion test_work_continuity_lifecycle_e2e test_native_stable_launcher test_native_bundle
CARGO_TARGET_DIR="$PWD/.moru/native/cargo-target" cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --workloads stop --samples 24 --budget-seconds 90 --output .moru/performance/native-stop.json
```

Local source review/commit precedes main integration and installed readback.
Rollback remains `MORU_LAUNCHER_BACKEND=python`; optional artifact absence or
source mismatch preserves compatibility. No live frequency, whole-agent or
token-savings claim follows from these callback fixtures. Other hosts retain
the portable bundle's existing per-host build/receipt requirements.
