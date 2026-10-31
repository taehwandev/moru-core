---
keyflow_id: sys_runtime_native_mailbox
status: review
type: ai-generated
---

# Native quiet mailbox callbacks

## Supported boundary

The second ordered increment handles repeated
`mailbox-hook deliver|ack --runtime claude|codex` calls with unchanged guidance
and empty inboxes/leases. It proves that Python would produce no output or
state change. Message delivery, acknowledgements, task authorization and all
effectful paths remain owned by `agent_mailbox_hook.py` and its stores.
This upgrades inventory unit 14, rather than adding a migration target.

The source/environment guard returns the validated Core root from the same
snapshot. A shared replay adapter preserves raw stdin, stdio and exit/signal
handling; it executes Python once when a proof is unavailable. The new mailbox
handler never writes state or claims task authority.

Repository identity uses the exact existing two-second Git command, with the
same canonical-project fallback and SHA-256 prefix as Python. It does not
replace Git identity with an approximate filesystem heuristic. Git remains
required for successful Git identity lookup; native execution proof removes
Python from PATH while retaining the actual Git executable.

Both project and repository-shared queues must be empty for the selected
runtime. Native takes existing `.mailbox.lock` files with nonblocking exclusive
`flock`; missing, busy, special or symlinked locks select Python. Symlinked or
unreadable state also selects Python. No cross-call state or source cache exists.
The existing locked libc version becomes a direct dependency for these Unix
primitives; no package version or downloadable dependency is added.

For prompt delivery, the canonical continuity section is read each time and
its exact hash must match the session's guidance receipt. A first prompt or
changed/malformed/missing receipt uses Python. Any task record or turn budget
also selects Python, preserving prompt-boundary pause/reset effects. An absent
or empty task directory is eligible; paused historical records are deliberately
still on compatibility. Acknowledgement does not pause tasks or refresh guidance.

Conservative replay also covers unusual argument order, payload types, Unicode
session identifiers, source drift and unsupported environment overrides. The
bounded fast path accepts a nonempty printable ASCII session up to 128 bytes,
an absolute existing cwd and at most 64 KiB input. These are eligibility limits,
not restrictions on the Python interface.

## Verification and measurement

The paired experiment and executable verification are recorded before local
integration. Results below are limited to these callback fixtures, with warm
filesystem and prepared isolated bytecode; they do not establish production
call frequency, whole-agent latency or token savings.

The affected suites pass **147 distinct Python tests and 10 Rust tests**. After
consolidating the shared guard's exported functions behind one `CallbackGuard`
owner, all **32 affected mailbox/pretool tests and 10 Rust tests** passed again;
the remaining checks were unchanged. Ten new
mailbox methods exercise the actual generated launcher: native quiet deliver
and ack for both runtimes; cwd ancestry; first/changed/malformed guidance;
unusual payloads; delivery followed by acknowledgement; malformed local packet
quarantine and orphan-lease cleanup; task pause and budget deletion; absent,
symlinked and busy locks; empty versus populated task state; reordered arguments;
Python environment overrides; and shared reference identity across a real
linked Git worktree. Output is compared byte-for-byte. State snapshots compare
paths, kinds and contents; only generated receipt/lease clock values are
normalized. No live sessions, messages or transcripts are used.

The first executable attempt caught a missing auto-selector entry: its quiet
checks reached the Python wrapper rather than Rust. Adding `mailbox-hook` to
the installed trampoline selection and rebuilding made the positive no-Python
checks pass. Negative checks intentionally remove Python and require exit 127
without native state changes, then compare real Python replay and effects.
Existing pretool, source-input, launcher, bundle, builder, mailbox-delivery and
task suites pass after the shared replay/root changes.

On Darwin 27.0.1 arm64, Python 3.9.6 and Rust 1.94.1, 24 balanced AB/BA pairs per
case completed in a **16.95-second bounded run** including fixture preparation.
Per-callback timers exclude preparation. Each variant uses the same generated
callback and source, with one warm-up per case/variant.
No other verification or provider process was started during the timing run.

| Callback | Wall median Python → auto, ms | Wall p95 Python → auto, ms | CPU median Python → auto, ms | Reported peak RSS median Python → auto, MiB |
| --- | ---: | ---: | ---: | ---: |
| Claude deliver | 79.434 → 34.092 | 88.453 → 45.034 | 70.206 → 27.737 | 16.75 → 4.02 |
| Claude ack | 75.524 → 33.670 | 78.058 → 35.527 | 68.066 → 27.673 | 16.80 → 4.02 |
| Codex deliver | 76.602 → 33.463 | 79.521 → 37.258 | 69.679 → 27.387 | 16.75 → 4.02 |
| Codex ack | 76.530 → 33.697 | 79.261 → 35.714 | 69.504 → 27.636 | 16.75 → 4.02 |
| Reordered-argument fallback | 77.127 → 80.028 | 79.946 → 82.687 | 70.079 → 71.928 | Not compared |

Quiet paths reduce median wall time by 55–57%, beyond the programme's 20%/5 ms
target. The fallback control retains a 2.90 ms wall and 1.85 ms CPU increase;
it is not described as faster. CPU covers serial child work. BSD time reports
per-process maximum RSS, not aggregate concurrent tree memory; replay adds a
parent process, so its RSS is deliberately not compared.

Raw samples, platform metadata and exact source/utility hashes are retained in
ignored `.moru/performance/native-mailbox-final.json`. The earlier pre-structure
measurement remains in `native-mailbox.json` (quiet wall 76–78 to 33–34 ms;
fallback 78.54 to 81.45 ms); it is not silently replaced. The final measured launcher is
813,728 bytes with SHA-256
`4851dbfe1f602cf4b6be4a0446d441bf5f850fcf0cea7f5a8942e6fd9835071c`.
All 362 receipt inputs and the measured binary match; the guarded runtime set
contains 332 Python files in seven directories. These are local-host results,
not cross-platform installation or production-frequency evidence.

```sh
python3 -B scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_mailbox test_native_pretool test_native_pretool_files test_native_stable_launcher test_native_bundle test_agent_mailbox_delivery test_agent_mailbox_task test_support_native_source_inputs test_build_native_runtime
CARGO_TARGET_DIR="$PWD/.moru/native/cargo-target" cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --workloads mailbox --samples 24 --budget-seconds 90 --output .moru/performance/native-mailbox-final.json
```

Source review/commit precedes local main activation and an actual installed
callback readback. `MORU_LAUNCHER_BACKEND=python` preserves rollback; absence of
a matching optional native artifact keeps installation on Python. Stop handling
is the next ordered unit and gains no native coverage from this mailbox change.
