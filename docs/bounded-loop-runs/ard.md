---
keyflow_id: bounded_loop_runs_ard
status: review
type: ai-generated
---

# Bounded Loop Run Architecture

Use the existing Python CLI/runtime architecture, run registry, state locks and
atomic JSON writes. Keep loop state beside its bound run's preflight evidence;
do not add another router, daemon, database, transcript store or sync channel.

## Owners And Contracts

- `scripts/agent_loop_inputs.py`: one `LoopInputs` owner validates exact relative
  owned/verifier file lists and captures HEAD, index, owned file identities,
  frozen verifier identities and non-owned Git changes. No source writes.
- `scripts/agent_loop_check.py`: executes the frozen unittest selections through
  the existing bounded runner; captures input stability and a finite optional
  measurement emitted to a unique local artifact. No shell or model execution.
- `scripts/agent_loop_contract.py`: closed schemas and pure budget, acceptance
  and result-summary policies; no I/O or authority decisions.
- `scripts/agent_loop_binding.py`: exact registry/session admission, locked
  storage and process-liveness probes; no source writes or authority transfer.
- `scripts/agent_loop_state.py`: one `LoopRun` owner controls enrollment,
  attempts, reservations, pause and recovery through the existing run binding.
- `scripts/agent_loop_candidate.py`: executes a candidate outside the state
  lock, durably admits its process groups, then reconciles fresh results and
  accept/discard decisions inside the current owner's transaction.
- `scripts/agent_loop.py`: CLI parsing and JSON output only. Existing launcher
  registration exposes `loop`; existing lifecycle admission remains mandatory.
- A need-driven `common/skills/bounded-loop/SKILL.md` documents the protocol.
  Ordinary start, Stop, review and finish behavior is unchanged.

`LoopInputs(project, owned, verifiers).capture()` returns a JSON object containing
`head`, `index`, `outside`, `owned`, and `verifiers`. `assert_scope(current,
accepted)` permits owned-file changes only; `assert_restored` requires complete
equality. Paths are exact files, no globs, traversal, directories or symlinks.
Index and non-owned changes make a candidate unsafe; no rollback is inferred.

Checks use frozen unittest directory/pattern selections, not arbitrary commands.
Expose the existing unittest executor as a reusable function without changing
its normal tests-gate behavior. Loop attempts do not manufacture task gate
success or trigger the task's repair lifecycle for expected rejected experiments.
Only the final integrated task records normal tests/review/finish evidence.

Optional measurement files contain one finite numeric `value`; the checker
must create them during the current execution. Their meaning belongs to the
project's frozen test oracle. Missing, stale or malformed output fails closed.
The final goal test, not a manually supplied metric or success flag, proves done.

## Safety And Recovery

All mutations require the registry's exact current writable owner transaction.
Run identity is durable; standard Moru resume supplies any new session binding.
Loop state does not transfer authority or automatically reclaim another run.
For session-less CLI processes, reuse the existing process-owned evidence
resolver; revalidate the same owner and session generation inside the transaction.
Deadlines include pause time. Model-call reservations are never refunded.
Oversized requests are invalid operations, not budget exhaustion. Reconciliation
cannot reopen an exhausted loop. Ignored environments/packages remain trusted
fixed inputs outside the source fingerprint guarantee.
Each POSIX verification process group is durably admitted before its runner
loads project code. A trusted runtime starts an isolated no-site bootstrap;
after admission it replaces itself with the selected interpreter, preserving
the PID/group and normal venv/PYTHONPATH startup. EOF before admission runs no
project or environment startup code. A live or unprobeable child group blocks
recovery even after its parent has died; timeout/interrupt cleanup targets only
the group this executor created. Other operating systems fail closed for this
supervised adapter until an equivalent process-ownership mechanism exists.
Permission-denied liveness probes preserve the original check failure and the
unresolved checking state; they never imply the process has exited.

Candidate discard is an observed reconciliation: after the agent restores only
its rejected changes, a snapshot must equal the accepted checkpoint before the
controller advances. This protects pre-existing dirty work and concurrent edits
without copying source bytes or secrets into runtime records.

History is bounded by enrollment limits and contains fingerprints and bounded
hypotheses, never commands, transcripts or source contents. Existing JSON state
and filesystem failures preserve the last atomic record. No source or Git write
is performed by this feature. A loop result is not commit readiness.

## Delivery And Checks

Parent owns state/check/CLI integration and specs. A worker owns input capture
and its tests after this contract is stable. A separate read-only reviewer checks
the integrated patch. Tests mirror each production owner; CLI subprocess tests
exercise the actual consumer path. Existing verifier and launcher tests protect
compatibility. Structure preview, workflow validation and the normal review and
finish hooks close the delivery; no push or installation is included.
