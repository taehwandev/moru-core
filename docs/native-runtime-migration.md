---
keyflow_id: sys_native_runtime_migration_inventory
status: review
type: ai-generated
---

# Native runtime migration inventory

Track **53 execution units**: **30 primary runtime units plus 23 ancillary
direct CLIs**. The original 52-unit baseline gains one portable-bundle CLI;
this is delivery tooling, not another required Rust conversion.
At baseline
`1a61f4be`, the stable launcher exposed 45 alias names backed by 28 distinct
Python entry scripts. Add one common launcher and the checkout-identity unit:
28 + 1 + 1 = 30. The baseline had 321 Python files under scripts; those are
implementation dependencies, not 321 independent rewrite commitments.

The bridge adds checkout-identity as the 46th alias. Its Python compatibility
script belongs to the existing checkout unit, so the primary total stays 30: 29 unique
primary script owners plus the common launcher. Lifecycle aliases share agent-hook.py
and are not counted 17 times. Help flags are not separate migration targets.

The initial count of 30 covered the common launcher's primary path. An AST
scan of all 321 baseline Python files found 48 module-level main guards, with
no parse failures. Combining them with catalog entry owners produces 51 unique
Python execution owners: 29 primary and 22 additional direct CLIs. Add the
common generated launcher to obtain 52. A shebang-only helper such as
workflow_dispatch_cli.py has no execution dispatch and is not a separate CLI.
The other 270 baseline files have no discovered standalone entry boundary;
resolve their supporting ownership with callers when a unit is selected.

