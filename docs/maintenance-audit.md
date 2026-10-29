---
keyflow_id: sys_moru_maintenance_audit
status: review
type: ai-generated
---

# Moru Maintenance Audit

Use these checks for an explicit Moru audit of duplicate reading, memory reuse,
cache freshness, or repeated workflow work. Keep the criteria and findings in
this section so another agent can continue from the same repository evidence.
This is an on-demand reference, not an extra startup read or workflow gate.
[Project instructions](../AGENTS.md) and current source contracts remain authoritative.

Record the source revision, dirty paths, runtime, toolchain, and scope. Inspect
the relevant owner and nearest falsifying check before widening the audit. Use
the required lifecycle before edits; reuse the living task and existing authority.

| ID | Check | What to verify | Owner and nearest tests |
| --- | --- | --- | --- |
| H01 | Document selection | Require command/owner contracts; keep optional links on demand. Count conditional follow-up reading too. | [Router](../scripts/workflow_route.py), [selection tests](../tests/test_workflow_required_doc_selection.py), [project docs tests](../tests/test_agent_project_route_docs.py). |
| H02 | Duplicate reads | Reuse complete unchanged reads before/after start, across worktrees, JSON outputs, split ranges, and compound commands. Count file opens separately from model delivery. | [Delivery](../scripts/agent_required_doc_delivery.py), [reuse](../scripts/agent_required_doc_reuse.py), [delivery tests](../tests/test_agent_required_doc_delivery.py), [reuse tests](../tests/test_agent_required_doc_reuse.py). |
| H03 | Context freshness | Reject changed/deleted/reordered rules, failed or incomplete reads, and pre-compaction coverage. Takeaways must cover credited readings. | Delivery and reuse above; their negative cases. |
| H04 | Memory | Prefer the request's scope; exclude expired, retired, replaced, malformed, and foreign-repository records. Skip oversized records without losing shorter useful ones. Memory never grants authority. | [Memory](../scripts/agent_project_memory.py), [memory tests](../tests/test_agent_project_memory.py). |
| H05 | Cache validity | Invalidate changed source/rules/checker inputs; reuse identical inputs. Check same-status and preserved-metadata changes, staging, Unicode paths, and symlinks. | [Audit cache](../scripts/agent_vibeguard_cache.py), [graph cache](../scripts/workflow_doc_graph_cache.py), [audit tests](../tests/test_agent_vibeguard_cache.py), [graph tests](../tests/test_workflow_doc_graph_cache.py). |
| H06 | Lifecycle work | Lookup creates no task state or index refresh. An unchanged action does not repeat start, passed checks, review, or finish. | [Lookup](../scripts/agent_lookup_start.py), [lookup tests](../tests/test_agent_lookup_start.py), [continuity tests](../tests/test_agent_work_continuity_start.py), [E2E smoke](../scripts/run_smoke_checks.py). |
| H07 | Authority and isolation | Reuse scope-matched authority; protect exact repository/worktree/session/effect. Denied, foreign, diverged, and post-finish writes remain denied. | [Identity tests](../tests/test_agent_worktree_identity.py), [finished integration tests](../tests/test_finished_worktree_integration.py), [read-only tests](../tests/test_read_only_lifecycle.py). |
| H08 | Verification truth | Reproduce the actual condition, verify it after repair, and retain negative controls. Never report a failed wrapper or partial suite as passing. | [Verification contract](../common/skills/verification-policy/references/current-guidance.md), affected owner tests, and smoke's rejection check. |
| H09 | Runtime wiring | Resolved launcher/root and exact worktree targeting are correct; supported Claude/Codex payloads reach the protected boundary. Inspect without reinstalling. | Delivery tests above, [Codex cwd tests](../tests/test_codex_exec_workdir.py), [continuation hook tests](../tests/test_agent_hook_continuation.py). |
| H10 | Measured efficiency | Separate selected bytes, actual reads/delivery, checker calls, and elapsed time. Compare identical inputs; do not estimate token or latency savings. | Owners above, [status snapshot](../scripts/agent_observability.py), [snapshot tests](../tests/test_agent_observability.py), [overhead report](../scripts/moru_overhead_report.py), [report tests](../tests/test_moru_overhead_report.py), controlled probes. |

## Verification And Maintenance

### Per-call carried-context measurement (H10)

Use local transcripts only; record runtime/version, source revision, date
window, included session/call counts and exclusions. Keep raw data and paths
untracked, and print numeric aggregates only. Do not send transcripts to APIs.

For Claude JSONL, skip `isSidechain` entries and deduplicate assistant messages
by `message.id` within each session (streamed blocks repeat the same call).
For each call with valid numeric usage, context is `input_tokens` +
`cache_creation_input_tokens` + `cache_read_input_tokens`; output tokens are
excluded. Missing usage is unknown, not zero. Do not add cache creation's
duration breakdown again. Retain chronological call values and compaction
boundaries. The [existing overhead parser](../scripts/claude_transcript_overhead.py)
illustrates message deduplication; its session totals alone are not a per-call
distribution. Codex adapters must use per-call input usage (already including
cached reads), not cumulative session totals, and report a separate cohort.

Report mean, median and p90 context, plus both call share and input-token share
above fixed thresholds such as 200K, 300K and 500K: `count(c > t) / count(c)`
and `sum(c for c > t) / sum(c)`. State missing-usage coverage and sampling
filters. For output hygiene, measure tool-result character lengths separately;
characters are not tokens. Report the count share, character share and excess
characters above a cap such as 4,000, without printing result bodies.

A cap/reset simulation must state its assumed post-compaction size and handle
observed compactions as new segments. It models potential input reads only;
it does not measure summary quality, elapsed time, billed cost or actual savings.
Use matched before/after tasks with quality checks before claiming improvement.

