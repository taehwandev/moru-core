---
keyflow_id: sys_runtime_native_completion_evidence
status: review
type: ai-generated
---

# Native completion evidence

Implement the approved sequence: verification-quality warnings, requirement/
artifact/gate coverage, then semantic progress diagnosis. Decision rules live
in Rust. Python retains the existing lifecycle, ownership and storage interfaces
and transports bounded JSON; no parallel Python decision implementation is added.

## 1. Verification quality

Inspect successful `tests` records when single/batched gate recording returns.
Warn on standalone fixed-output commands (`echo`, `printf`, `true`, `:`, `exit 0`)
and zero-test results. A chain containing a real verifier or an observed variable
is not classified as a fixed literal. Never execute the supplied command; print
only the gate/rule, not command content. Warnings add no gate/approval and do not
replace evidence, test-count, freshness or review checks. Lexical inspection
cannot prove arbitrary code satisfies an English outcome. Missing native support
retains existing gate behavior.

## 2. Requirement coverage

Multi-outcome work can add this optional field to existing checkpoint work:

```json
{
  "requirements": {
    "revision": 1,
    "items": [
      {"id": "r1", "outcome": "Deliver the plan", "owner": "lead",
       "gate": "tests", "artifacts": ["docs/plan.md"]}
    ]
  }
}
```

Each item has exactly these five fields. IDs are unique bounded lowercase slugs;
revisions are positive integers. Changing items requires a higher revision and
existing IDs cannot disappear within the run. Scope authority and cancellation
remain with the existing request/lifecycle owner. Up to 32 items and eight
artifact paths per item must also fit existing packet byte/prose limits. Paths
exclude traversal, `.git`, `.moru`, symlinked files/parents and non-regular files.
An empty artifact list permits a non-file outcome to rely on its observing gate.

Validate this closed optional subtree separately for depth; preserve the old
packet depth limit elsewhere. Existing packets omit it and retain their behavior;
older readers reject the new field instead of silently ignoring it. Recording/
updating the opt-in contract and finishing it require matching native evaluation.
Missing native support, Python rollback or source drift fails coverage closed.

Before finish, every item must name a successful gate in the admitted route and
every artifact must exist. Native observation hashes bounded bytes (16 MiB/file,
32 MiB/call). Missing files/gates and invalid contracts remain failures even when
`remaining_work` is empty. Existing finish checks still validate actual ledger
ownership/freshness, pending work and authority; coverage never grants those.

## 3. Semantic progress

Eligible active-work Stop continuation observes remaining actions, blockers,
gate states and requirement mappings. Ignore timestamps, generation numbers,
incidental log text, ordering and revision-number-only edits. A changed acceptance
state resets the counter. Three unchanged observations append a diagnosis to the
existing reminder; they neither close work nor increase one-per-turn continuation.
User stops, approval waits and global blockers retain precedence.

Store only this advisor's digest/count in a session/runtime/run-local file. A
nonblocking no-follow private lock and atomic JSON replacement prevent the
advisor from holding Stop. Contention, unavailable native support, unsupported
runtime or malformed state omits the diagnosis. Python rollback omits it too.
Compare delivery/authority state independently of these explicitly tested files.

## Protocol and delivery

The existing binary exposes private `--completion-probe <operation>` ingress for
`quality`, `requirements`, `coverage`, `progress`. Bounded JSON yields
`{"schema_version":1,"result":...}`. Retain the source/environment guard, 1 MiB
transport bounds and ten-second timeout. Unsupported input returns 125 without
stdout, including under hook soft-fail. There is no public launcher alias,
shell executor, new dependency/service, model call or consumer compiler.

The independent implementation was informed by
[unlazy completion ideas](https://github.com/Leonxlnx/unlazy/tree/16671491f6679ad9378f52604d3bc2415b4120c7).
No upstream code, installer or hook is vendored. Follow selective measurement:
no per-item timing/CPU/RSS/cost experiment or new speed claim. Source remains on
the local performance branch; main integration, push, release and global
activation are separate outcomes.

## Verification

Observed locally on macOS arm64 with `PYTHONPATH=scripts:tests` for Python
unittest runs. The affected twelve Python suites collect 205 unique tests;
coverage below comes from focused runs, not one monolithic invocation.

| Check | Observed result |
| --- | --- |
| Rust launcher tests (`rust-final.log`) | 30 passed |
| Completion, packet, checkpoint, finish and Stop suites (`completion-final.log`) | 91 passed |
| Final native/integration/ledger compatibility run (`integration-final.log`) | 42 passed |
| Claude, Codex and continuation adapters (`adapters-final.log`) | 82 passed |
| Final reordered-progress and real finish-CLI checks (`final-acceptance.log`) | 2 passed |
| Fresh packaged consumer with empty PATH (`smoke-final.log`) | 65 checks passed |
| Formatting and whitespace | `cargo fmt --check` and `git diff --check` passed |

Logs are retained under the observing run's ignored `.moru/runs/` directory.
Initial failures are retained there too. The feature run exposed a false
zero-test warning and the new contract's packet-depth conflict; both were
corrected in their owners and covered by passing reruns. Compatibility failures
required explicitly separating the new advisory files from authority-state
comparison and making an existing invalid-retrospective fixture unambiguously
invalid; canonical retrospective validation was unchanged. Later focused runs
include nonblocking lock contention, symlink rejection, session isolation and an
actual finish invocation that refuses a missing requirement artifact.

The fresh consumer exercises all four private operations without a compiler or
Python on PATH. The four-host CI selector includes the affected suites; remote CI
and global installation were not executed in this local increment. No latency,
CPU, memory or token-saving result is claimed.
