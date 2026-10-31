---
keyflow_id: sys_native_statusline_performance_contract
status: review
type: ai-generated
---

# Statusline performance specification and evidence

Owner: pure statusline formatting plus separately owned process and chain adapters.
Allowed imports: Rust std and existing serde_json, with ordered-map support
from cached crates. Forbidden: network, account queries, repository/ledger
content reads, persistent payload storage and new runtime model calls. The
process adapter checks root-pointer metadata and project markers to preserve
root selection. A different root or HOME pointer uses Python before input.

The Python reference remains `support.statusline.render` and runtime_quota.
Both provider entrypoints print model, session location and remaining budgets
without a trailing newline. Preserve the full public output: Unicode path
shortening, home boundary, colors, quota precedence, insertion-order last-window
wins, round-to-even, gauge width and three-character percent alignment.
Nothing is fetched: quota comes only from the supplied payload.

The native formatter is pure and can return unsupported before output. The
parent adapter then uses the existing Python renderer with the original input.
This is semantic selection before any chain or output, not an error retry.
Unsupported CLI syntax/text encoding can exec Python before reading input.
Native execution failures do not replay an already-run chain.

Preserve `--chain`: execute the configured command exactly once via /bin/sh,
pass the same text payload Python would read (including universal newlines),
retain stdout even for nonzero child exits, strip it as Python does, and keep
its two-second bound. Timeout/spawn failure leaves only the native segments.
Output-decoding errors preserve a nonzero failure rather than running the
chain again. Only controlled test chains are invoked by this experiment.

Keep stdout/exit semantics, NO_COLOR, existing soft-fail behavior and Python
rollback. A normal UTF-8 payload must execute without Python on PATH, including
a shell-builtin chain. Python-specific coercions or number spellings can take
the compatibility path. Do not silently approximate unsupported values.

The first screening baseline uses 20 prepared-bytecode fresh processes per
case: plain median 58.1888 ms, p95 64.8304 ms; controlled-chain median 62.0244 ms,
p95 76.2012 ms. This selects a candidate, not an accepted improvement. Final
measurement must use the same generated entrypoint and common workloads.
Source integration, temporary installation and actual global activation remain
separate. All changes stay on the performance branch.

## Reproduction

From this branch, with a cached Rust toolchain/dependencies and Python:

```sh
python3 -B scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_statusline.py --samples 40
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_statusline
```

The benchmark installs only into a temporary HOME. It prepares Python bytecode
for every compared path, then randomizes the four variants in each of 40
fresh-process rounds per workload (seed 5189). It requires identical stdout,
stderr and exit status. The reference is the generated Python-only launcher;
native-auto and Python rollback use the same generated polyglot launcher.
`python_no_site` invokes the Python reference with `-S`. Warm filesystem,
captured pipes and an unreserved host apply to all variants. Build/setup and
bytecode preparation are outside timing. No live configured chain is executed.

Run timing outside filesystem/process sandbox instrumentation, and before
parallel tests or builds. Samples, source hashes, generated entrypoint hashes,
toolchain and native receipt are written to ignored local state at
`.moru/performance/statusline-comparison.json`. That file is retained execution
evidence, not a required distributed artifact. Rerunning regenerates it.

## Observed result: 2026-10-31

macOS 27.0.1 arm64; Python 3.9.6; rustc 1.94.1. Times below are milliseconds,
shown as **median / p95**. These are paired controlled workloads, not an
estimate of total agent latency or token use.

| Workload | Python reference | Python `-S` | Native auto | Python rollback |
| --- | ---: | ---: | ---: | ---: |
| Plain Claude line | 59.5396 / 81.0711 | 49.0545 / 66.1880 | 11.0981 / 15.1168 | 61.5244 / 75.2662 |
| Claude + shell builtin | 62.8155 / 70.1493 | 52.1295 / 55.8562 | 16.1079 / 18.1398 | 65.2640 / 76.6703 |
| AGY + controlled cat pipeline | 68.5567 / 80.8409 | 57.1076 / 67.3904 | 19.7674 / 22.4784 | 72.6973 / 85.5885 |
| Non-string model compatibility | 59.9934 / 79.8790 | 49.8992 / 78.8727 | 67.1839 / 106.5694 | 64.4002 / 77.2350 |
| Legacy launcher help control | 46.2227 / 58.5421 | 35.7970 / 44.0428 | 48.9123 / 69.8826 | 48.9284 / 66.2024 |

The three supported rendering workloads save about **46.7–48.8 ms** median
(**71.2–81.4%**) against the Python reference. All exceed the 20%/5 ms target
and improve observed p95. The simpler `-S` option saves about 10–11 ms but
does not reach 20% on these rendering cases. Native also remains substantially
faster than `-S`; this is the reason to retain the native experiment.

Costs are explicit: the compatibility case adds **7.19 ms** median and **26.69
ms** p95 against the original reference; legacy help adds **2.69 ms** median.
The latter uses Python directly through the shell bridge and is not a native
rendering win. Fallback frequency and aggregate live-workflow impact are
unmeasured. Tail samples are host-dependent, not a guaranteed percentile SLO.

The launcher is **711,808 bytes**, versus the prior 510,560-byte stage-two
artifact (+201,248 bytes). Its SHA-256 is
`f493ed61c8dbaa182c155db32c6b49f1a9b8153c09ad5add2e44f0a30522aeff`.
The checkout-only binary is 528,000 bytes; enabling ordered JSON maps affects
the shared crate. Peak RSS, startup on other machines and real configured
chain latency have not been measured.

## Conformance and collaboration

Claude supplied the pure formatter. Parent review corrected numeric-string
window minutes and JSON whitespace handling before integration. AGY supplied
rounding, map ordering, Unicode, consumed-input fallback, inherited-pipe timeout
and real-entrypoint counterexamples. Its suggestion to use `-S` was measured;
its daemon and guessed direct-chain alternatives were not adopted. AGY emitted
a warning that its plan flag had no effect with slash expansion disabled;
that flag is not treated as evidence of a tool-execution boundary. Briefs were
generic and repository-free; local CLI responses were observed successfully.

`test_native_statusline` executes the real generated launcher. It covers both
aliases without Python on PATH, 270 quota boundary/random payloads, Unicode and
home boundaries, ordered aliases/duplicate keys, numeric precedence, Python
fallback with original pipe input, CLI/root selection, chain newlines/nonzero
stdout, decode failure without replay, soft-fail, a 200 KB pipe and timeout
cleanup of the chain's own process group. Python remains the output oracle.
The related regression run passed 203 Python tests and eight Rust tests.

Decision: keep this as a **verified performance-branch candidate**. Standard
UTF-8 rendering meets the local target; fallback and wrapper costs remain
visible. This does not authorize a main merge, global activation or release.
Before rollout, assess actual call/fallback frequency and supported hosts;
operators can retain the existing Python launcher or select Python rollback.
