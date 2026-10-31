---
keyflow_id: sys_native_runtime_migration_inventory
status: review
type: ai-generated
---

# Native runtime migration inventory

Track **52 execution units**: **30 primary runtime units plus 22 ancillary
direct CLIs**. These are inventory boundaries, not 52 mandatory Rust rewrites.
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

This is a candidate inventory. Each later unit needs measured benefit,
behavioral parity, a rollback path and its own verified performance-branch commit.
Low-frequency setup/maintenance may remain Python; do not port them solely to
reach a count. A unit can require several small commits. Internal helper or
policy splits do not silently increase this inventory; update its scope and
acceptance explicitly. Tests check complete, unique entry-owner coverage.

## Coverage and state

The checkout unit is integrated as native source in local main. The common
launcher bridge connects native ingress while retaining Python delegation for
the remaining legacy commands. The performance branch adds the two statusline
entrypoints through one shared native renderer; the other 26 processors retain
Python. This branch result is not a claim of main integration or global activation.
Eight boundaries now have measured changes on or before this branch: four
native boundaries (including the partial launcher) and four Python optimizations
(entry, discovery, status and next). That is 8/52 inventory coverage, or 8/30
primary coverage, not effort-weighted completion or eight accepted migrations.
The remaining 44 are retained candidates, not mandatory ports. The new
[startup batch](runtime-performance/startup-paths.md) remains below the frequent-path
20% target. Installed user-global hooks are a separate rollout boundary from
source integration.

| ID | Source owner | Entry aliases | State | Acceptance focus |
| --- | --- | --- | --- | --- |
| 1 | `scripts/checkout_identity.py` | checkout-identity | Native lookup accepted in stage one | Metadata parity, timeout, recovery, Python rollback |
| 2 | `scripts/support/stable_launcher.py` | All entry aliases | Stage-two native ingress bridge | No Python for lookup; legacy stdio/PID/exit/soft-fail parity |
| 3 | `scripts/agent-entry.py` | agent-entry | Python registry snapshot optimized on performance branch | Entry selection/scope consistency; measured batch benefit |
| 4 | `scripts/agent-finish-check.py` | agent-finish-check | Python candidate | Admission, state/evidence freshness and completion safety |
| 5 | `scripts/agent-hook.py` | agent-hook, cancel, checkpoint, fingerprint, finish, gate, gate-batch, handoff, repair-verify, resume, review, skill-curate, skill-draft, skill-feedback, skill-maintenance, skill-review, start, verify | Python candidate | Admission, state/evidence freshness and completion safety |
| 6 | `scripts/agent-mailbox.py` | agent-mailbox | Python candidate | Repeated-call latency with context/state/delivery correctness |
| 7 | `scripts/agent-os-maintenance.py` | agent-os-maintenance | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 8 | `scripts/agent-os-status.py` | agent-os-status | Python imports deferred on performance branch | Basic/help parity; frequent-path gain below 20% target |
| 9 | `scripts/agent-os-watchdog.py` | agent-os-watchdog | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 10 | `scripts/agent-preflight.py` | agent-preflight | Python candidate | Admission, state/evidence freshness and completion safety |
| 11 | `scripts/agent_doctor.py` | doctor | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 12 | `scripts/agent_execution_capsule.py` | execution-capsule | Python candidate | Admission, state/evidence freshness and completion safety |
| 13 | `scripts/agent_loop.py` | loop | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 14 | `scripts/agent_mailbox_hook.py` | mailbox-hook | Python candidate | Repeated-call latency with context/state/delivery correctness |
| 15 | `scripts/agent_next_action.py` | next | Python imports deferred on performance branch | No-run/help parity; active control unchanged; gain below 20% target |
| 16 | `scripts/agent_project_memory.py` | project-memory | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 17 | `scripts/agent_work_cards.py` | work-cards | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 18 | `scripts/agy_statusline.py` | agy-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 19 | `scripts/claude_continuation_hook.py` | claude-continuation-hook | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 20 | `scripts/claude_pretool_gate.py` | claude-pretool-gate | Python candidate | Permission and negative-authority regressions before latency |
| 21 | `scripts/claude_statusline.py` | claude-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 22 | `scripts/claude_stop_gate.py` | claude-stop-gate | Python candidate | Repeated-call latency with context/state/delivery correctness |
| 23 | `scripts/codex_operator_review.py` | operator-review | Python candidate | Permission and negative-authority regressions before latency |
| 24 | `scripts/codex_pretool_gate.py` | codex-pretool-gate | Python candidate | Permission and negative-authority regressions before latency |
| 25 | `scripts/codex_stop_gate.py` | codex-stop-gate | Python candidate | Repeated-call latency with context/state/delivery correctness |
| 26 | `scripts/project-discover.py` | project-discover | Python enumeration optimized on performance branch | Same selection/order/bounds; measured file-heavy benefit |
| 27 | `scripts/setup-agent-hooks.py` | setup-agent-hooks | Python candidate | Low-frequency operator work; justify a port before changing Python |
| 28 | `scripts/workflow.py` | workflow | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 29 | `scripts/workflow_dispatch.py` | workflow-dispatch | Python candidate | Behavior, failure/recovery, measured benefit and rollback |
| 30 | `scripts/workflow_dispatch_launch.py` | workflow-dispatch-launch | Python candidate | Behavior, failure/recovery, measured benefit and rollback |

## Ancillary direct CLI coverage

These 22 entries sit outside the primary stable-launcher catalog. Inventorying
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
on its integration branch. Subsequent units accumulate there. Main integration
is a separate later decision based on measured usefulness, not an automatic
step after each unit. Push, global installation and releases retain their
separate authorization and verification boundaries.

The alias catalog is single-owned in
[launcher_python.py](../scripts/support/launcher_python.py). The installer and
[native bridge contract](../native/checkout-identity/LAUNCHER.md) define this
stage; this inventory does not replace runtime rules or authorize effects.
