---
keyflow_id: sys_runtime_native_pretool_files
status: review
type: ai-generated
---

# Native file-query pretool classification

## Scope and contract

The next ordered increment expands the shared Claude/Codex pretool classifier.
It never executes ripgrep or reads user file contents. It supports closed forms
of `rg --files [paths]`, `rg -n WORD [paths]`, `cat [-n] paths` and
`head [-n COUNT] paths`. Paths use ASCII letters, digits, `_./-`, with no parent
components or leading option marker. Explicit file/directory operands must
resolve. Missing paths, Unicode/quoted operands, other options and shell syntax
remain on Python. `WORD` is ASCII letters/digits/underscore; counts are unsigned
decimal through 1,000,000. At most 20 tokens are eligible.

`pretool_files.rs` owns this grammar and filesystem eligibility behind one
`FileQuery` type. The existing source/environment guard and fallback retain
their contract. Checking every non-option token also covers a local executable
or pattern-named symlink loop that the Python scope resolver can encounter.
Canonical prefix checks treat dangling/looping links as uncertain. Any local
entry with the query executable's name in the candidate or actual process cwd
selects Python: its classifier resolves launcher aliases before consulting the
read-only command list.

Codex can execute in a directory different from the session cwd. Function-call
records validate the candidate workdir; custom-call records conservatively
check every absolute quote-delimited fragment the legacy parser could select.
Quote parity is not trusted; non-directory/error candidates select Python.
Escaped or large custom-call code falls back rather than guessing JavaScript
semantics. The shared native custom-call boundary is 16 KiB/128 double quotes,
also preserving Python path-error diagnostics for existing Git/pwd queries.

## Verification

Before implementation, all 24 admitted-form/provider subcases failed the
no-Python check on the previous binary. The initial implementation passed **53 Python
tests and 10 Rust tests passed** in the affected file/pretool/source/launcher/
builder/bundle suites. The generated entrypoints check 28 supported-form/provider
combinations against exact Python exit/stdout/stderr and with Python absent;
120 unsupported-neighbor/provider cases prove fallback without Python.
Forty-four selected unsupported pairs also compare the real policy result.
This includes `rg --pre`, shell substitutions, command chaining, pipes,
redirections, write options, count limits, Unicode/space paths, environment
overrides, missing files, executable/operand/pattern symlink loops and both
Codex transcript shapes with a different workdir. No query was executed.
An extended admitted-form selector also passed for an absolute ASCII operand
outside the project and a valid symlink into that location.

The initial Rust grammar test made 367 assertions over admitted commands,
generated shell/option neighbors, control characters and malformed limits.
These are assertions inside one test, not independent test cases. Prior
source-hash, opaque-shadow, developer-cache and metadata regressions still pass.

## External review and correction

The user requested actual Claude and AGY reviews before integration. Both
received the same frozen staged patch and returned separate read-only reviews.
Claude's result identifies `claude-sonnet-5-5`; AGY's result does not identify
its model, so no independent-model claim is made. Neither reviewer ran tests;
AGY also checked local build/benchmark provenance. Their outputs are retained
under ignored `.moru/reviews/native-file-queries/`.

The lead reproduced two AGY findings on the initial artifact: a cwd-local
`cat`/`head` symlink to the Moru launcher produced Python policy JSON while
native returned silently; an overlong absolute custom-call workdir produced
a Python error diagnostic that native dropped. Those are actual output
differences. Any local executable entry now selects compatibility, and absolute
custom-call candidates are never filtered away merely because stat fails.
The latter also repairs that diagnostic boundary for existing Git/pwd queries.

Claude found quote-parity uncertainty: a quote in a comment, single-quoted or
template string could hide the selected workdir from alternating-fragment
inspection. The proposed policy-output divergence did not reproduce: both
modes returned silently. The lead did reproduce admission without the intended
filesystem eligibility check. All quote-delimited fragments are now considered;
odd and even shifted-quote fixtures require conservative fallback.

