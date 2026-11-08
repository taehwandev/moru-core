---
keyflow_id: sys_native_runtime_migration_inventory
status: review
type: ai-generated
---

# Native runtime migration inventory

Track **56 execution units**: **31 primary runtime units plus 25 ancillary
direct CLIs**. The original 52-unit baseline gains one portable-bundle CLI;
this is delivery tooling and is included in the full migration Goal.
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

The [full migration Goal](runtime-performance/full-migration.md), requested on
2026-11-06, now selects all owned targets in this inventory and their supporting
runtime responsibilities. The [ledger](runtime-performance/migration-ledger.json)
records the complete remaining scope. Current Python/partial states below are
implementation status, not final exceptions. Vendor boundaries remain explicit.

Later units need behavioral parity, a rollback
path and a verified performance-branch commit, with related units batched.
Existing comparisons establish the migration direction; follow the
[programme's selective measurement policy](runtime-performance/prd.md#behavior-acceptance-and-selective-measurement)
rather than benchmarking or calculating cost for every remaining script.
Prioritize frequent callbacks, then finish the lower-frequency owned targets
under that Goal. A unit can require several small commits. Internal helper or
policy splits do not silently increase this inventory; update its scope and
acceptance explicitly. Tests check complete, unique entry-owner coverage.

The product target is convergence of ordinary installed execution on Rust,
starting with frequent callbacks. Python remains transitional compatibility and
verification support; owned developer tools remain in the full Goal scope.

Primary and ancillary labels preserve the inventory's responsibility groups.
Adding a native launcher alias for an existing ancillary tool does not create a
new unit or renumber the inventory; manifest checkers retain units 36–37 and
the offline Figma validator retains unit 40.

The [ls/Git inspection extension](runtime-performance/native-ls-git.md) expands
the two existing pretool boundaries without adding another inventory unit or
claiming a new numerical speedup.

## Coverage and state

The checkout unit is integrated as native source in local main. The common
launcher bridge connects native ingress while retaining Python delegation for
the remaining legacy commands. Two statusline entrypoints share a native
renderer. Python branches remain in partially native pretool, quiet mailbox,
quiet/settled Stop, next and prepared-status paths. Seventeen primary boundaries now have implementation
coverage, all involving native work (including partial entry/discovery,
launcher, pretool, mailbox callback/CLI, Stop, next, status and work-card listing).
The latest native extensions add no new timing claim; earlier measurements remain historical.
The ancillary manifest checker and offline Figma validator engines add
implementation coverage for units 36–37 and 40. The native session aggregation
used by the overhead reporter adds partial supporting coverage for unit 46.
That is 21/56 inventory coverage, including 17/31 primary units, not
effort-weighted completion: 20 are partial and one is locally verified;
34 remain planned and one has an unresolved external
ownership boundary. The earlier
[startup batch](runtime-performance/startup-paths.md) remains below the frequent-path
20% target. The [mailbox batch](runtime-performance/mailbox-paths.md) reaches that
target for quiet prompt delivery only. Main integration and local installation
are now authorized; per-host execution and actual installed state still need
their own readbacks.

The [registered evidence lookup](runtime-performance/evidence-lookup.md) further
optimizes the existing `next` boundary and its shared resolver. It adds no
inventory unit or Rust conversion: generated active-next improves on large
history/cache fixtures, while compact and custom fallback show no benefit.

Unit 46's `measure_session` now requests a source-bound native session tally.
The private probe reads only bounded regular files, replaces invalid UTF-8 and
normalizes universal newlines before parsing JSONL. The adapter validates the
complete result before merging shared counters, preserving replay on decline.
Symlinks, descriptors, streams, unfamiliar datetime grammar, oversized numeric
values and other unsupported input shapes retain Python behavior. Native rows
restore datetime and Counter values at the Python boundary. Native group
statistics, regular timing JSONL, collection/window handling and the installed
`overhead-report` stdout CLI now share the engine. JSON and Markdown rendering
also run natively for supported reports. Explicit output-file effects and
unsupported inputs remain in unit46; this increment claims no measured speedup.
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

The [native completion increment](runtime-performance/native-completion-evidence.md)
adds private Rust policy in gate/checkpoint and finish (units 5 and 4) and extends
Stop. Python retains lifecycle/authority and transport; these remain partial
boundaries rather than complete migrations.

The [ordered query/registry extension](runtime-performance/native-query-registry.md)
adds safe regex/glob and Git query forms to the existing pretool units and
prepared registry reads to the shared session resolver. Transaction ownership
and compatibility remain Python; these helpers add no inventory unit.

| ID | Source owner | Entry aliases | State | Acceptance focus |
| --- | --- | --- | --- | --- |
| 1 | `scripts/checkout_identity.py` | checkout-identity | Native lookup accepted in stage one | Metadata parity, timeout, recovery, Python rollback |
| 2 | `scripts/support/stable_launcher.py` | All entry aliases | Stage-two native ingress bridge | No Python for lookup; legacy stdio/PID/exit/soft-fail parity |
| 3 | `scripts/agent-entry.py` | agent-entry | Partial native shared discovery; Python scope/launch policy retained | One registry snapshot, target/scope and launch-manifest parity |
| 4 | `scripts/agent-finish-check.py` | agent-finish-check | Partial native opt-in requirement coverage; Python lifecycle retained | Admission, freshness, artifact/gate coverage and completion safety |
| 5 | `scripts/agent-hook.py` | agent-hook, cancel, checkpoint, fingerprint, finish, gate, gate-batch, handoff, repair-verify, resume, review, skill-curate, skill-draft, skill-feedback, skill-maintenance, skill-review, start, verify | Partial native quality/requirement checks; Python lifecycle retained | Authority/recording, warning-only lint, stable requirement IDs/revisions and compatibility |
| 6 | `scripts/agent-mailbox.py` | agent-mailbox | Partial native empty-inbox status; Python packets/send/receive retained | Exact counts/output, repository and scan limits; read-only state parity and portable execution |
| 7 | `scripts/agent-os-maintenance.py` | agent-os-maintenance | Python candidate | Owned operator work; preserve effect boundaries during native conversion |
| 8 | `scripts/agent-os-status.py` | agent-os-status | Partial native prepared basic/validated snapshots; Python initialization/trends/fallback | Exact API/metadata/lock parity; warm native status gains about 65-67% |
| 9 | `scripts/agent-os-watchdog.py` | agent-os-watchdog | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 10 | `scripts/agent-preflight.py` | agent-preflight | Python candidate | Admission, state/evidence freshness and completion safety |
| 11 | `scripts/agent_doctor.py` | doctor | Python candidate | Owned operator work; preserve effect boundaries during native conversion |
| 12 | `scripts/agent_execution_capsule.py` | execution-capsule | Python candidate | Admission, state/evidence freshness and completion safety |
| 13 | `scripts/agent_loop.py` | loop | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 14 | `scripts/agent_mailbox_hook.py` | mailbox-hook | Partial native repeated quiet deliver/ack; Python effects retained | Exact output/state parity, unchanged guidance, locked empty queues and conservative replay |
| 15 | `scripts/agent_next_action.py` | next | Partial native inactive advice and safe changed-file verification; Python active-run/evidence lookup retained | Exact JSON/Markdown/state parity; active/uncertain fallback and resource costs |
| 16 | `scripts/agent_project_memory.py` | project-memory | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 17 | `scripts/agent_work_cards.py` | work-cards | Partial native CLI, typed SQLite reads and bounded liveness/recall context; Python writes/recovery retained | Exact values/order, repository/schema/WAL/lock behavior and settlement dispatch; bundled consumer without Python |
| 18 | `scripts/agy_statusline.py` | agy-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 19 | `scripts/claude_continuation_hook.py` | claude-continuation-hook | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 20 | `scripts/claude_pretool_gate.py` | claude-pretool-gate | Partial native plain-query callback | Exact deferral/error/fallback parity; complex/write branches remain Python |
| 21 | `scripts/claude_statusline.py` | claude-statusline | Shared native renderer on performance branch | Repeated-call latency with context/state/delivery correctness |
| 22 | `scripts/claude_stop_gate.py` | claude-stop-gate | Partial native quiet/settled Stop | Preserve active continuation, interruption, legacy edits, indexed projects and mailbox ack |
| 23 | `scripts/codex_operator_review.py` | operator-review | Python candidate | Permission and negative-authority regressions before latency |
| 24 | `scripts/codex_pretool_gate.py` | codex-pretool-gate | Partial native plain-query callback | Codex metadata boundary and no-Python query execution; other branches retain Python |
| 25 | `scripts/codex_stop_gate.py` | codex-stop-gate | Partial native quiet Stop | Exact active evidence/authority handling and mailbox ack through Python |
| 26 | `scripts/project-discover.py` | project-discover | Partial native traversal/facts/root lookup; Python compatibility retained | Same formats/ranking/bounds/symlinks; native-only supported CLI |
| 27 | `scripts/setup-agent-hooks.py` | setup-agent-hooks | Python candidate | Owned operator work; preserve effect boundaries during native conversion |
| 28 | `scripts/workflow.py` | workflow | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 29 | `scripts/workflow_dispatch.py` | workflow-dispatch | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 30 | `scripts/workflow_dispatch_launch.py` | workflow-dispatch-launch | Python candidate | Behavior, failure/recovery and rollback; reuse existing performance evidence |
| 31 | `scripts/agy_hook_adapter.py` | agy-hook | Python retained | Antigravity lifecycle hook ingress; native conversion required by full Goal |

## Ancillary direct CLI coverage

These 25 entries preserve their ancillary inventory classification, including
tools now exposed through installed aliases. The full Goal selects all owned
implementations for conversion. Their existing runtime effects still need the
appropriate invocation authority; the migration does not authorize device
actions, data deletion, paid calls or vendor replacement. Existing performance
evidence is reused; no per-unit profiling prerequisite is imposed.

| ID | Source owner | Entry | State | Disposition |
| --- | --- | --- | --- | --- |
| 32 | `scripts/agent-structure-check.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 33 | `scripts/agent_experience_eval.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 34 | `scripts/agent_unittest_result.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 35 | `scripts/build_native_runtime.py` | Direct CLI | Planned native | Port owned build orchestration; Rust SDK remains developer-only |
| 36 | `scripts/check_android_external_skill_manifest.py` | check-android-skill-manifest | Partial native | Local snapshot comparison and bounded Git identity; exceptional inputs remain open |
| 37 | `scripts/check_react_rn_external_skill_manifest.py` | check-react-rn-skill-manifest | Partial native | Local provenance and source hashes; remote and exceptional inputs remain open |
| 38 | `scripts/device-mcp.py` | Direct CLI | Python retained | Owned protocol boundary; port with fake-device tests before any live effects |
| 39 | `scripts/figma-handoff/figma-handoff.py` | Direct CLI | Python retained | Owned protocol boundary; port with fake-device tests before any live effects |
| 40 | `scripts/figma-handoff/figma_validate.py` | figma-validate; direct reference | Partial native | Offline schema, visibility, coverage, numeric sums and ordinary file errors; parser/exception and imported Python callers remain |
| 41 | `scripts/figma-handoff/live_smoke.py` | Direct CLI | Python retained | Owned protocol boundary; port with fake-device tests before any live effects |
| 42 | `scripts/lessons-compact.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 43 | `scripts/live_device.py` | Direct CLI | Python retained | Owned protocol boundary; port with fake-device tests before any live effects |
| 44 | `scripts/marketing-optimizer.py` | Direct CLI | Python retained | Domain/research tooling; no new model or service calls for this inventory |
| 45 | `scripts/migrate_skill_bundles.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 46 | `scripts/moru_overhead_report.py` | `overhead-report`; direct Python compatibility CLI | Native ordinary stdout CLI, collection, statistics and lossless numeric formatting | Output writers, exceptional statistics/timestamps, text/stdio gaps and direct Python removal remain owned scope |
| 47 | `scripts/mutation-check.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 48 | `scripts/path_claims.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 49 | `scripts/research-triage/microsoft_decision.py` | Direct CLI | Python retained | Domain/research tooling; no new model or service calls for this inventory |
| 50 | `scripts/run_smoke_checks.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 51 | `scripts/runs-prune.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 52 | `scripts/support/codex_statusline_setup.py` | Direct CLI | Python retained | Low-frequency maintenance/setup; explicit effect authorization remains required |
| 53 | `scripts/third_party/wikimap/wikimap.py` | Direct CLI | Python retained | Upstream dependency; retain ownership/license boundary and optimize adapters separately |
| 54 | `scripts/native-runtime-bundle.py` | Direct CLI | Python delivery tooling | Explicit local pack/install, host/source/hash checks; no compiler on consumer |
| 55 | `scripts/page_verify/judge_service.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |
| 56 | `scripts/page_verify/verify.py` | Direct CLI | Python retained | Owned tooling; native conversion required by full Goal |

## Delivery order

1. Checkout lookup: native implementation, direct invocation and compatibility.
2. Common ingress: stable launcher fast path and unchanged legacy delegation.
3. Complete repeated entrypoints next (pretool, status line and mailbox),
   moving policy with its negative tests and reusing existing measurements.
4. Complete installers, maintenance, owned tools and larger state machines in
   cohesive batches. The full Goal covers all owned units and support code;
   ordering by call frequency changes priority, not the completion scope.

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
