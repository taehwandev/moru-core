---
keyflow_id: sys_runtime_evidence_lookup_result
status: review
type: ai-generated
---

# Registered runtime evidence lookup

## Decision and scope

Resolve canonical run evidence directly before recursively discovering legacy
locations. This retains Python and changes only the general session resolver in
`scripts/agent_runtime_session.py`. It is an algorithm improvement, not a Rust
conversion, a cache, or another CLI inventory boundary. The owned-session
fallback resolver, registry format, authority checks and public signatures are
unchanged. Unit 15 (`next`) is an already-counted primary consumer; this increment
does not increase the inventory's ten changed primary boundaries.

The generated next-action entrypoint improves 39.4% (79.14 ms) for 500 history
records and 24.4% (39.35 ms) for 10,000 unrelated cache files. Both selected
synthetic workloads meet the programme's 20% and 5 ms median target. There is
no demonstrated benefit for compact state or custom-location fallback, and
these results do not establish whole-agent speed, token savings or host-wide
performance. Pretool import deferral remains a separate, unimplemented candidate.

## Preservation of decisions

The fast path accounts for **every** registry binding, including peers from
other sessions. It requires a valid opaque run ID, the exact registered key,
a regular non-symlink evidence file, and canonical directories that are neither
symlinks nor nested Git checkouts. Opening each directory preserves rejection
when a known file is reachable but its directory cannot be enumerated. No
directory entries are scanned in the successful fast path.

If any binding cannot be accounted for, the existing discovery algorithm runs
once with its original basename selection, worker separation and completeness
rules. This includes custom, missing, malformed, worker and moved-state claims.
After selection, the existing session/generation checks, ownership-based peer
selection and ambiguity rejection still decide the answer. Sorting direct
candidates preserves recursive ordering when settled timestamps tie. Nothing
is memoized across lookups or authorizations.

The registry still reads and filters its history. Its cost is not constant in
the number of registry records; the reduction removes unrelated filesystem
enumeration. Multiple active claims also increase direct-lookup work.

## Verification

Before changing production code, the canonical-claim test failed on the old
resolver because it called recursive traversal. After the change, eight new
regressions and the existing resolver/registry/worker/next/pretool/stop suites
passed: **359 tests**, no skips reported. These cover exact keys, a canonical
decoy for a custom claim, malformed IDs, missing files, resumed generations,
execute-only directories, nested checkouts, symlinks, active-peer ownership,
settled ties, worker isolation and legacy fallback.
The two inventory coverage checks also passed: **361 unique tests** in total.

The fresh-process public-resolver comparison checks eleven scenarios against
both source variants: compact, history, cache, custom, ambiguity, settled tie,
parent with worker, worker hint, nested checkout, symlink file and moved state.
Every exit code, stdout byte and stderr byte matches the expected answer.
Four scenarios have 24 measured processes per variant, and 24 initialized
samples per variant. A separate operation-count probe shows:

| State | Recursive walk calls | Directory opens | Filenames inspected |
| --- | ---: | ---: | ---: |
| Compact | 1 → 0 | 3 → 3 | 6 → 0 |
| 500 history records | 1 → 0 | 503 → 3 | 506 → 0 |
| 10,000 unrelated cache files | 1 → 0 | 504 → 3 | 10,006 → 0 |
| Custom location | 1 → 1 | 2 → 4 | 6 → 6 |

Parent-owned serial execution avoids concurrent child-CPU accounting and
coordination overhead for this one shared resolver. No external provider,
model call, runtime dependency or private source transfer was used.

## Measured result

Baseline is `24246a961174975350a94b406a16171477af0a83`. The candidate is
the same frozen source with only `scripts/agent_runtime_session.py` replaced;
its SHA-256 is
`2175fdaf6838ae7e4964e59ad2cb130566377b2623d4b8b2b2f2417c294c3d58`.
Both variants share fixtures and a generated temporary-home launcher. The
launcher digest is
`75a97f584c34ece0b75379fd7ab1a2e603459ae41595356c65a30a185396b446`.