Three new regression methods failed in 12 subcases on the initial artifact,
then passed after repair. The corrected affected suites pass **57 Python tests
and 10 Rust tests**. Coverage now compares all 120 unsupported-neighbor/provider
pairs, checks 32 supported-form/provider combinations plus the 20-token
boundary, 21-token fallback, option-only forms, dangling operands, tab-separated
input, the maximum admitted head count and ASCII DEL. The new Rust grammar
test now has 380 assertions. These results supersede the initial acceptance
counts without erasing the original experiment.

The follow-up also prompted a check of process cwd versus payload cwd. Python's
bare-alias resolver uses its actual process cwd, without a parent-directory
search. A different payload cwd reproduced two more output-divergence subcases.
The guard now requires clear local-executable absence in both contexts. The
new boundary tests pass, including parent-only aliases and relative transcript
workdirs (which Python explicitly ignores). Final coverage is **60 Python tests
and 10 Rust tests**. Both providers inspected the added guard and reported no
blocking finding; reviews remain source-inspection evidence, not test runs.
Claude's nonblocking fixture concern is resolved by the valid payload file in
`setUp` and successful native execution with Python absent.

Error diagnostics are compared against the observed interpreter baseline:
Python 3.14 changed `Path.is_dir()` to suppress OS errors. The test therefore
does not require the Python 3.9 warning on every interpreter. See the
[Python filesystem-status contract](https://docs.python.org/3/library/pathlib.html#querying-file-type-and-status).
This is a portable assertion contract, not a claim of cross-version execution.

## Measurement and delivery

The initial artifact's experiment below is retained. The requested external
reviews found issues before main integration; corrected-source acceptance and
matching-artifact results are recorded separately below.

The matching bounded benchmark uses five file-query/control workloads, 24
balanced AB/BA pairs per workload, isolated prepared bytecode, warm filesystem,
an unreserved macOS host and BSD per-process maximum RSS. It records raw samples
and source/artifact/driver hashes in ignored
`.moru/performance/native-pretool-files.json`. It measures the classifier,
including source verification and path checks, rather than search speed.
Fallback RSS is not a process-tree total and is not compared.

One completed run took 14.69 seconds of its 90-second budget: 240 timed
invocations and ten warmups, with no source or utility hash mismatches. The
796,768-byte launcher SHA-256 is
`f471ea7c440f004050b150b32bdd21c408952d9d06f9ef740f310e8450aba1be`;
its receipt binds 356 build/runtime inputs. The runtime snapshot remains 329
Python files and seven source directories.

Python → Rust/auto; time in milliseconds, RSS in MiB:

| Callback | Wall median / p95 | CPU median | Max RSS median |
| --- | ---: | ---: | ---: |
| Claude file listing | 63.607 / 78.828 → 19.255 / 24.081 | 58.114 → 16.569 | 21.30 → 2.28 |
| Codex search with transcript | 63.605 / 69.337 → 19.512 / 20.594 | 58.647 → 16.779 | 21.60 → 2.31 |
| Claude head | 67.909 / 115.608 → 21.787 / 37.020 | 62.013 → 18.485 | 21.27 → 2.30 |
| Codex cat | 73.211 / 130.502 → 22.388 / 45.756 | 65.544 → 19.192 | 21.57 → 2.30 |
| Quoted compatibility | 65.700 / 86.283 → 69.225 / 83.841 | 60.521 → 63.172 | not comparable |

The Codex search case reduces median wall 69.3%, CPU 71.4% and maximum RSS
89.3%. Quoted fallback adds 3.53 ms wall (5.4%) and 2.65 ms CPU (4.4%). This
does not establish live call frequency, whole-agent memory or model-token
savings; cross-host execution and cold-disk behavior remain unmeasured.

### First review repair artifact

After the review repairs, a separate completed run took **14.52 seconds** with
the same 24-pair design. Raw data is
`.moru/performance/native-pretool-files-reviewed.json`. Source/driver and binary
hashes match, with 356 receipt inputs. The corrected launcher is 796,784 bytes,
SHA-256 `6818579d05dfacaca33be9960959dd9b81d343b00a4de1b2f468748856735500`.

| Callback | Wall median / p95 | CPU median | Max RSS median |
| --- | ---: | ---: | ---: |
| Claude file listing | 76.471 / 106.217 → 23.456 / 38.151 | 69.916 → 19.996 | 21.23 → 2.31 |
| Codex search with transcript | 69.694 / 73.897 → 21.152 / 22.461 | 63.509 → 18.153 | 21.54 → 2.38 |
| Claude head | 70.641 / 77.531 → 21.379 / 23.784 | 64.434 → 18.299 | 21.26 → 2.31 |
| Codex cat | 70.431 / 72.082 → 21.100 / 22.079 | 64.243 → 17.907 | 21.53 → 2.31 |
| Quoted compatibility | 70.230 / 75.685 → 73.767 / 76.733 | 63.932 → 66.558 | not comparable |

Within this run, Codex search reduces median wall 69.6%, CPU 71.4% and maximum
RSS 88.9%. Quoted fallback adds 3.54 ms wall (5.0%) and 2.63 ms CPU (4.1%).
Unreserved-host differences between runs do not measure the causal cost of the
repair. This single matching-artifact run, rather than the faster initial
numbers, supports the corrected implementation's performance claim.

### Final process-cwd artifact

One matching run for the final guard took **15.66 seconds**, 24 AB/BA pairs
per workload, without concurrent tests or reviewer processes. Raw data is
`.moru/performance/native-pretool-files-final.json`; all source/driver hashes
and the binary match. The 796,784-byte launcher has SHA-256
`2a370d6719421681c3cc151d1d83af94eb63d3541cc06ad45704b323a4d21b1e`.
The source receipt remains 356 inputs.

| Callback | Wall median / p95 | CPU median | Max RSS median |
| --- | ---: | ---: | ---: |
| Claude file listing | 77.214 / 90.833 → 23.159 / 31.253 | 65.707 → 19.044 | 21.23 → 2.34 |
| Codex search with transcript | 77.203 / 88.836 → 22.174 / 26.460 | 65.044 → 18.506 | 21.59 → 2.38 |
| Claude head | 72.086 / 86.844 → 22.867 / 35.256 | 65.690 → 18.705 | 21.25 → 2.36 |
| Codex cat | 73.374 / 80.368 → 22.961 / 30.453 | 65.491 → 18.963 | 21.60 → 2.36 |
| Quoted compatibility | 73.070 / 78.921 → 79.782 / 85.776 | 65.007 → 68.208 | not comparable |

Final Codex search reduces median wall 71.3%, CPU 71.5% and maximum RSS 89.0%
within this run. Retain the worse quoted control: +6.71 ms wall (9.2%) and
+3.20 ms CPU (4.9%). Source inspection shows quoted-input rejection and the
Python replay mechanism are unchanged from the preceding callback implementation;
the experiment measures bridge overhead, not a causal cost of the new guards.
Do not select the faster earlier run as final evidence or extrapolate live
workflow savings. Unsupported-input replay remains an optimization candidate.

```sh
python3 scripts/build_native_runtime.py
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_pretool_files test_native_pretool test_support_native_source_inputs test_native_stable_launcher test_build_native_runtime test_native_bundle
CARGO_TARGET_DIR=.moru/native/cargo-target cargo test --locked --offline --manifest-path native/checkout-identity/Cargo.toml
PYTHONPATH=scripts:tests python3 -B tests/benchmark_native_pretool.py --workloads files --samples 24 --budget-seconds 90 --output .moru/performance/native-pretool-files-final.json
```

This is stage one of the user's ordered file-query, prompt-mailbox and Stop
increments. Mailbox and Stop retain Python until their state/acknowledgement
contracts are verified in their own stages. Actual local activation needs a
matching source/receipt/binary readback and an installed no-Python smoke. No
new remote push, release asset or tag is included in this stage.
