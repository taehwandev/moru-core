---
keyflow_id: sys_runtime_native_next
status: review
type: ai-generated
---

# Native inactive next advice

## Scope and authority

`NextProcess` implements bounded `next` CLI shapes for JSON and Markdown advice
when no active run is proven. `Verification` maps safe Git status paths to the
same changed paths, nearest Python test modules and suggested commands as the
reference. Suggestions are never executed. Explicit evidence, help/errors,
unmodelled argument order, relative explicit project paths, worker bindings,
active/unknown run state and uncertain paths execute the original Python CLI.
The existing source/environment guard and explicit Python rollback remain.

Without a runtime session, Python does not resolve run evidence; native follows
that same rule. With a session, absent project state or terminal-only registry
history is required. Existing project/registry locks are acquired without
creating files; missing/busy/symlink locks select Python. The pre-guard state
check only rejects, followed by a locked recheck after source validation.
Locks are released before Git status, matching the Python reader. Nothing is
marked finished, resumed or acknowledged by this path.

The shared `GitRead` owner retains the checkout identity's `git -C` argv and
adds status with exactly `git status --porcelain --untracked-files=all` in the
selected cwd. Both share the existing two-second native transport deadline.
Nonzero exits, decode failures and native timeouts select Python; timeout can
therefore add up to two seconds before Python's existing ten-second Git read.
Git is required even when Python is absent. No cache, daemon, service, model
call or dependency is introduced.

Verification paths are literals including Unicode, spaces and Git's
escaped reference strings, with no parent or option-like prefix. Rename destinations, sorting/deduplication, local `.moru/` filtering,
deleted tests, nearest test lookup, compile/test command limits and framework
marker priority match the reference. Other metacharacters and symlink/error
uncertainty remain on Python. Existing reference handling of Git's quoted
filename strings is preserved, not reinterpreted. This does not change the
separate pretool classifier's quoted file-operand contract.

## Test language and acceptance

Rust unit tests own CLI admission, exact JSON/Markdown formatting and the pure
status-path boundary. Python process tests compare the old and new engines,
state bytes, locks, environment, real Git and transported installation. The
Python test runner is a developer tool, excluded from child-process timing
and RSS; it is not needed by an admitted installed native call. Other Core
paths still require Python during migration. Tests need not all use the
product runtime language to establish its behavior.

The initial fixture accidentally left its opt-in instruction file untracked;
native correctly rejected its supposed clean state. The fixture now excludes
that synthetic file and asserts clean status before testing. Initial timing
then exposed a 25.09 ms dirty-path fallback penalty (67.407 → 92.492 ms), retained
in `.moru/performance/native-next-initial.json`. That led to the bounded native
verification extension rather than accepting that common regression.

A focused no-Python regression also reproduced registry locks being held
through Git. The correction drops both locks before invoking Git, and the spy
Git process must acquire both locks itself. Source/CLI parity alone would not
have established that concurrency boundary.

## Reproduction and delivery

```sh
PYTHONPATH=scripts:tests python3 -B scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_next test_agent_next_action
cargo test --offline --locked --manifest-path native/checkout-identity/Cargo.toml \
  --target-dir .moru/native/cargo-target
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py \
  --workloads next --samples 24 --budget-seconds 90 \
  --output .moru/performance/native-next.json
```

The timed comparison uses the generated temporary-home entrypoint, prepared
bytecode, balanced serial Python/auto pairs and BSD `time` on macOS. Build/setup
and the Python driver are excluded. The host is unreserved; no live frequency,
whole-agent speedup, token saving, process-tree peak or cross-host timing is
inferred. Source/bundle checks, four-host CI, public release and global runtime
activation remain separate outcomes. Inventory stays 14/53: the already-counted
next boundary becomes partial native, giving ten native-involving boundaries
and four Python-only optimizations.

## Final measurements

On macOS 27.0.1 arm64, Python 3.9.6 and Rust 1.94.1, each case has 24 balanced
fresh-process pairs after warmup. Times are milliseconds; RSS is BSD `time`'s
reported command maximum, not a sum or concurrent process-tree peak.

| Case | Wall median, Python → auto | Wall p95 | CPU median | RSS median (MiB) |
| --- | ---: | ---: | ---: | ---: |
| Inactive JSON | 69.220 → 28.441 | 77.970 → 32.653 | 61.146 → 23.733 | 17.21 → 4.70 |
| Inactive Markdown | 66.660 → 28.557 | 73.500 → 32.515 | 59.887 → 24.012 | 17.13 → 4.70 |
| Settled session | 70.189 → 31.894 | 88.082 → 41.485 | 61.746 → 24.965 | 17.16 → 4.70 |
| Changed Python file | 66.655 → 31.652 | 73.689 → 38.397 | 59.326 → 24.220 | 17.10 → 4.72 |
| Korean/space changed file | 67.494 → 29.248 | 76.325 → 34.262 | 58.509 → 23.833 | 17.13 → 4.74 |
| Active-run fallback | 83.000 → 84.688 | 101.618 → 93.649 | 74.709 → 76.214 | Not compared |
| Symlink fallback | 73.024 → 98.245 | 89.171 → 119.253 | 63.041 → 76.963 | Not compared |

The selected native paths improve wall medians by 53–59%, meeting the 20%/5 ms
target. Active compatibility retains **1.69 ms wall / 1.51 ms CPU overhead**.
Symlink uncertainty still retains **25.22 ms wall / 13.92 ms CPU overhead**:
source validation and a first Git read precede Python's unchanged inspection.
That path is not accelerated. Its safe optimization remains a later target.

The intermediate ASCII-only result also retained a 23.88 ms Unicode fallback
penalty in `.moru/performance/native-next-ascii.json`. The final parser extends
literal paths to remove that common penalty while preserving reference output.
These are separate development snapshots, not repeated timing selection.

The final 22.43-second run is `.moru/performance/native-next.json`, SHA-256
`694182a6fe17282e5e4f2fcb1864527450ac06440e6ae9d146336ad5a2cf1054`.
Its 367 source inputs and all utility hashes match current files. The native
binary is 880,496 bytes, SHA-256
`15918e81811dd1960224121a2126c8ed8e924c834850d239032c0e264f7c9df4`.
The guard still validates 332 Python sources and seven directory shapes.

Verification covers **66 distinct Python tests**, using the 65-test shared
suite plus affected final selectors after the literal-path extension. **16
Rust tests pass**, including six new next/verification unit tests. Consumer
smoke checks pass **27 transported macOS arm64 checks**, using Git-only PATH,
including clean and Korean changed-file JSON/Markdown output. Existing CI adds
the same native-next suite to its four existing hosts; those remote runs, main
integration, publication and global activation are not claimed by this batch.