The [finish nudge](../scripts/agent_finish_context.py) uses the latest assistant
usage at a successful task boundary, with a default 200K threshold, not summed
session usage. It reads at most the final 1 MiB of the exact Claude session's
transcript under `CLAUDE_CONFIG_DIR` (default `~/.claude`); unknown, ambiguous,
pre-compaction-only or other-runtime context stays silent. This is an optional
early reminder for the shared ~250K rule, not a gate or automatic compaction.

Run from the exact target checkout. The following selected suite was used for
the initial audit; later changes use the affected owner's checks rather than
automatically rerunning everything:

```bash
PYTHONPATH=tests:scripts python3 -m unittest \
  test_workflow_required_doc_selection test_agent_project_route_docs \
  test_agent_start_guidance test_agent_required_doc_delivery \
  test_agent_required_doc_reuse test_agent_project_memory \
  test_agent_vibeguard_cache test_workflow_doc_graph_cache \
  test_agent_lookup_start test_read_only_lifecycle test_agent_observability \
  test_codex_exec_workdir test_finished_worktree_integration \
  test_agent_worktree_identity test_agent_hook_continuation \
  test_agent_work_continuity_start
```

Use the [local E2E command above](../README.md#local-hook-testing) for lifecycle integration.
It checks start, weak-evidence rejection, a valid gate batch, finish, and search.
Keep fixture evidence outside the read-only source snapshot, such as in ignored
`.moru/` state. Real source drift must still fail verification.

Keep H01–H10 stable and extend the relevant row before adding a new failure
class. Each finding needs an ID, priority, source owner, reproduction condition,
observed/expected behavior, next proving check, and disposition. Retain before
and after evidence when resolving it. Record each audit's revision and limits;
carry untouched findings forward as historical evidence. Keep raw transcripts,
secrets, local memory bodies, and run-state files untracked.

Stop dependent work on a failed required gate, missing authority, unresolved
owner, or missing required source. Follow the existing repair contract. Passing
selected tests does not establish whole-system health or measured efficiency.

## Security inspection refresh: 2026-10-26

Baseline `7df738a5` plus the recorded reference, validator and guidance repairs.
The [dated inspection report](security/skillspector-2026-10-26/README.md) owns
the raw scanner results, source hashes, contextual dispositions and tests.

| ID | Priority | Finding and disposition | Verification / next check |
| --- | --- | --- | --- |
| S01 | Medium | Ambiguous claim that later hooks never refuse could obscure safety checks; clarified as legacy path compatibility only. | Targeted rescan removed AR1 and changed DO_NOT_INSTALL to CAUTION; authority and gate requirements remain explicit. |
| S02 | Medium | Two missing-binary fallback references permit unpinned package execution; open under current managed runtime policy. | Resolve explicit package-pinning policy before claiming remediation. |
| S03 | Medium | Four document surfaces generate seven parser/reconstruction warnings; 56 bundle analyses remain partial. | Two design bundles changed concurrently in main and were rescanned; retain partial results and require compatible coverage or justified independent checks. |
| S04 | Medium | 51 relative references and 34 obsolete bare skill names were stale after the bundle migration. Intermediate suffix-only triage falsely accepted 32 records. | Canonical paths now resolve literally; all internal-reference dispositions record source spellings and hashes. A suffix-only record is rejected by the independent verifier. |
| S05 | Medium | The review checker ignored backtick relative paths and the product-pattern root. | Two relative-path tests and one product-root negative control fail before repair; all 31 reference tests pass after repair. |

## Audit: 2026-10-02

Source baseline: `d074b64f9934587bd0593a2e153cc186e5be5556`. Environment:
local macOS checkout, Codex, Python `3.9.6`. This agent-generated audit covers
H01–H10 using selected source/test contracts, temporary probes, installed-root
inspection, and E2E smoke. It is a focused audit, not the full repository suite
or a live Claude session.

- The 16-module command above passed **282 tests**, exit `0`, `99.532s`.
- The follow-up documentation/routing suite passed **154 tests**, exit `0`,
  most recently `9.767s`: `test_workflow_required_doc_selection`,
  `test_agent_project_route_docs`, `test_agent_start_guidance`,
  `test_workflow_doc_graph_cache`, `test_agent_lookup_start`, and
  `test_read_only_lifecycle`, with the same `PYTHONPATH` and unittest runner.
- E2E initially exited `1`; after F01's repair, all **5 stages passed**, exit `0`.
- **4 temporary observational probes passed**, exit `0`, `0.195s`. They confirmed
  the costs and edge case below; they are not acceptance tests closing F02/F03.
- Documentation integration initially failed on two example targets treated as
  real links; describing their target names removed those broken links. Final
  validation passed **185 workflow references, 386 Markdown frontmatter/link
  checks, and 28 route contracts**. Two focused document checks passed, including
  **33 relative links** and the shared agent entrypoint.

Selection profiles used `resolve_docs(command, None, [], surface_paths=owners,
project_root=ROOT)`. These measure selection, not task admission. Byte totals
are unique `required_docs` file sizes before history reuse and follow-up reads.

| Command | Owner input | Required docs | Selected bytes |
| --- | --- | ---: | ---: |
| `small-change` | none | 2 | 6,705 |
| `small-change` | `README.md` | 7 | 58,084 |
| `small-change` | `scripts/agent_required_doc_delivery.py` | 8 | 74,507 |
| `commit` | none | 2 | 6,803 |

No comparison measured end-to-end latency, tool-call totals, token usage, or
whether real recalled notes reduced exploration. H09 verified local root/cwd
wiring and tested payload shapes; it did not verify a live Claude session.
Results below retain these limits; tests passing does not close the findings.

## F01: E2E Smoke Changed Its Read-Only Fixture

P1 for the advertised smoke command; **resolved in this change**. Owner:
[test_gate_validation_success](../scripts/run_smoke_checks.py). At the baseline,
`python3 scripts/run_smoke_checks.py` writes `smoke-gates.json` into the
temporary source root after a read-only triage start. Finish rejects that
untracked-file drift and the command exits `1`.

The repair places the batch in the fixture's ignored `.moru/` directory. The
same E2E command then passes all five stages with exit `0`, preserving source
drift validation and the weak-evidence rejection control.

## F02: Delivery Reopens Content It Already Has Or Can Skip

The follow-up repairs below use the combined Codex/Claude baseline `180bb39`.

P2 efficiency; **resolved**, H02/H10. Owner: `delivery_text`, `_read_in_context`,
and `_render` in [delivery](../scripts/agent_required_doc_delivery.py). Reproduce
with [DeliveryTests](../tests/test_agent_required_doc_delivery.py)'s existing
empty transcript and two required documents. Count `Path.read_text` calls for
those document paths while invoking `_deliver()`.

At the audit baseline, each unread document was opened **twice**, for transcript
comparison and rendering. A second delivery opened neither document. Controlling
`required_doc_reuse` to prove both documents reusable still opened each **once**,
while delivering no text. This is local file I/O, not duplicate model context
or a measured latency regression.

The repair excludes proven-reused documents before transcript verification and
shares one content buffer between comparison and rendering. The delivery suite
now passes **30 tests**: one content open per unread document, zero per
proven-reused document, and zero after the marker. Five new regression cases
failed before the repair; freshness, partial-read and compaction controls pass.
These counts cover document content reads, not lifecycle-evidence file reads.

## F03: Restored Metadata Can Hide A Document-Graph Change

P2 correctness edge; **resolved for the reported rewrite**, H05. Owner:
[document_key](../scripts/workflow_doc_graph_cache.py). In a temporary
`.moru`-enabled fixture, build a graph from a Markdown link to `alpha.md`, replace
its target with equal-length `omega.md`, and restore the original `st_mtime_ns`
using `os.utime`. Clear only the in-process graph cache, then build again to exercise
the persisted cache.

At the audit baseline, the returned edge still pointed to **alpha.md**. Advancing
the mtime and clearing the in-process cache rebuilt it with **omega.md**. The key measured document
path/size/mtime, symlink identity, and builder content, rather than document
contents. The repair adds `st_ctime_ns`, device and inode to the same stat-based
key. The graph suite now passes **24 tests**, including persisted-cache
in-place rewriting, atomic replacement, unchanged-input hits and zero document
content opens while keying. Four regression assertions failed before the fix.
Metadata-only caching still cannot detect an in-place change that leaves every
key field identical at the filesystem's timestamp precision; this is not a
content-hash guarantee.

For acceptance that must detect this case, compare the cached graph with a
graph rebuilt directly from the document contents. The repeatable diagnostic
below checks that comparison and includes a synthetic frozen-metadata
counterexample: cached `alpha.md` remains stale, while an uncached rebuild and
content hashing detect `omega.md`. Normal metadata still invalidates the entry.
The default metadata cache is retained; a content hash on every lookup would
read the whole corpus again. This diagnostic does not add a production strict
mode or guarantee that every ordinary cached lookup verifies content.

## F04: Small-Change Owner Guidance Still Has A Large Read Surface

P3 optimization investigation; **partially improved; broader investigation open**,
H01/H10. Owners: the
[router](../scripts/workflow_route.py), [surface rules](../workflow-doc-surfaces.json),
and selected guidance. The measured README and runtime-script profiles above
select **58,084** and **74,507 bytes**. This does not establish irrelevance:
verified owner contracts still apply and some readings may already be retained.

The follow-up inspected `required_doc_reasons`: delivery/reuse inherited CI/CD
guidance from the broad `workflow_router` path rule, although neither owner
defines CI checks, release pipelines or scheduled automation. A specific
`required_doc_context` rule preserves scripted workflow, lifecycle and recovery
guidance without that unrelated card. The same delivery-owner profile now
selects **7 docs / 69,386 bytes**, a reduction of **5,121 selected bytes**.
Mixed delivery/workflow changes still require CI/CD guidance. The surface suite
passes **74 tests**, with both owner-only negative controls failing before the
rule split. README's profile remains **7 docs / 58,084 bytes**; its applicable
documentation/source/writing contracts were retained. These are selection
measurements, not actual model reads or latency savings. Further splitting
requires a source-backed owner and conditional-read accounting.

### Measured File Reads And Timing: 2026-10-02–03

Reproduce with [the isolated benchmark](../tests/benchmarks/document_loading.py):

```sh
python3 tests/benchmarks/document_loading.py --revision 95b02f5
```

The benchmark archives the same `95b02f5` document corpus into temporary
directories and restores only delivery code and surface rules from `180bb39`
in the baseline copy. Both variants therefore read identical guidance content.
It makes no model or network calls and does not reset the live graph cache.
Raw samples and counted paths are written to ignored
`.moru/performance/health-measurements.json`; archive creation, fixture setup and
marker removal are outside the timed actions. Read counters run separately
from timing. The measured environment was macOS 27.0.1 arm64, Python 3.9.6,
with warm OS file caches: 10 warmups and 200 samples per action, plus 20 fresh
processes per variant. Corpus keying first warms the builder-code digest.
The tables report the second run; the repeatable command stores its own latest
samples, so subsequent runs need not reproduce the same timings.

| Action | Content opens before → after | Bytes read before → after | Median before → after |
| --- | ---: | ---: | ---: |
| Deliver seven unread docs | 14 → 7 | 138,792 → 69,396 | 1.768 → 1.598 ms |
| Seven docs with completed-run reuse proof | 7 → 0 | 69,396 → 0 | 1.255 → 0.642 ms |
| Already delivered in this run | 0 → 0 | 0 → 0 | 0.027 → 0.028 ms |
| Complete reads in transcript, without run-history reuse proof | 7 → 7 | 69,396 → 69,396 | 2.005 → 2.038 ms |
| Warm routing plus complete selected-doc reads | 28 → 26 | 258,213 → 248,671 | 2.855 → 3.038 ms |
| Fresh-process routing plus complete selected-doc reads | 187 → 185 | 468,902 → 459,360 | 52.272 → 52.603 ms |

Routing counts include every observed Markdown/surface-map content read inside
the resolver as well as explicitly reading each required document once. They
are larger than the selected-doc count: repeated metadata/entrypoint reads
remain, including four opens each for the scripted-workflow and lifecycle
entrypoints on the warm path. File reads dropped, but F04 showed **no latency
improvement** in this measurement. Fresh-process wall time including Python
startup/imports was 151.781 → 151.046 ms. Selected files were 8 / 74,517 bytes
before and 7 / 69,396 after; the older audit's byte totals used earlier guidance.

A first independent run measured unread delivery at 1.758 → 1.269 ms and
proven reuse at 1.268 → 0.640 ms, while fresh routing/read time was
55.009 → 55.593 ms. Variation between runs matters at this scale; these are
local subsystem observations, not a guaranteed speedup percentage.

| F03 key strategy, same 386-document corpus | Corpus/map opens | Bytes read | Median / p95 |
| --- | ---: | ---: | ---: |
| Existing metadata key | 0 | 0 | 2.898 / 3.083 ms |
| Counterfactual full-content hash on every key calculation | 387 | 2,304,078 | 23.964 / 26.132 ms |

The hash comparison measures key construction, not graph rebuild time. The
isolated persisted graph also matched an uncached source rebuild: 386 nodes,
3,512 edges. F03's remaining metadata limit is explicitly reproduced rather
than claimed fixed. F04's local file-read/timing gap is now measured; model
context actually consumed, conditional guidance reads, tool transport, token
usage and end-to-end session time remain unmeasured. Use source-backed evidence
before removing more guidance or caching repeated resolver reads.

The same follow-up fixes the hash-based fixture in
[runs-prune tests](../tests/test_runs_prune.py): `PYTHONHASHSEED=240` reproduced a
directory collision before repair; ordinal phase IDs then passed all **22
tests** with that same seed. No run-retention policy was changed.

## Audit: 2026-10-02, Feature QA

Source baseline: `d074b64`. Environment: Claude Code, Python `3.9.6`, a detached
checkout with temporary HOME/state directories. Ten feature areas (install,
router, lifecycle, continuation, safety gate, doc delivery, collaboration,
memory and cards, VibeGuard and release, runtime adapters) were each checked
against README/AGENTS/reference promises by running CLIs, hooks or focused
tests, with reported outcomes of 112 pass, 4 unverified, and 9 fail. Each failure
was reproduced again by an independent agent; one turned out to be a stale fixture rather than
a product failure. After the repairs below, the full `discover -s tests` suite
ran **3776 tests** (**3775 passed**, 1 skipped).

All resolved in this change except F11, which is docs-only by decision:

- **F05** README's direct `workflow route product|feature|docs-review`
  diagnostics needed an intent envelope. Examples now show only routes that run
  bare, with the requirement stated.
- **F06** The one-public-owner review budget does not count lowercase Python
  functions. AGENTS.md now defines what an owner is.
- **F07** A failed `verify` printed a repair-verify instruction but recorded no
  failed checkpoint (`checkpoint_not_failed`). It now records `tests` with a
  stable signature ([verification hook](../scripts/agent_verification_hook.py)).
- **F08** `git --version`, `-v`, `--help` and `git version` were denied in a
  protected checkout as Git writes. They now count as reads; `--exec-path=<dir>` does not
  ([classifier](../scripts/claude_bash_git.py)).
- **F09** Deleting a protected branch on the remote (`push --delete main`,
  `:main`) got no hook question. It now asks, in the protected checkout and in
  linked worktrees. Other deletions still defer to Claude's own prompt.
- **F10** In a protected checkout, `rm`/`mv`/`sed -i` defer instead of being
  denied, as designed. The safety-gate docs now say so.
- **F11** On Codex, deferred commands pass silently because Codex has no native
  ask. This behavior is kept by decision, and the docs describe it.
- **F12** `setup-agent-hooks` run under a redirected HOME bootstrapped the
  account's real `gui/<uid>` maintenance agent, pointing it at the sandbox
  checkout. It now skips launchctl unless HOME is the account home
  ([scheduler](../scripts/support/maintenance_scheduler.py)).
- **F13** Stale tests: the parser-parity fixture for `command -v git` and the
  quoted-commit-message test that still expected a deny.

Unverified in that run (permission classifier or gate refusals, not failures):
`agent-os-status --validate`, the maintenance/watchdog CLIs, the
mailbox/handoff/dispatch suites, and pre-commit audit reuse.

## Audit: 2026-10-07, Figma And PR Follow-Through

Source baseline: `129d256567d1fabacbaa72a0036e3346d7ce095b`. Environment:
Codex on macOS, isolated Moru task checkout. Scope: the Figma command boundary
and the agent's follow-through on one resource-copy change and its requested PR.
This does not migrate or reinstall the active runtime, alter the product
repository's policy, or establish full visual parity.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F14 | High / H07, H09 | The canonical Figma interpreter operand and URL query were treated as local write paths. Even dry-run required another repository's writable lifecycle. A bytecode-free dry-run should be a read; extraction should protect its output, not require authoring the tool checkout. | [Figma classifier](../scripts/claude_bash_figma.py), [regressions](../tests/test_claude_bash_figma.py). Two new tests failed before the repair; canonical CLI operand roles now resolve the false targets. Unknown tools/options and protected output writes remain conservative. |
| F15 | Medium / H06 | PR lookup was invoked with `--check` after other options, but the project's explicit non-publication prefix places it immediately after the script. This was an agent invocation error, not a missing publication exemption. | [Prefix contract](../scripts/claude_worktree_gate.py), [longest-prefix tests](../tests/test_claude_worktree_gate.py). Use the repository's declared lookup form; do not reorder arbitrary script arguments or infer safety from the spelling of a flag. Existing tests passed. |
| F16 | Medium / H02, H10 | The agent asked for design text despite having the Figma link, stopped before supported recovery, reread unchanged guidance, and exported 142 assets for one copy change. These were avoidable execution decisions; no comparable latency benchmark was collected. | Existing operating-skill persistence/reuse rules already cover the first three. Figma guidance needs a bytecode-free invocation and bounded extraction for copy-only work. No end-to-end speedup is claimed. |
| F17 | Medium / H07, H08 | A required product pre-push structure check found inherited upstream debt. Publication authority did not authorize changing its frozen baseline; a separate baseline approval remained necessary. | Product-owned audit and approval rule remain authoritative and unchanged by this Moru repair. Anticipate required publication checks when preparing the concrete PR unit; a failed check must not be bypassed. |
| F18 | Medium / H06, H07 | Staged canonical maintenance rejected a Moru task worktree target as `maintenance_target_mismatch` when `--rules` still named the main checkout. The task worktree is a canonical source owner in the same repository, not a foreign product-local skill. | [Maintenance owner](../scripts/agent_skill_maintenance.py), [identity controls](../tests/test_agent_skill_maintenance.py). Canonical bundles now require matching Git common directories, exact checkout roots, a linked `.git` file, bundle provenance and containment. Foreign repositories, subdirectories, missing bundles and symlink escapes remain refused. The live maintenance step completed using the actual canonical task worktree as its rules owner. |

The copy implementation and product PR were ultimately completed. The delays
came from both a missing Figma command contract and agent decision errors.
The auxiliary no-source-change extraction run was unnecessary; removing the
false tool-repository target avoids it without weakening the empty-code-review
guard. Keep required approvals, isolation, lifecycle gates, and publication
checks intact.

Verification: **173 tests passed**, exit `0`, with `python3 -B -m unittest`
over `tests.test_claude_bash_figma`, `tests.test_claude_bash_readonly`,
`tests.test_claude_worktree_gate`, `tests.test_claude_pretool_target_protection`,
`tests.test_claude_shell_parser_parity`, `tests.test_figma_cli`,
`tests.test_figma_validate`, `tests.test_agent_skill_maintenance`,
`tests.test_agent_skill_learning`, and `tests.test_agent_skill_hooks`. These cover
the actual CLI dry-run's lack of output, argument-grammar drift, source-operand
exemption, canonical maintenance identity, and negative protection cases.
Canonical Figma guidance was staged and its maintenance verifier passed the
focused unittest selector before marking the change applied. These are not the full Moru suite or
a new live Figma API/network test.

## Audit: 2026-10-09, Native Integration Latency

Source baseline: `52c5d70`; integrated base: `a6f124b`. Environment: Codex on macOS, isolated Moru task
checkout. Scope: one native desktop material change's recorded elapsed time,
scoped commit preparation, and finished-run denial diagnostics. The live Moru
checkout also had unrelated edits in `scripts/workflow_validate.py` and
`tests/test_workflow_catalog.py`; this audit neither includes nor changes them.
Raw session records and the derived timeline remain local, untracked evidence.

The selected request-to-commit interval was **53m 58.535s**; the final response
arrived after **54m 28.169s**. Contiguous milestone intervals were:

| Phase | Elapsed |
| --- | ---: |
| Intake and preparation | 1m 43.612s |
| Native rendering and input diagnosis, fixes | 30m 06.528s |
| Broader regression checks | 8m 34.821s |
| Golden approval, update and verification | 2m 53.714s |
| Final build, documentation and lifecycle checks | 6m 50.523s |
| Commit-boundary recovery and commit | 3m 49.337s |
| Post-commit verification and response | 29.634s |

These intervals describe milestones, not exclusive causes. The **24 recorded
Moru hook invocations consumed 26.262s** of checker time. **21 Gradle outcomes**
included **14 failures and 7 successes**; 20 reported build durations totaled
**204s**, with one compile failure missing a duration. Two escalation-request
to prefix-record windows totaled **4m 23.830s**, overlapping other work; they
do not establish that a human approval dialog was visible or waiting.

**36m 32.202s** falls outside the recorded foreground tool, asynchronous Gradle
and escalation-observation windows. That time is unclassified: the records do
not separate model inference, transport, other activity, or polling delays.
It must not be attributed to Codex service latency or Moru computation. No token
usage or end-to-end before/after speedup was measured.

| ID | Priority / check | Reproduction and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F19 | Medium / H06, H07 | A completed review of an explicit pathspec, including the original 141-path unit, could not reuse commit-ready evidence. The helper accepted only whole-tree reviews even though the snapshot already bound the scope and path list. Eligible scoped evidence should be reusable with the same literal scope, ordered paths, complete index coverage, session, authority, rules and unchanged full snapshot. | [Commit preparation](../scripts/agent_commit_ready.py), [normalized-scope regressions and negative controls](../tests/test_agent_commit_ready.py), [canonical contract](../workflows/skills/review-and-commit/references/current-guidance.md). Repaired in this change. The public CLI normalizes working-tree plus explicit paths to pathspec; regression fixtures use that literal scope and exercise its preparation owner, rather than launching a new CLI process. Unrelated unstaged content may remain unchanged; selected unstaged content, foreign staging, or any snapshot drift must prevent reuse. |
| F20 | Medium / H06, H07, H09 | A local commit with failed current finish proof was reported as an older paused-run problem. The open-run publication classifier intentionally excludes local add/commit; reusing it for finished-run mismatch detection hid the actual changed inputs or insufficient effect. The refusal should identify the current proof failure without asking to resume the superseded pause. | [Entry gate](../scripts/claude_pretool_gate.py), [finished effect detection](../scripts/claude_pretool_finished_admission.py), [public gate and negative controls](../tests/test_pretool_finished_entry.py). Repaired without relaxing receipt freshness, rule revisions, shell parsing or effect authority. Newer pauses, expired proof, local non-publication commands and unreadable publication forms retain their existing boundaries. |
| F21 | Medium / H08, H10 | The agent discovered synthetic input permission late, used a popup fixture with a covering always-on-top parent and a hover-contaminated pixel marker, and retried invalid lifecycle arguments. Three rejected start forms and checkpoint/documentation argument retries were execution mistakes. Detect environment prerequisites and use the documented manifest/schema before repeated native test loops. | Existing [verification policy](../common/skills/verification-policy/references/current-guidance.md), [tool recovery](../common/skills/tool-failure-recovery/references/current-guidance.md) and [operating contract](../common/skills/agent-operating-skill/SKILL.md) already cover these decisions. No new approval or startup gate is added. Genuine native peer/layer hosting defects still required implementation and regression verification. |

The elapsed time does not show that 54 minutes was necessary. Most observed
delay occurred during agent diagnosis, implementation and retries, with two
Moru recovery/reuse defects contributing avoidable work. Checker execution
alone does not explain the wall time, and the unclassified gaps do not prove a
Codex platform fault. These repairs address reproduced behavior rather than
claiming a quantified overall performance improvement.

Verification: **332 focused tests passed**, exit `0`, across `test_agent_commit_ready`,
`test_agent_review_reuse`, `test_pretool_finished_entry`,
`test_claude_pretool_gate`, `test_agent_publication_admission`, and
`test_finished_worktree_integration`, plus `test_claude_pretool_sibling_run`, using the unittest runner with
`PYTHONPATH=tests:scripts`. The scoped preparation subset passed **64 tests**
in **36.076s**. After integrating the updated base, finished-entry/publication
and sibling-run checks passed **268 tests** in **27.656s**; unchanged preparation
owner/reuse results were retained. The preceding 262-check run passed in
**29.851s**. Regression assertions failed before the fixes. These checks retain
scope/staging/byte/rules/authority controls and a public gate negative control
using the former classifier. Workflow validation passed **196 references,
413 Markdown frontmatter/link checks and 28 route contracts**. This is focused
verification, not the full Moru suite or a replayed end-to-end desktop task.

## Audit: 2026-10-09, Worktree And Codex Latency

Source baseline: `a6f124bed7421e4489eedf4304f385dcc3500155`. Environment:
Python 3.9.6, Git 2.54.0, macOS 27.0.1 arm64. The offline comparison replays
the exact approval-setup patch from `22c1ea9fdae901bb23540193c84a8c2579db6e7f`
to `63f6c1d05f3a76e984f3d95961a51066b6564db1`, using a branch in one checkout
or a linked worktree. Each of five alternating pairs starts from independent
fixtures containing all 1,036 baseline tracked members, including five safe
relative symlinks. Both variants apply the same patch, run the same 35 tests,
commit, and integrate fixture main; their final tracked contents must match.

| Phase | One checkout, median | Linked worktree, median |
| --- | ---: | ---: |
| Branch or worktree preparation | 13.87 ms | 199.71 ms |
| Apply frozen patch | 10.98 ms | 11.66 ms |
| Focused tests | 727.95 ms | 698.51 ms |
| Commit | 54.20 ms | 101.58 ms |
| Integrate fixture main | 44.50 ms | 22.78 ms |
| Complete local task | 846.30 ms | 1,076.18 ms |

The median **paired** total difference is +199.26 ms for worktrees; the largest
of five paired differences is +367.61 ms. Subtracting the two total medians
gives a different statistic, and phase medians do not sum to a total median.
The tests' apparent advantage in worktrees is timing variation, not a claimed
speedup. Archive/patch preparation (179.32 ms once) and common fixture setup
(about 2.02 seconds per variant) are recorded separately and excluded from
task totals. Fixtures isolate HOME/XDG/TMP/Git settings and use their own empty
hooks directory; live hooks and policies remain unchanged.

Reproduce with `python3 -B tests/benchmarks/worktree_latency.py --pairs 5`.
Raw samples, metadata, patch/content digests and parity checks are written to
ignored `.moru/performance/worktree-latency.json`. This measures local commands
with warm OS caches. Applying a frozen patch replaces model implementation;
model inference, tool transport, approvals, dependency installation, build
cache recreation, live hooks, concurrent main changes and fixture cleanup
are outside the comparison. There is no end-to-end Codex speedup estimate.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F22 | Medium / H07, H10 | Identical local work adds roughly 0.20 seconds through linked worktrees in this corpus. This does not explain minute-scale latency or price the cost of rebuilding dependencies. | [Offline benchmark](../tests/benchmarks/worktree_latency.py). All ten fixtures matched exact patch, test counts, tracked content and main integration; 350 test cases passed. Keep required isolation; measure environment setup separately before changing it. |
| F23 | High / H02, H09 | `functions.exec` can print adjacent serialized JSON results. The delivery reader treated the whole stream as plain escaped text, missing complete reads and requesting them again. A synthetic replay of this run's 19 current required docs marked all 162,772 bytes unread and rendered a 25,879-byte notice. | [Delivery reader](../scripts/agent_required_doc_delivery.py), [regressions](../tests/test_agent_required_doc_delivery.py). Decode complete structured result streams and the completed orchestration envelope. The same replay now recognizes all 19 docs and renders no notice. Failed, rejected, pending, malformed and truncated results remain unconfirmed; compaction and current-content checks remain. |
| F24 | Medium / H06, H10 | A separate Moru app trace lasted 3,268.17 seconds. Its 24 recorded lifecycle hooks total 26.26 seconds; non-overlapping wall categories contain 263.83 seconds of escalation observation, 759.84 seconds of Gradle observation, 52.30 seconds of other foreground tools and 2,192.20 seconds uncovered. | Existing [stage timing](../scripts/support/stage_timing.py) and that run's ignored latency timeline. Hook totals overlap tool windows and must not be added to them. Escalation windows do not prove a visible dialog or human waiting. Uncovered time is unclassified, not proven model inference. This is another workload, not the approval patch or a controlled worktree comparison. |

The document replay uses synthetic read evidence, not a real transcript.
Its local scan median increases from 1.38 to 3.20 ms across 100 warm scans:
the repair saves redundant delivery and potential rereading, not scanner CPU
time. A worker also received a duplicate document notice after a ready handoff;
the canonical reuse contract permitted continuing without another reading.
That observation alone does not prove the worker's notice has the same parser
cause. Do not turn these byte savings into an elapsed-time or token estimate.

Prioritize proven duplicate reading, avoidable approval/recovery round trips,
and repeated environment preparation before weakening worktree isolation.
Retain one task checkout across a continuation and reuse valid evidence under
the existing contracts. Publication/lifecycle corrections owned by the
concurrent latency audit are outside this change.

Verification: **73 tests passed**, exit `0`, with `python3 -B -m unittest`
over `tests.test_agent_required_doc_delivery`, `tests.test_agent_required_doc_reuse`
and `tests.test_support_stage_timing`. The orchestration regressions failed
before repair; the final suite also confirms a successful sibling counts while
a nested pending command remains unread. These are focused checks, not the
full Moru suite or a controlled pair of model sessions.

## Audit: 2026-10-12, CI Correction Preparation

Source baseline: `62bb6670158b751cf7a45ae66e30df7f8e91247f`, clean before this
task. Environment: Codex on macOS, Python 3.9.6. This follow-up uses observed
execution evidence and bounded source inspection; it does not reconstruct an
entire session timeline or measure an end-to-end speedup.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F25 | Medium / H06, H08 | A declaration parameter change invalidated three existing signature-keyed static-analysis exemptions, requiring another CI correction. A required structure check was also discovered after behavioral tests. Inspect affected exemption identities and required ordering before the costly check; retain valid evidence when a late check can still verify it. | [Verification guidance](../common/skills/verification-policy/references/current-guidance.md), Markdown/frontmatter/link validation and final diff review. Resolved as a guidance gap; no new gate, analyzer permission, baseline exemption or runtime classifier change. |

The existing [publication classifier](../scripts/claude_worktree_gate.py) already
supports a repository-declared non-publishing argv prefix. This inspection does
not establish why a prior PR-check invocation was refused; keep its exact argv,
receipt and working directory distinct before changing the classifier. A long
observed tool wait likewise does not prove network delay or a visible approval
dialog. Runtime latency and overall CI health remain outside this correction.

Verification commands: `python3 scripts/workflow.py validate` and
`git diff --check`, followed by the final review. This documentation correction
does not establish a runtime speedup or a passing application CI run.

## Audit: 2026-10-18, Workflow Overhead

Source baseline: `33ad1052`. Environment: Claude Code on macOS. The window is
2026-09-18 to 2026-10-18 UTC: entries from 219 main-session transcripts, 27 of
them in this repository, measured with the [overhead report](../scripts/moru_overhead_report.py).
Rerun it with the same `--since`/`--until` flags after later changes; a pre-rename
checkout is counted with `--alias-root`. Token figures marked chars/4 are
approximations, not tokenizer counts. Only entries inside the window count, so
a session spanning a change is split at the window edge.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F26 | Medium / H10 | Launcher calls were 14.2% of all tool calls; hook-injected context was about 1.3% of new input tokens. Claude policy notes, which decide nothing, were repeated 3,485 times. Show it once per transcript. | [Claude PreToolUse gate](../scripts/claude_pretool_gate.py), its gate tests. Resolved in `62c1a2f2`. |
| F27 | Medium / H10 | Each gate process ran up to 11 git subprocesses to resolve its checkout; median process time was 172 ms. Read the git directory, common directory and branch from disk, falling back to git for unusual layouts. | [Worktree gate](../scripts/claude_worktree_gate.py), [git-dir tests](../tests/test_claude_worktree_gate_git_dir.py). Resolved in `5d0692f9`; median 62 ms on the same probe. |
| F28 | Low / H06 | Start asked for `request intake` that it had already recorded, and every closeout spent a gate-batch on a `no_reusable_gap` retrospective. Omit start-recorded gates and let finish derive the default retrospective. | [Hook CLI](../scripts/agent-hook.py), [retrospective default](../scripts/agent_finish_retrospective_default.py) and its tests. Resolved in `89e06e64`; this change lets the Claude finish guard admit an unrecorded retrospective and keeps a failed agent record from being replaced by the default. |
| F29 | Low / H06 | Review rejected calls that lacked structure evidence for large changed files, and most source files here exceed the 300-line review-pressure size. A successful gate-batch now previews those requirements while the review hook is outstanding. | [Structure preview](../scripts/agent_review_structure_preview.py) and its tests. Resolved in this change. |

Bridge-instruction compaction was not pursued: injected context is a small
share of input, and its phrasing is pinned by regression tests. A before/after
comparison needs sessions recorded after these changes. A first reading from
2026-10-18 06:45 UTC (10 sessions, 564 tool calls, too small to conclude) showed
policy notes at 1.8 per 100 tool calls against 7.6 before, and a PreToolUse
median of 326 ms against 436 ms.

## Audit: 2026-10-20, Release Preparation Reading And Round Trips

Source baseline: `625deb4d`. This focused audit uses one completed Codex Spill
release-preparation turn, from 05:59:02.176 to 06:19:55.527 UTC. It does not
compare a matching Claude run or establish a model speed difference.

| Observation | Measured value |
| --- | ---: |
| User request to task completion | 1,253.351 s |
| Outer orchestration calls | 44 exec, 16 wait |
| Nested command executions | 118 |
| Commands reading source or docs with cat or sed | 36 |
| Lifecycle commands | 11; 5.243 s summed process duration |
| All command durations | 171.061 s summed process duration |
| Awaited outer tool intervals | 280.820 s |
| Six escalated calls, invocation to command start | 410.940 s summed interval |

These measures are not additive wall-time categories: commands can overlap,
and background execution or permission processing can continue outside an
awaited outer interval. The remaining 972.531 seconds outside those intervals
are unclassified, not a measurement of model inference or human approval time.
The six escalated calls took 67.883 to 69.897 seconds each before their matching
command started. This includes permission processing and transport; it does
not prove a visible dialog, human delay, or time spent specifically in the
native reviewer. No token totals were reconstructed.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F30 | Medium / H01, H02, H06, H10 | Release preparation followed the routed manifest with a broad second Read list, then opened generic cards and their references. It also used many short waits and separated checks whose existing runner already built the bundle. Bound reading to the manifest and unresolved decisions; retain valid checks and artifact inputs, batch ready work, and continue resolved actions. | [Release readiness](../workflows/skills/release-readiness/references/current-guidance.md). Resolved as a guidance correction; workflow validation and required-document selection tests must still pass. Safety, permission enforcement, release checks and production approval rules are unchanged. |

The observed stale verifier paths were corrected in Spill. An environment
selector was also conservatively rejected as a protected-root target; this
audit does not relax that parser's executor-variable safeguards. The agent's
over-reading and deliberation contributed to the turn and are not attributed
to hook CPU time. This correction has no measured end-to-end speedup yet.

## Audit: 2026-10-23, Durable Learning And Correction

Source baseline: `a13e35a8`, clean main checkout; repair verified in a linked
worktree on macOS with Codex and Python `3.9.6`. Scope: H04/H08, existing
project-memory storage, recall and closeout validation. No transcript store,
inference change, vector index, external model call or memory migration.

At 10:17 UTC, the live store had 10 valid records (5 active, 5 retired), no
unreadable records or unfinished replacements. The verified lesson captured on
October 22 at 14:42 UTC remained source-unchanged and was delivered by the
installed launcher at this task's start in a new linked worktree. The elapsed
window was 19.58 hours, not a full day; that diagnosis was the only capture in
the window. In the main checkout's retained manifests, five completed work
runs carried `decision_v1` and a successful, reasoned `not_needed` decision,
referring to their canonical source changes. A completed commit-only run had
no retrospective requirement; an unfinished work run had no decision yet.
This demonstrates continued decision recording and cross-worktree delivery,
not that those decisions were semantically correct or repeated mistakes fell.

The current Korean follow-up alone recalled nothing; supplying its established
repeated-mistake/memory-reuse scope retrieved the relevant lesson. This is the
documented lexical boundary: carry resolved conversational scope into the
existing target summary, without guessing applicability or filling empty slots.
The actual start did so and delivered the source-checked diagnosis. Some
lower-ranked lexical matches remain irrelevant; agent applicability judgment
is still required.

### F31: Interrupted Correction Can Resurrect Superseded Advice

P1 correctness / H04, H08; **resolved**. Owner: `_recall` in
[project memory](../scripts/agent_project_memory.py). Replacement writes the
new record before retiring its predecessor. If that retirement is interrupted,
the predecessor remains active on disk. The baseline suppresses predecessors
only through recallable successors: correcting that successor again or retiring
it removes its exclusion link. Old invalidated advice then becomes recallable
and can satisfy a `stored` closeout reference again.

Three targeted regressions failed before repair: chained correction returned
both old and current advice; retirement restored the old record; closeout
accepted the superseded reference. The repair derives supersession from every
validated record, independent of its current status, preserving the durable
replacement commit point. Expiry or retirement withdraws advice; it does not
undo its correction. No stored records are rewritten or automatically promoted.

Proving checks are the interrupted-chain and retired/expired-successor cases in
[memory tests](../tests/test_agent_project_memory.py), including CLI recall and
read-only byte comparisons, and the superseded-reference rejection in
[closeout tests](../tests/test_project_memory_closeout_end_to_end.py). The
existing actual CLI capture, finish, next-start recall and late-retirement
rejection flow remains covered. The live store showed no unfinished replacement;
this is a reproduced failure mode, not a claim it occurred in that store.

Final verification: **178 tests passed**, zero failures/errors/skips, across
`test_agent_project_memory`, `test_agent_project_memory_applicability`,
`test_agent_project_memory_consolidate`, `test_project_memory_closeout_end_to_end`,
`test_agent_finish_gate_policy` and `test_agent_gate_record_template` using
`PYTHONPATH=tests:scripts python3 -B -m unittest`. Workflow validation passed
195 references, 434 Markdown blocks/links and 28 route contracts. There is no
measured change in real-work mistake rates or model reasoning quality.

## F32: Every Task Start Performs Full Fuzzy Consolidation

P2 efficiency / H04, H06, H10; **resolved for startup**, baseline `197d3b4e`.
Owners: `_project_memory_upkeep_lines` in `scripts/agent-hook.py` and `findings`
in `scripts/agent_project_memory_consolidate.py`. Every start invoked full
pairwise near-duplicate comparison to produce a content-free hint. At 3,000
active records this performs 4,498,500 similarity calls even if no hint appears.

Startup now uses linear exact-duplicate, expiry, shared-source and unfinished
replacement counts; its label explicitly says `exact_duplicates`. The existing
explicit consolidation report retains full fuzzy analysis and human/agent
decision evidence. No automatic memory mutation or advice-selection change.
The [reproduction and measured limits](project-memory.md#startup-maintenance-cost)
include byte-equivalent recall on the synthetic comparison. The actual CLI
startup and memory/closeout suites passed, and a read-only probe recalled the
source-unchanged live diagnosis without changing any of the ten stored records.
Record-file scanning and lexical ranking remain linear; a scalable index,
weak-link learning and real judgment improvement are not delivered by this fix.