Python 3.9.6, macOS 27.0.1 arm64. Each case uses 24 balanced randomized AB/BA
pairs with prepared isolated bytecode and warm filesystem. CPU is serial child
user plus system time. p95 is nearest rank. Temporary HOME/state and synthetic
registry/cache files isolate all checks from real sessions and usage databases.
The 90-second budgets include setup; the component run took 23.33 seconds and
the generated-entrypoint run 32.57 seconds. Partial samples are retained on
failure or budget exhaustion, without retries until a desired timing appears.

The actual temporary launcher runs `next --project <fixture> --format json`
with a synthetic session and **without** `--evidence`. Its output must report
the expected active run and tests gate, and match byte-for-byte between variants.
This exercises ordinary session discovery rather than an explicit-path shortcut.
The auto launcher delegates this alias to Python; no native gain is inferred.

All times below are milliseconds, reference → candidate:

| Generated next path | Wall median | Wall p95 | CPU median | CPU p95 |
| --- | ---: | ---: | ---: | ---: |
| Compact | 119.568 → 120.659 | 132.283 → 155.845 | 111.161 → 111.172 | 120.275 → 129.717 |
| 500 history records | 200.895 → 121.750 | 231.804 → 155.005 | 191.078 → 112.467 | 211.911 → 134.479 |
| 10,000 unrelated cache files | 161.475 → 122.129 | 219.786 → 140.820 | 151.175 → 113.202 | 180.249 → 123.704 |
| Custom location | 124.668 → 128.992 | 166.549 → 173.082 | 114.602 → 117.161 | 137.094 → 138.657 |

Compact state has no measured median gain and a worse observed p95. Custom
fallback is 4.32 ms (3.5%) slower at the median. Initialized custom lookup adds
0.044 ms (7.7%); it still enumerates the same files and opens two extra
directories while rejecting the fast path. These costs are retained evidence,
not an improvement claim. The unreserved host and small single-run sample do
not isolate the cause of tail differences or guarantee other hosts' latency.

| Public resolver component | Fresh process wall median | Initialized wall median |
| --- | ---: | ---: |
| Compact | 60.930 → 60.279 | 0.588 → 0.565 |
| 500 history records | 139.610 → 67.092 | 81.545 → 2.037 |
| 10,000 unrelated cache files | 93.567 → 59.972 | 38.662 → 0.766 |
| Custom location | 61.713 → 63.256 | 0.577 → 0.621 |

Component CPU, p95 and all raw samples are retained separately. These are
different experiments, not additive savings or a causal time series with the
earlier exploration. Full pretool latency, live task frequency, cold-disk
behavior, cross-host execution and installed-runtime activation are unmeasured
by these benchmarks.

## Reproduction and rollback

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_agent_runtime_session_lookup test_agent_runtime_session test_agent_run_registry test_agent_worker_evidence test_agent_next_action test_claude_pretool_gate test_claude_stop_gate
PYTHONPATH=scripts:tests python3 -B -m unittest test_native_stable_launcher.NativeStableLauncherTests.test_inventory_covers_each_unique_entry_owner_once test_native_stable_launcher.NativeStableLauncherTests.test_inventory_covers_all_direct_python_entrypoints
PYTHONPATH=scripts:tests python3 -B tests/benchmark_runtime_evidence_lookup.py --samples 24 --budget-seconds 90
PYTHONPATH=scripts:tests python3 -B tests/benchmark_runtime_evidence_entry.py --samples 24 --budget-seconds 90
```

Ignored `.moru/performance/evidence-lookup.json` and `evidence-entry.json` retain
raw samples, exact-output hashes, runtime/utility hashes and partial-run status.
Public documentation contains no personal paths or real session data. Reverting
this isolated unit restores full discovery; no schema, stored-data, native
artifact, dependency or configuration migration is needed. Source integration,
remote availability and installation remain separate delivery evidence.
