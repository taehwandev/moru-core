---
keyflow_id: sys_discovery_entry_performance_batch
status: review
type: ai-generated
---

# Discovery and entry: three reductions in one batch

## Scope and ownership

Baseline is `9e166efd`. Keep this cohesive discovery/entry increment on the
performance branch: two disjoint helpers, parent-owned adapters and one
integration review/local commit. It changes no aliases, dependencies, native
artifacts, ranking rules, traversal limits, default search roots or installation.
The 52-unit inventory remains unchanged.

- AGY supplied `literal_boundary.contains_literal`: find escaped literal names
  with the original ASCII `[a-z0-9_-]` boundary semantics. Normalization and
  generic-name filtering stay in `agent_project_search`.
- Claude supplied immutable `ProjectFacts`: ordered instruction/marker tuples
  collected with the original Path.exists behavior. The discovery scan passes
  these facts to candidate construction instead of probing them again.
- The lead extracted the internal discovery function so entry manifests use
  one normalized registry snapshot for both selection and workspace guidance.
  A new call reads fresh data; nothing is cached across calls.

Both external workers received generic source-free interfaces, returned only
their owned helper and did not claim to execute tests. Parent integration owns
the existing shared files, tests, measurement, evidence and review. Two provider
responses cover this batch, rather than dispatching both providers for each
small item. No overall coordination-time saving was measured.

Owner: literal helper owns containment, facts helper owns existence tuples,
search owns traversal/candidate policy, discovery owns registry/entry orchestration.
Allowed imports: stdlib plus these local helpers. Forbidden in helpers: network,
registry/ranking/traversal decisions, persistent state, caching or provider calls.
Callers/tests: project-discover, agent-entry, test_discovery_batch and existing
discovery/scan tests. Verification: reference equivalence, probe/read counts,
freshness, traversal parity and actual generated-entrypoint comparison.

## Repairs and semantic limits

An unguarded literal loop is slower for a 65,536-character repeated request:
an initial isolated probe measured about 18.89 ms versus 0.69 ms for the original
regex. Production matching therefore retains the original regex for requests
longer than 4,096 characters. The final long-request measurement below verifies
that compatibility path. The threshold selects an implementation, not allowed
request content or project-selection policy.

The original path-only scan still short-circuits after instruction detection;
only the scan-to-candidate pipeline gathers complete facts once. Every probe
uses Path.exists, preserving symlinks, case-insensitive filesystems and errors.
Tuples are converted to the existing candidate lists. The facts object is an
invocation-local observation, not an authoritative persistent index.

Registry consistency is intentional: if the registry changes during one entry
call, the selection and workspace guide now share its first snapshot. The next
call reloads it. Previously those two results could use different reads.

## Final worktree-source measurement

macOS 27.0.1 arm64, Python 3.9.6. Thirty balanced randomized pairs per workload,
prepared bytecode, warm filesystem, unreserved host. Both use the same generated
launcher in a temporary HOME; the reference uses frozen Git source and candidate
uses the checkout. Explicit synthetic roots/registry avoid private configured
scans. Median / p95 milliseconds:

| Fresh process | Reference | Candidate |
| --- | ---: | ---: |
| Small: 8 directories | 63.9332 / 79.0408 | 67.2515 / 86.8448 |
| 600 marked directories, selected | 267.6590 / 296.0070 | 175.7768 / 195.0966 |
| 600 marked directories, ambiguous | 264.6823 / 362.0760 | 177.4651 / 220.5615 |
| File-heavy: 40 directories x 250 files | 79.0615 / 90.1801 | 84.8251 / 96.4949 |
| Entry: 600 projects + 6,000 disabled registry records | 271.9669 / 309.3159 | 177.8063 / 203.4143 |

The three large-candidate paths save about **87.2–94.2 ms median (33.0–34.6%)**,
exceeding the 20% and 5 ms target. Small adds **3.32 ms** median; file-heavy
adds **5.76 ms**. Both tails are slower in this run. These costs are retained;
this is not a claim that all discovery calls improve. The file-heavy path
already contains the previous enumeration optimization on both sides.

Initialized components are separate experiments, not additive attribution:

| Isolated work | Reference median / p95 | Candidate median / p95 |
| --- | ---: | ---: |
| Match 600 distinct names | 28.4333 / 45.7281 | 1.3988 / 2.3237 |
| Scan and construct 600 candidates | 103.8324 / 132.2480 | 90.8686 / 120.2908 |
| Two versus one registry reads | 7.4146 / 15.2597 | 3.5699 / 12.6532 |
| Long repeated request, guarded production matcher | 0.6300 / 1.0460 | 0.6267 / 0.9349 |

The registry component measures only repeated read/parse work, not an isolated
end-to-end registry improvement. Probe/read-count tests tie that work to the
production call path. Do not add these component deltas to predict CLI latency.

## Reproduction and evidence boundary

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_discovery_batch test_agent_project_discovery test_project_directory_scan
PYTHONPATH=scripts:tests python3 -B tests/benchmark_discovery_batch.py --samples 30
```

Current benchmark reproduction puts both source variants in sibling temporary
snapshots and verifies the changed runtime bytes against the checkout. This
controls source location, which differs in the worktree-source table above.
The 20-pair sibling-snapshot run produced the following additional observations
(median / p95 ms); no runtime code changed between these two batches:

| Fresh process, sibling snapshots | Reference | Candidate |
| --- | ---: | ---: |
| Small | 283.2930 / 422.2621 | 299.7312 / 355.2627 |
| 600 projects, selected | 1270.0026 / 1794.4024 | 884.8086 / 1539.1528 |
| 600 projects, ambiguous | 3924.3850 / 6338.3158 | 1547.4122 / 2639.6413 |
| File-heavy | 1037.7111 / 1737.7526 | 1314.2587 / 1794.6432 |
| Entry with registry | 789.8110 / 8014.7478 | 421.4824 / 4492.5624 |

Absolute timings vary greatly across and within these unreserved-host runs.
This follow-up is retained as a sensitivity check, not a new latency promise
or evidence that source location caused the difference. Large-candidate paths
remain faster, while small/file-heavy medians regress in both batches. The
source-location check does not explain or remove that regression. **General
adoption is not accepted**: startup/small-tree cost needs investigation on a
stable host before a main/global rollout. The branch result is limited to a
reviewable candidate with demonstrated large-candidate benefit and explicit
negative controls; no additional timing loop is used to seek a passing result.

It records source/entry hashes, raw samples, exact statuses and output checks.
For agent-entry only, declared source-root metadata paths are normalized; every
other JSON value, pretty formatting, stderr and exit status must match. Source
paths naturally identify the source installation, not the selected project.

An early harness assertion missed macOS `/var` versus `/private/var` aliases;
source roots are now resolved before that narrowly scoped comparison. Results
are persisted after each workload to retain evidence if a later check fails.
The failed pilot is not used as final acceptance evidence.

Raw records are `.moru/performance/discovery-batch.json` (30-pair worktree run)
and `discovery-batch-symmetric.json` (20-pair sibling-snapshot check). Keep them
separate. Final runtime hashes match both; the benchmark hash differs because
the second version controls source location.

The 36 behavior tests include 11 new tests, with 5,013 regex-reference input
pairs, long-input fallback, one metadata probe set per candidate, unchanged
path-only traversal/bounds, registry snapshot consistency and next-call
freshness. Existing discovery and scan tests remain in the focused group.

This remains a performance-branch candidate. Actual global activation, call
frequency, whole-agent/token improvement, cold-cache and network-filesystem
behavior remain unmeasured. No main integration or release is included.
