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
marker priority match the reference. Verification file predicates now follow
links as Python does; other metacharacters and uncertain metadata errors remain
on Python. Source, state and lock-path symlink guards are unchanged. Existing reference handling of Git's quoted
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

## Initial next increment measurements (0a28433d)

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
That increment retained **25.22 ms wall / 13.92 ms CPU overhead** for symlinks:
source validation and a first Git read precede Python's unchanged inspection.
This finding motivated the link metadata increment below.

The intermediate ASCII-only result also retained a 23.88 ms Unicode fallback
penalty in `.moru/performance/native-next-ascii.json`. The final parser extends
literal paths to remove that common penalty while preserving reference output.
These are separate development snapshots, not repeated timing selection.

The original 22.43-second run is `.moru/performance/native-next.json`, SHA-256
`694182a6fe17282e5e4f2fcb1864527450ac06440e6ae9d146336ad5a2cf1054`.
Its 367 source inputs and utility hashes matched that increment. The native
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

## Link metadata increment

`reference_is_file` replaces conservative symlink rejection only inside
verification-target discovery. It follows links through the platform metadata
call, matching `Path.is_file`: regular targets are true; directories, missing
targets, non-directory prefixes, bad descriptors and link loops are false.
Other OS errors return to Python rather than silently becoming false. This
preserves version-specific Python handling of permission/IO/overlong-path
errors. It does not read target contents or execute suggested commands.

The file, nearest-test and framework-marker predicates share this helper.
Non-Python changed paths avoid the former redundant prefix scan because the
reference does not inspect their file type. No metadata result is cached.
Source validation, session/registry authority and existing lock-path checks
remain unchanged, including rejection of symlinked state/lock paths.

Before the change, the link-matrix no-Python selector returned 127 while the
Python reference succeeded. Afterward, **21 focused Python tests and 18 Rust
tests pass**. Two new Rust tests directly cover regular/chained/broken/looped/
directory links, non-directory prefixes and uncertain metadata errors. Process
comparisons also cover linked test directories and framework markers. An
overlong-path Git fixture proves exact Python result/error replay. The
transport test packs and installs the actual archive into a different source
root and temporary home, then compares linked-target JSON and Markdown with
Git-only PATH. The consumer needs neither Python nor a Rust toolchain for
those admitted calls; the development comparator still uses Python.

### Link measurements

The same generated-entrypoint protocol now uses nine cases, 24 balanced pairs
each, prepared bytecode and an unreserved macOS arm64 host. The link cases
include the previously created ordinary/Unicode changes and accumulate regular,
broken and looped links. Each Python/auto pair receives identical inputs.

| Case | Wall median, Python → auto (ms) | Wall p95 (ms) | CPU median (ms) | RSS median (MiB) |
| --- | ---: | ---: | ---: | ---: |
| Inactive JSON | 62.965 → 27.794 | 73.522 → 29.034 | 57.177 → 22.747 | 17.10 → 4.70 |
| Inactive Markdown | 64.703 → 28.269 | 69.713 → 31.292 | 58.887 → 23.577 | 17.10 → 4.70 |
| Settled session | 66.019 → 29.093 | 81.336 → 33.481 | 60.021 → 24.165 | 17.16 → 4.72 |
| Changed Python file | 68.494 → 30.476 | 190.066 → 47.295 | 62.441 → 25.123 | 17.15 → 4.73 |
| Korean/space changed file | 65.131 → 28.651 | 67.922 → 32.151 | 59.509 → 23.950 | 17.16 → 4.73 |
| Regular symlink | 64.007 → 28.184 | 67.481 → 30.459 | 58.727 → 23.398 | 17.16 → 4.73 |
| Broken symlink | 65.938 → 28.760 | 71.612 → 33.149 | 60.156 → 24.277 | 17.20 → 4.73 |
| Loop symlink | 64.864 → 28.927 | 73.669 → 32.965 | 59.341 → 24.341 | 17.16 → 4.73 |
| Active-run fallback | 84.410 → 87.872 | 96.420 → 99.731 | 76.428 → 79.460 | Not compared |

The three link cases now execute without Python and improve wall medians by
55–56%, exceeding the 20%/5 ms target. The previous 25.22 ms symlink fallback
is removed for these admitted paths. The old 98.245 ms auto snapshot and the
new 28.184 ms auto snapshot are not a paired causal comparison; the measured
claims above use each run's same-input Python reference. No live-frequency,
whole-workflow or token-saving claim follows from these synthetic checks.

Active-run compatibility remains Python-owned. This run retains **3.46 ms wall
and 3.03 ms CPU overhead** for that path. Its implementation did not change;
this and the earlier 1.69 ms result are separate unreserved-host snapshots.
The high dirty-file p95 is retained rather than rerun or omitted.

The 25.01-second report is `.moru/performance/native-next-links.json`, SHA-256
`116d03be4acaf850506540c2bd5d42f8bb363b74349e5f5b2d19871684002fc6`.
Its 367 runtime sources, utility files and native binary match their recorded
hashes. The measured binary is 880,496 bytes, SHA-256
`4f65423614d9c6f85d215f7aa0b6e5b5a95cf2afc9d178540349510302b78df5`.
Python 3.9.6, Rust 1.94.1, 332 guarded Python sources and seven guarded directory
shapes are unchanged. Original reports remain intact. This increment is local
source/build/transport acceptance; no new remote CI, release or global
activation is claimed.
