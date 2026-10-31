---
keyflow_id: sys_runtime_mailbox_performance_result
status: review
type: ai-generated
---

# Ordinary mailbox startup and repeated identity reads

## Change and decision

Keep validation where explicit task authority is checked; ordinary mailbox
status and new-prompt handling need not eagerly import the full capsule/task
binding stack. The CLI imports its implementation after parsing help.
`AgentMailbox` retains its validator seam through a thin deferred call, with the
same capsule reader implementation and unchanged explicit validation.
`TaskContinuation` imports binding checks at authorize/complete/eligible-continue,
while pause/new-prompt still invalidate unused permission without those imports.

Prompt delivery also queried the same repository identity four times. Open one
existing Git read scope per synchronous `deliver` call and memoize `repository_key`
inside that scope. Outside a scope it still executes normally; the next prompt
opens a fresh scope and queries again. No cross-turn cache or authority change.

Baseline `08c75417` failed all three new import tripwires. After deferral, 115
mailbox/startup checks passed. A separate counter test then reproduced four Git
queries, and passed with one query on each of two successive prompt calls after
the scoped change. Additional delivery/project-memory/Git-scope checks passed.
The guard for new-prompt handling asserts an armed record actually becomes
paused and its budget is removed; swallowed import errors cannot satisfy it.

## Measurement and limits

The first 24-pair import-only screening found status median 92.170 → 91.467 ms,
receive 93.042 → 90.089 ms, quiet prompt delivery 125.748 → 112.953 ms, ack
81.528 → 80.333 ms, mailbox help 74.725 → 49.185 ms, status help control
49.417 → 50.159 ms. It did not establish a frequent-path 20% gain. Raw evidence
is retained in ignored `.moru/performance/mailbox-paths.json`.

After the four-query reproducer, one bounded three-way run compared reference,
that exact import-only intervention and the final scoped implementation. Do not
compare absolute times between these two experiments as a causal time series.
The final run used 24 fresh child processes per variant/case, all six variant
orders balanced, prepared bytecode, warm filesystem and an unreserved macOS
27.0.1 ARM64 host with Python 3.9.6. CPU is child user plus system time.

All measurements use the actual generated temporary-home entrypoint and frozen
sibling sources. Synthetic state, no runtime identities and explicit prompt
payloads avoid real messages or usage databases. The canonical guidance is
copied identically; warmups deliver it once and timed turns are quiet. Timed
stdout bytes, stderr and exits must match exactly, with no normalization.
No import tripwire bootstrap is timed. The auto launcher delegates these aliases
to Python; native-fast-path performance is not measured here.

Each cell is median / p95, milliseconds. p95 is the recorded nearest-rank
statistic from 24 samples, not a host-wide guarantee.

| Wall time | Reference | Imports only | Final |
| --- | ---: | ---: | ---: |
| Mailbox status | 106.738 / 190.572 | 107.453 / 130.891 | 107.850 / 131.730 |
| Empty receive | 105.592 / 146.679 | 104.688 / 115.420 | 104.398 / 171.367 |
| Quiet prompt delivery | 150.023 / 209.052 | 136.414 / 171.364 | 109.626 / 134.880 |
| Empty ack control | 94.596 / 162.903 | 93.948 / 153.880 | 95.721 / 140.282 |
| Mailbox help | 84.880 / 92.868 | 56.276 / 59.435 | 56.026 / 64.461 |
| Status help control | 54.453 / 59.686 | 54.500 / 59.708 | 54.955 / 60.668 |

| Child CPU | Reference | Imports only | Final |
| --- | ---: | ---: | ---: |
| Mailbox status | 97.754 / 132.143 | 97.967 / 110.220 | 97.124 / 115.859 |
| Empty receive | 97.001 / 113.063 | 95.804 / 101.995 | 95.448 / 111.335 |
| Quiet prompt delivery | 134.680 / 164.159 | 121.120 / 151.884 | 96.897 / 114.345 |
| Empty ack control | 87.040 / 119.934 | 85.923 / 119.618 | 86.515 / 119.341 |
| Mailbox help | 78.660 / 85.720 | 50.451 / 53.602 | 50.169 / 56.793 |
| Status help control | 49.009 / 52.306 | 48.842 / 53.132 | 49.389 / 53.052 |

Quiet delivery saves 40.397 ms (26.9%) median wall and 37.783 ms (28.1%) median
CPU against reference. Its wall improvement meets the programme's 20% and 5ms
target for this frequent path. Against import-only it saves another 26.788ms
wall. Status, receive and ack provide no material median benefit; receive p95
is worse than reference. Retain those controls and mixed tails. No whole-agent
speed, model-token saving, cold-disk, peak RSS or cross-host performance is proven.

## Reproduction and ownership

```sh
PYTHONPATH=scripts:tests python3 -B -m unittest test_mailbox_startup_paths test_agent_mailbox test_agent_mailbox_store test_agent_mailbox_reference test_agent_mailbox_task test_agent_mailbox_delivery test_agent_project_memory test_support_git_read_scope
PYTHONPATH=scripts:tests python3 -B tests/benchmark_mailbox_paths.py --samples 24 --budget-seconds 90
```

The second command reproduces the final three-way design, not the earlier
screening. Raw records `.moru/performance/mailbox-scope-paths.json` include full
source/utility hashes, original and intermediate identities, sample arrays,
guidance and launcher hashes, output hashes and complete status. Budget failure
retains partial data; there is no retry-to-pass loop. Native code is unchanged.
Parent owns runtime, measurement, integration and qualified delivery. A native
worker separately supplied portable bundle validation/tests; AGY reviewed only
the local article, not source correctness or execution evidence.
