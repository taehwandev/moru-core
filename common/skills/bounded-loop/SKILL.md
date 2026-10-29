---
name: bounded-loop
description: "Bounded Loop: Read only for an explicitly requested sustained task with a checkable finish condition."
keyflow_id: sys_bounded_loop
status: review
type: ai-generated
metadata:
  internal: true
---

# Bounded Loop

Read only for an explicitly requested sustained task with a checkable finish
condition. Ordinary tasks do not enroll. This card adds no authority, router,
wakeup, model service, automatic commit, source rollback or final-gate waiver.

## Contract

Start an ordinary writable Moru task first. Define the goal as an executable
project test, a separate regression selection, exact owned files and the frozen
test files. Keep helper fixtures that define the oracle outside the owned set.
The initial adapter uses Python unittest; use a project-owned test wrapper for
another existing verifier only when its execution and effects are authorized.
The wrapper must exercise the real claimed outcome, not merely return green.

Enroll once using `<MORU_LAUNCHER> loop start --project <PROJECT>` with:

- `--objective <bounded goal>`;
- repeated `--path <owned-file>` and `--verifier-path <frozen-test-file>`;
- `--test-directory <directory>`, `--goal-pattern <test-file-glob>` and
  `--regression-pattern <test-file-glob>`;
- explicit `--max-iterations`, `--max-seconds` and `--max-model-calls`.

Paths are exact project-relative files. HEAD, staged index, frozen tests and
non-owned files must stay unchanged during the loop. No symlinks or submodules.
Enrollment executes the baseline. A passing baseline completes with no attempts.

The runtime owns model execution and wakeups. `begin --calls N` reserves N calls;
before further calls use `reserve --calls N`. Never launch more calls than the
successful reservation admits. This counts protocol admissions, not hidden or
unreported usage. A reservation does not authorize a paid service or new scope.
Exact token counts remain the runtime's responsibility, never estimated here.
Requesting more calls than remain exits 2 without changing the loop or spending
reservations. A genuinely exhausted loop stays terminal after reconciliation.
Keep the interpreter and dependencies fixed: fingerprints cover the declared
files and tracked/non-ignored Git files, not ignored environments or packages.

## One Attempt

1. `loop begin --project <PROJECT> --hypothesis <one hypothesis> --calls 1`.
   Inspect the returned status before launching work; `exhausted` admits none.
2. Make only the scoped change. Do not stage or commit during an attempt.
3. `loop check --project <PROJECT>` runs the frozen regression and goal checks
   with one shared remaining deadline. It captures real exit status, test count,
   input identity and optional measurement. At least one test must really pass;
   skip-only and expected-failure-only suites provide no completion proof.
   Gate prose cannot substitute for execution.
4. `loop accept --project <PROJECT>` accepts a fresh goal success, or a measured
   improvement with green regressions. A passing regression alone is not done.
5. For a rejected candidate, restore only that attempt's changes yourself.
   `loop reject --project <PROJECT>` advances only after its owned files match
   the accepted checkpoint. Never reset, clean or delete unrelated work.

In measurement mode, declare `--direction min|max --min-delta <positive noise floor>`
at enrollment. The goal test writes `{"value": <finite number>}` to the current
`MORU_LOOP_MEASUREMENT_PATH`, including when the target is not yet reached.
Use repeated samples in the project oracle; a single noisy sample is not proof.
The frozen goal test asserts the final target and its required workload. The
regression test protects correctness. Missing, stale or malformed output is an
error, never a zero measurement. Only improvement beyond the declared delta is
accepted. Non-improving changes must be restored before the next attempt.

## Stop And Resume

- `loop pause` stops admissions without discarding work. `loop resume` preserves
  the original deadline, consumed reservations, attempt and accepted checkpoint;
  it requires a fresh check for an unfinished candidate.
- After interruption, use ordinary Moru resume to regain the exact task owner
  first. Loop resume cannot claim another session or worktree. A live check must
  finish or be reconciled through its existing handle before resuming. The
  supervised check adapter currently requires POSIX process groups and refuses
  unsupported hosts; it never assumes a dead parent means its children stopped.
  A denied process probe also blocks recovery until its recorded handle is reconciled.
- CLI runs without session environment variables use Moru's existing exact
  process-owned binding. Foreign owners and missing strict sessions still fail.
- `loop cancel` records cancellation and preserves all source and evidence.
- `loop status --project <PROJECT> --run-id <id>` reads durable state, including
  after task completion. History records hypotheses, values and accept/reject
  decisions; it contains fingerprints, not source snapshots or transcripts.
- `exhausted` means a ceiling stopped work, not that the goal passed. Exit 4
  reports this outcome; invalid or denied operations exit 2.

Every command above accepts `--project <PROJECT>`. Loop success does not finish
the task: run its required integrated tests, review and finish before claiming
delivery or any separately authorized commit/publication. Do not reopen those
gates for each expected rejected experiment. Never relax the goal, reset a
budget, turn on broad multi-model work or widen scope to get past a plateau.

Design and acceptance: [PRD](../../../docs/bounded-loop-runs/prd.md) and
[architecture](../../../docs/bounded-loop-runs/ard.md).
