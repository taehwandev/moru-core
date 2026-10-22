---
keyflow_id: sys_moru_experience_reuse_experiment_20261022
status: review
type: ai-generated
---

# Conditional experience reuse: implementation and bounded trial

On 2026-10-22, the existing local project-memory path was extended to carry
verified applicability and exceptions, and to withhold records with no lexical
match when a task supplies query context. Claude and AGY independently proposed
and challenged the design, then each completed the same synthetic judgment
comparison through existing CLI access. No conversation fork, vector service,
new memory store or automatic model call was added to task starts.

The result supports more selective delivery of existing knowledge. It does not
establish improved model intelligence, learned weights or autonomous learning.

## Runtime behavior

- Optional `applies_when` and `not_when` fields are each bounded to 160 printable
  characters and included in integrity validation, recall, history and
  consolidation reports. The existing capture command accepts both conditions.
- Only the positive condition contributes to ranking. A term in an exception
  cannot itself attract the lesson; superseded history remains outside ranking.
- Context-bearing recall withholds zero-score records. Context-free inspection
  retains its original ordering. Recall still has a three-record, 1,200-character
  JSON payload budget, and source files are hashed at most once per recall.
- Recalled conditions are evidence for the agent to assess, not executable
  predicates. Source drift still demands verification. Required documents,
  current action authority, expiry, replacement and isolation contracts retain
  their existing owners. Native runtimes retain active context ownership.

Older records without conditions remain readable. Older Moru versions do not
understand the extended digest and can reject new conditional records; update
readers together before using them against a shared local store. No existing
user records were migrated or rewritten by this experiment.

## Retrieval comparison

The developer-only evaluator uses 14 synthetic cases and injected in-memory
records, with no store writes or model calls. One context-free listing case is
excluded from aggregate retrieval metrics. The baseline is the exact memory
module from `49fd9e95`, loaded against the same fixture and unchanged helpers.
The fixture was written for this feature; it is not a held-out benchmark.

| Measurement across 13 query cases | Baseline | Candidate |
| --- | ---: | ---: |
| Relevant records rendered / expected | 7 / 9 | 8 / 9 |
| Irrelevant records rendered | 32 | 1 |
| Relevant records missed | 2 | 1 |
| Retrieval precision | 17.9% | 88.9% |
| Retrieval recall | 77.8% | 88.9% |
| JSON payload characters, excluding headers/list markers | 6,350 | 1,796 |

The approximately 72% payload reduction applies only to these fixtures. The
positive-condition case retrieves an experience for a differently named file
that the baseline misses. One generic-word false inclusion remains. A relevant
paraphrase with no indexed shared terms is still missed. These are visible
failures, not accepted proof of semantic retrieval. Zero-score withholding can
also remove an accidentally useful fallback in other tasks; no population-level
recall or efficiency improvement is established.

Reproduce candidate retrieval from the repository root:

```sh
python3 -B scripts/agent_experience_eval.py
```

For the historical comparison, export
`git show 49fd9e95:scripts/agent_project_memory.py` to a scratch directory, then
pass that directory with `--engine-root`. The evaluator prints input SHA-256
hashes and per-case misses, false inclusions and character counts. It uses the
checkout's helper modules; this is not a complete historical-runtime benchmark.

## Live judgment comparison

Each provider received one fresh batch of 12 cases per arm, four calls total.
The full arm contains all reference passages for each case; the compact arm
contains actual candidate recall output. Current facts, choices, decisive
lessons, exceptions and source-drift information are available in both arms.
The expected choices were fixed before calls and kept out of provider prompts.
Each prompt contains only the shared instruction and case id, request, current
facts, available choices and that arm's references. No tools or real project
actions were permitted. Later code cleanup was checked to emit byte-identical task
prompts, preserving the applicability of the recorded trial.

| Provider | Full references | Compact references |
| --- | ---: | ---: |
| Claude, current configured default | 12 / 12 | 12 / 12 |
| AGY, current configured default | 12 / 12 | 12 / 12 |

The cases cover duplicate delivery after a rename, distinct valid event ids,
valid cache reuse, account changes, unknown permissions, changed source,
corrected display advice, live stop guards, mandatory unread documents,
scope-bound approval, independent usage failure and authorization failure.
Returned reasons were inspected alongside exact-choice scoring.

Reference characters fell from 10,045 to 8,462 (15.8%). The complete supplied
task prompts fell from 15,640 to 14,406 characters (7.9%, including JSON
escaping and instructions). These are character counts, not token savings.
Native CLI instructions, caches and model versions were not normalized or
hard-pinned; observed provider token fields and process wall times cannot
establish causal cost or speed improvements. This small multiple-choice trial
checks retention of stated boundaries, not open-ended coding quality, novel
reasoning, repeated-session learning or production safety.

The [result artifact](project-memory-2026-10-22.json) retains the synthetic
cases, both reference forms, expected choices, returned choices/reasons,
reported usage, wall times and input hashes. Its shared instruction replaces
the local capsule path with a placeholder; original prompt hashes refer to the
unredacted local task prompts. Provider-native hidden context is not included.

## What this establishes and what remains open

The implemented improvement is more useful, bounded reference delivery through
the current memory path. Existing models retained the desired decisions in
this trial; their decision accuracy did not improve over the full-reference
arm. Storing conditions does not itself prove that an experience is true or
that the agent will generalize it correctly.

The next acceptance boundary is a consented set of actual task outcomes:
transfer to renamed owners, withheld advice under reversed conditions,
correction without unrelated regressions, and verified read/tool reductions.
Cases with no shared terms need a separate comparison of simpler terminology
bridges and optional semantic retrieval before choosing a vector dependency.
Neither automatic lesson promotion nor relaxed required reads is justified by
the current evidence.
