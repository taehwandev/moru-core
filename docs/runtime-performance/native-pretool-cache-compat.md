---
keyflow_id: sys_runtime_native_pretool_cache_compat
status: review
type: ai-generated
---

# Native pretool developer-cache compatibility

## Failure and correction

The first actual installation check of commit `297c21a5` found a delivery gap:
ordinary `scripts/.pytest_cache` directories in the main checkout caused the
native source guard to select Python. All 329 Python source hashes matched.
The build and installed binary hashes also matched; they did not prove the
installed callback selected native execution. The no-Python check returned 127.

Preserve existing caches. `native_source_inputs.py` now owns one finite list:
`__pycache__`, `.pytest_cache`, `.mypy_cache` and `.ruff_cache`. The generator
embeds the same sorted list in Rust. Snapshot traversal and runtime directory
validation agree about these non-runtime directories. Only actual directories
are exempt at runtime; cache-named directory symlinks, unknown directories, changed
sources and opaque import shadows retain conservative Python fallback.

The new copied-source regression failed on the previous artifact, then passed
for both generated provider entrypoints with caches present and Python/Git
absent from PATH. Adding an unknown directory still forces compatibility.
A second test covers nested cache exclusion from the build-time snapshot.

## Verification and artifact

The affected Python suites passed **48 tests**: source inputs, pretool,
native stable launcher, runtime builder and portable bundle. Rust passed
**nine tests**. The full previous increment's unchanged checks are retained in
the [initial result](native-pretool.md), rather than rerun for reassurance.

The corrected launcher remains 796,704 bytes. SHA-256:
`cb40170eb46682b5a715cbceb85518af790528c32ae62ac8daef0bbf346392b3`.
Its receipt still binds 355 native/build/runtime inputs. No cache was removed,
dependency added, external provider called or existing release asset replaced.

## Matching measurement

The previous artifact's raw results remain in
`.moru/performance/native-pretool.json`. A separate bounded paired run for the
corrected artifact writes `.moru/performance/native-pretool-cache-compat.json`.
Use the same five synthetic workloads, 24 AB/BA pairs each, warm filesystem,
isolated prepared bytecode and macOS process statistics as the initial run.
Fallback RSS is not comparable to the native single-process path. These
measurements do not establish whole-agent memory savings or live call counts.

One completed run took **12.73 seconds** of the 90-second budget, with 240
timed callback invocations and ten warmups. Final source and binary hashes
matched the recorded artifact. Results below compare modes within this run;
the host was unreserved, so differences from the initial run are not a measured
speedup caused by cache exclusion.

Python → Rust/auto, milliseconds:

| Callback | Wall median | Wall p95 | CPU median | CPU p95 |
| --- | ---: | ---: | ---: | ---: |
| Claude status | 62.323 → 19.058 | 67.411 → 28.260 | 56.142 → 16.091 | 61.220 → 17.588 |
| Codex status with transcript | 65.942 → 19.257 | 78.488 → 31.294 | 58.310 → 16.508 | 65.348 → 19.937 |
| Claude cached diff | 64.659 → 18.900 | 75.057 → 23.122 | 56.579 → 16.176 | 64.642 → 18.598 |
| Codex pwd | 64.038 → 19.476 | 75.402 → 29.977 | 56.977 → 16.518 | 59.730 → 19.097 |
| Quoted-query fallback | 62.034 → 64.392 | 70.643 → 70.762 | 55.602 → 57.280 | 57.449 → 59.421 |

Per-process maximum RSS median / p95, MiB:

| Native callback | Python | Rust |
| --- | ---: | ---: |
| Claude status | 21.23 / 21.33 | 2.28 / 2.31 |
| Codex status with transcript | 21.60 / 21.80 | 2.30 / 2.31 |
| Claude cached diff | 21.28 / 21.38 | 2.28 / 2.31 |
| Codex pwd | 21.40 / 21.77 | 2.28 / 2.31 |

The Codex status case reduces median wall by 70.8%, CPU by 71.7% and process
maximum RSS by 89.4%. Quoted compatibility adds 2.36 ms median wall (3.8%) and
1.68 ms CPU (3.0%). Writes and complex commands remain on Python.

```sh
python3 scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_support_native_source_inputs test_native_pretool test_native_stable_launcher test_build_native_runtime test_native_bundle
CARGO_TARGET_DIR=.moru/native/cargo-target cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --samples 24 --budget-seconds 90 --output .moru/performance/native-pretool-cache-compat.json
```

## Acceptance boundary

Local source integration and actual installation require a readback of this
exact artifact, the unchanged main source pointer and both installed callbacks
with Python/Git absent from PATH while the real cache remains present.
Quoted unsupported queries must preserve exact Python output and writes must
retain mutation denial. Portable bundle tests establish packaging behavior;
this increment has no published release or additional-host execution evidence.
