---
keyflow_id: sys_project_memory_start_references_2026_10_24
status: review
type: ai-generated
---

# On-Demand Memory: Startup Ablation

## Decision And Scope

Remove automatic project-memory scan, recall and upkeep from task start. Keep
explicit retrieval, correction, retirement, history, work cards and existing
same-session document/verification reuse. This is a reduction of an unproven
extra retrieval layer, not evidence that all models have identical memory or
that external memory is never useful.

## Reproduction

```sh
python3 -B tests/benchmarks/project_memory_start_references.py --samples 21
```

The [benchmark](../../tests/benchmarks/project_memory_start_references.py)
loads the original hook from baseline commit
`d77f2402f376c351bc61a0a7f0d6085f51526f89` and the current hook. Other runtime
dependencies are shared and algorithmically unchanged. Each condition uses a
fresh temporary Git project and isolated on-disk memory store; no user records
are read or modified. The actual startup-reference helper runs with real work
cards, record parsing/ranking and Git source hashes. Three matching records
share one source file. Calls are warmed up and alternate order for 21 pairs.
Instrumentation is outside the timing samples. Store byte digests are checked
before and after all calls.

[Raw samples and operation counts](project-memory-start-references-2026-10-24.json)
retain both runs: the first overlapped this task's test processes; the second
began after they completed. Other machine load was uncontrolled. Python 3.9.6,
macOS 27.0.1 arm64. These are warm-cache, single-machine measurements of one
helper, excluding full lifecycle/process startup, model calls and token billing.

## Results

Second-run medians, milliseconds:

| Stored records | Before | After | Record reads before / after | Injected characters before / after |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 75.55 | 49.28 | 0 / 0 | 0 / 0 |
| 10 | 128.10 | 65.00 | 10 / 0 | 640 / 0 |
| 1,000 | 233.29 | 53.27 | 1,000 / 0 | 640 / 0 |
| 3,000 | 282.94 | 26.96 | 3,000 / 0 | 640 / 0 |

For every nonempty condition, source hashing also falls from one call to zero;
the baseline delivers three records and the candidate delivers none. Store
digests remain unchanged. The empty-store control removes no record reads or
text; its timing difference includes the removed store-location/scan setup.

At 3,000 records the median paired time saved is 257.09 ms; an exploratory
2,000-resample percentile bootstrap gives 234.65–296.22 ms. This interval
describes within-run samples only. The first run measured 303.79 to 30.11 ms
at that size. Variable work-card/system overhead is visible in the other sizes;
timings do not establish a universal speedup ratio. The deterministic result is
zero memory-store reads, source hashes and reference text in this startup path.

## Behavior Verification

All 144 focused tests passed on the final production patch:

| Selector (`tests/`) | Tests | Covered behavior |
| --- | ---: | --- |
| `test_agent_work_cards_lifecycle.py` | 10 | No automatic recall/upkeep; explicit lookup; work-card continuity; no user-store leakage |
| `test_project_memory_closeout_end_to_end.py` | 16 | Actual CLI capture, closeout, absent-at-start, explicit recall and late-retirement rejection |
| `test_agent_project_memory.py` | 39 | Replacement, expiry, retirement, history, bounded retrieval and source freshness |
| `test_agent_project_memory_applicability.py` | 15 | Applicability, exceptions and invalid evidence |
| `test_agent_required_doc_reuse.py` | 15 | Reuse of unchanged readings and takeaways; rejection for changed/missing/cross-session evidence |
| `test_agent_gate_reuse.py` | 16 | Reuse of valid verification; drift/failure/authority/external-result controls |
| `test_agent_hook_start_run_binding.py` | 12 | Start/run identity and continuation |
| `test_agent_hook_compact_start_authority.py` | 21 | Compact-start authority boundaries |

Run each selector with `python3 -B -m unittest discover -s tests -p <selector>`.
Lifecycle fixtures use their existing audit stand-in where appropriate; the
real repository safety audit is a separate review/finish check.

## What This Establishes

The removed startup memory work and injected text are directly measured.
Existing reuse and correction safeguards still pass their focused checks.
The change does not measure real-project task success, recurring-mistake rate,
quality of native analysis reuse, cross-provider equivalence, billed tokens or
end-to-end productivity. Removing advice can also remove a useful reminder;
explicit retrieval and current instructions remain available, but universal
task-quality noninferiority has not been established.