This is a candidate inventory. Later units need behavioral parity, a rollback
path and a verified performance-branch commit, with related units batched.
Existing comparisons establish the migration direction; follow the
[programme's selective measurement policy](runtime-performance/prd.md#behavior-acceptance-and-selective-measurement)
rather than benchmarking or calculating cost for every remaining script.
Low-frequency setup/maintenance may remain Python; do not port them solely to
reach a count. A unit can require several small commits. Internal helper or
policy splits do not silently increase this inventory; update its scope and
acceptance explicitly. Tests check complete, unique entry-owner coverage.

The product target is convergence of ordinary installed execution on Rust,
starting with frequent callbacks. Python remains transitional compatibility and
verification support; developer tools need not be rewritten to reach a quota.

The [ls/Git inspection extension](runtime-performance/native-ls-git.md) expands
the two existing pretool boundaries without adding another inventory unit or
claiming a new numerical speedup.

## Coverage and state

The checkout unit is integrated as native source in local main. The common
launcher bridge connects native ingress while retaining Python delegation for
the remaining legacy commands. Two statusline entrypoints share a native
renderer. Twenty-six processors still have Python branches, including two
partially native pretool, quiet mailbox, quiet/settled Stop, inactive-next and prepared-status paths. Fifteen primary boundaries now have implementation
coverage, all involving native work (including partial entry/discovery,
launcher, pretool, mailbox callback/CLI, Stop, next, status and work-card listing).
The latest native extensions add no new timing claim; earlier measurements remain historical.
That is 15/53 inventory coverage, or 15/30 primary
coverage, not effort-weighted completion. The remaining 38 are candidates. The earlier
[startup batch](runtime-performance/startup-paths.md) remains below the frequent-path
20% target. The [mailbox batch](runtime-performance/mailbox-paths.md) reaches that
target for quiet prompt delivery only. Main integration and local installation
are now authorized; per-host execution and actual installed state still need
their own readbacks.

The [registered evidence lookup](runtime-performance/evidence-lookup.md) further
optimizes the existing `next` boundary and its shared resolver. It adds no
inventory unit or Rust conversion: generated active-next improves on large
history/cache fixtures, while compact and custom fallback show no benefit.
The [native pretool batch](runtime-performance/native-pretool.md) adds two partial
Rust boundaries with CPU/wall/RSS evidence and no-Python plain-query execution.
The [file-query extension](runtime-performance/native-pretool-files.md) expands
those same two boundaries; it does not increase the inventory count.
The [native quiet-mailbox extension](runtime-performance/native-mailbox.md)
upgrades the existing prompt boundary; delivery and task effects remain Python-owned.
The [quiet/settled Stop increment](runtime-performance/native-stop.md) adds two
partial boundaries, preserving active work continuity and interruption in Python.
The [Git-inspection and release-consumer batch](runtime-performance/native-pretool-git.md)
expands the existing pretool boundaries and verifies the complete transported runtime.
The [literal-path and guard-profile increment](runtime-performance/native-literal-paths.md)
extends those same queries to quoted/Unicode/space paths without caching validation.
The [inactive-next increment](runtime-performance/native-next.md) moves bounded
read-only advice and safe verification-target discovery to Rust, retaining active-run decisions in Python.
The [shared ARM64 SHA increment](runtime-performance/native-sha.md) accelerates
the existing exact source guard through CPU detection, without caching or new inventory units.
The [read-only inspection batch](runtime-performance/read-inspection.md) extends
native tail/wc/bounded-sed queries and removes mutation/capture imports from
basic status and work-card listing. The latter two remain Python paths.
The subsequent [prepared-status increment](runtime-performance/native-runtime-status.md)
adds real native basic/validated snapshots with existing locks and generated API
snippets. Initialization, contention, trends and unusual inputs remain Python.

The [native project-discovery batch](runtime-performance/native-project-discovery.md)
moves traversal, marker facts and nearest-root lookup into one Rust engine.
The generated discovery CLI and Python entry builder share that engine for
supported inputs. The [registered-project extension](runtime-performance/native-project-registry.md)
adds registered roots, aliases and ordered candidate merging. The subsequent
[workspace-group extension](runtime-performance/native-workspace-discovery.md)
adds group/member candidate lookup; scope/checkpoint guidance and uncertain
path/input forms retain Python. These extend two existing boundaries, without
additional inventory units.

The [explicit request-path extension](runtime-performance/native-request-paths.md)
adds ordinary absolute/current-home path lookup before registered candidates.
Quotes, escapes, unusual whitespace and uncertain inputs retain Python. This
also extends units 3 and 26 without changing inventory coverage counts.

The [native work-card query](runtime-performance/native-work-cards.md) adds
read-only list/list-all execution with bundled SQLite. Internal Python readers,
write/close/resume operations and canonical recovery remain with Python.

The [native mailbox status increment](runtime-performance/native-mailbox-status.md)
upgrades the already-covered mailbox CLI: empty inboxes and acknowledgement
counts run natively; packets, delivery and uncertain state retain Python.

| ID | Source owner | Entry aliases | State | Acceptance focus |
| --- | --- | --- | --- | --- |
| 1 | `scripts/checkout_identity.py` | checkout-identity | Native lookup accepted in stage one | Metadata parity, timeout, recovery, Python rollback |
| 2 | `scripts/support/stable_launcher.py` | All entry aliases | Stage-two native ingress bridge | No Python for lookup; legacy stdio/PID/exit/soft-fail parity |
| 3 | `scripts/agent-entry.py` | agent-entry | Partial native shared discovery; Python scope/launch policy retained | One registry snapshot, target/scope and launch-manifest parity |
| 4 | `scripts/agent-finish-check.py` | agent-finish-check | Python candidate | Admission, state/evidence freshness and completion safety |
| 5 | `scripts/agent-hook.py` | agent-hook, cancel, checkpoint, fingerprint, finish, gate, gate-batch, handoff, repair-verify, resume, review, skill-curate, skill-draft, skill-feedback, skill-maintenance, skill-review, start, verify | Python candidate | Admission, state/evidence freshness and completion safety |
| 6 | `scripts/agent-mailbox.py` | agent-mailbox | Partial native empty-inbox status; Python packets/send/receive retained | Exact counts/output, repository and scan limits; read-only state parity and portable execution |
| 7 | `scripts/agent-os-maintenance.py` | agent-os-maintenance | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 8 | `scripts/agent-os-status.py` | agent-os-status | Partial native prepared basic/validated snapshots; Python initialization/trends/fallback | Exact API/metadata/lock parity; warm native status gains about 65-67% |
| 9 | `scripts/agent-os-watchdog.py` | agent-os-watchdog | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 10 | `scripts/agent-preflight.py` | agent-preflight | Python candidate | Admission, state/evidence freshness and completion safety |
| 11 | `scripts/agent_doctor.py` | doctor | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 12 | `scripts/agent_execution_capsule.py` | execution-capsule | Python candidate | Admission, state/evidence freshness and completion safety |
| 13 | `scripts/agent_loop.py` | loop | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 14 | `scripts/agent_mailbox_hook.py` | mailbox-hook | Partial native repeated quiet deliver/ack; Python effects retained | Exact output/state parity, unchanged guidance, locked empty queues and conservative replay |
| 15 | `scripts/agent_next_action.py` | next | Partial native inactive advice and safe changed-file verification; Python active-run/evidence lookup retained | Exact JSON/Markdown/state parity; active/uncertain fallback and resource costs |
| 16 | `scripts/agent_project_memory.py` | project-memory | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 17 | `scripts/agent_work_cards.py` | work-cards | Partial native read-only CLI; Python internal reads/writes/recovery retained | Exact JSON, repository/schema/WAL/lock behavior; bundled consumer without Python |
| 18 | `scripts/agy_statusline.py` | agy-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 19 | `scripts/claude_continuation_hook.py` | claude-continuation-hook | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 20 | `scripts/claude_pretool_gate.py` | claude-pretool-gate | Partial native plain-query callback | Exact deferral/error/fallback parity; complex/write branches remain Python |
| 21 | `scripts/claude_statusline.py` | claude-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 22 | `scripts/claude_stop_gate.py` | claude-stop-gate | Partial native quiet/settled Stop | Preserve active continuation, interruption, legacy edits, indexed projects and mailbox ack |
| 23 | `scripts/codex_operator_review.py` | operator-review | Python candidate | Permission and negative-authority regressions before latency |
| 24 | `scripts/codex_pretool_gate.py` | codex-pretool-gate | Partial native plain-query callback | Codex metadata boundary and no-Python query execution; other branches retain Python |
| 25 | `scripts/codex_stop_gate.py` | codex-stop-gate | Partial native quiet Stop | Exact active evidence/authority handling and mailbox ack through Python |
| 26 | `scripts/project-discover.py` | project-discover | Partial native traversal/facts/root lookup; Python compatibility retained | Same formats/ranking/bounds/symlinks; native-only supported CLI |
| 27 | `scripts/setup-agent-hooks.py` | setup-agent-hooks | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 28 | `scripts/workflow.py` | workflow | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 29 | `scripts/workflow_dispatch.py` | workflow-dispatch | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 30 | `scripts/workflow_dispatch_launch.py` | workflow-dispatch-launch | Python candidate | Behavior, failure/recovery, measured benefit and rollback |

## Ancillary direct CLI coverage

These 23 entries sit outside the primary stable-launcher catalog. Inventorying
them does not execute them, authorize migrations/deletion/device operations,
or justify rewriting upstream dependencies. They retain Python by default
until a measured bottleneck and a safe owner boundary justify another choice.

| ID | Source owner | Entry | State | Disposition |
| --- | --- | --- | --- | --- |
| 31 | `scripts/agent-structure-check.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 32 | `scripts/agent_experience_eval.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 33 | `scripts/agent_unittest_result.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 34 | `scripts/build_native_runtime.py` | Direct CLI | Python retained | Keep Python build orchestration; Rust SDK is developer-only |
| 35 | `scripts/check_android_external_skill_manifest.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 36 | `scripts/check_react_rn_external_skill_manifest.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 37 | `scripts/device-mcp.py` | Direct CLI | Python retained | External/device protocol boundary; retain Python unless I/O profiling justifies change |
| 38 | `scripts/figma-handoff/figma-handoff.py` | Direct CLI | Python retained | External/device protocol boundary; retain Python unless I/O profiling justifies change |
| 39 | `scripts/figma-handoff/figma_validate.py` | Direct CLI | Python retained | External/device protocol boundary; retain Python unless I/O profiling justifies change |
| 40 | `scripts/figma-handoff/live_smoke.py` | Direct CLI | Python retained | External/device protocol boundary; retain Python unless I/O profiling justifies change |
| 41 | `scripts/lessons-compact.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 42 | `scripts/live_device.py` | Direct CLI | Python retained | External/device protocol boundary; retain Python unless I/O profiling justifies change |
| 43 | `scripts/marketing-optimizer.py` | Direct CLI | Python retained | Domain/research tooling; no new model or service calls for this inventory |
| 44 | `scripts/migrate_skill_bundles.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 45 | `scripts/moru_overhead_report.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 46 | `scripts/mutation-check.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 47 | `scripts/path_claims.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 48 | `scripts/research-triage/microsoft_decision.py` | Direct CLI | Python retained | Domain/research tooling; no new model or service calls for this inventory |
| 49 | `scripts/run_smoke_checks.py` | Direct CLI | Python retained | Operator/test tooling; profile before considering a port |
| 50 | `scripts/runs-prune.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 51 | `scripts/support/codex_statusline_setup.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 52 | `scripts/third_party/wikimap/wikimap.py` | Direct CLI | Python retained | Upstream dependency; retain ownership/license boundary and optimize adapters separately |
| 53 | `scripts/native-runtime-bundle.py` | Direct CLI | Python delivery tooling | Explicit local pack/install, host/source/hash checks; no compiler on consumer |

## Delivery order

1. Checkout lookup: native implementation, direct invocation and compatibility.
2. Common ingress: stable launcher fast path and unchanged legacy delegation.
3. Profile repeated entrypoints next (pretool, status line and mailbox) and
   choose the smallest worthwhile owner; move policy only with its negative
   tests. Do not infer that the table order mandates a full rewrite.
4. Treat installers/maintenance and larger state machines separately, based on
   actual call frequency and compatibility cost.

Performance work now follows the [dedicated performance programme](runtime-performance/prd.md):
isolated change, focused verification, final staged review and a local commit
on its integration branch. The user subsequently authorized main integration,
remote availability and local installation for this accumulated batch. Preserve
negative timing results, Python rollback and per-platform installation evidence.
Later publication or release actions still need their own matching authority.

The alias catalog is single-owned in
[launcher_python.py](../scripts/support/launcher_python.py). The installer and
[native bridge contract](../native/checkout-identity/LAUNCHER.md) define this
stage; this inventory does not replace runtime rules or authorize effects.
