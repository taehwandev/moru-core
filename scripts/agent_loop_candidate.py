"""Observed verification and accept/discard transactions for one loop candidate.

Owner: loop candidate execution boundary. Imports: existing loop storage,
input identity and bounded unittest adapter. No source/Git writes or wakeups.
Caller/tests: LoopRun, test_agent_loop_state and test_agent_loop.
"""

from __future__ import annotations

import os
import time

from agent_loop_binding import LoopBinding, _require_groups_finished
from agent_loop_check import LoopCheck
from agent_loop_contract import budget_allows, candidate_improves, goal_met, result_summary
from agent_loop_inputs import LoopInputs


def evaluate(binding: LoopBinding) -> dict:
    with binding.transaction():
        state, now = binding.load()
        if state["status"] not in {"ready", "attempting"}:
            raise ValueError("loop is not ready for fresh verification")
        if state["status"] == "ready" and state["baseline_result"] is not None:
            raise ValueError("begin an attempt before evaluating another candidate")
        inputs = _inputs(binding, state)
        inputs.assert_scope(inputs.capture(), state["accepted"])
        if not budget_allows(state, now):
            return binding.save(state)
        state["status"], state["inflight"] = "checking", {"owner": os.getpid(), "groups": []}
        attempt_id = (state["attempt"] or {}).get("id")
        binding.save(state)
    checker = LoopCheck(binding.project, state["config"], binding.path.parent / "loop-artifacts",
                        process_admission=lambda pid: _admit_process(binding, attempt_id, pid))
    try:
        result = checker.run(inputs, max(0.001, state["deadline"] - time.time()))
        return _record_result(binding, attempt_id, result)
    except BaseException:
        _abandon_check(binding, attempt_id)
        raise


def resolve(binding: LoopBinding, accept: bool) -> dict:
    with binding.transaction():
        state, now = binding.load()
        attempt = state["attempt"]
        if state["status"] not in {"evaluated", "exhausted"} or attempt is None:
            raise ValueError("no evaluated attempt to resolve")
        exhausted = state["status"] == "exhausted"
        inputs, result = _inputs(binding, state), attempt["result"]
        if accept:
            if result is None or now >= state["deadline"] or not result["timely"]:
                raise ValueError("candidate has no timely observed result")
            current = inputs.capture()
            inputs.assert_scope(current, state["accepted"])
            if current != result["candidate"] or not result["regression"]["passed"]:
                raise ValueError("candidate changed or regressions failed")
            if not candidate_improves(state, result):
                raise ValueError("candidate did not improve the frozen criterion")
            state["accepted"], state["baseline_value"] = current, result["value"]
        else:
            inputs.assert_restored(inputs.capture(), state["accepted"])
        attempt["verdict"] = "accepted" if accept else "rejected"
        if result is not None:
            attempt["result"] = result_summary(result)
        state["history"].append(attempt)
        state["attempt"] = None
        state["status"] = ("exhausted" if exhausted else
                           "succeeded" if accept and goal_met(result) else "ready")
        if state["status"] != "succeeded":
            budget_allows(state, now, new_attempt=True)
        return binding.save(state)


def _record_result(binding: LoopBinding, attempt_id: str | None, result: dict) -> dict:
    with binding.transaction():
        state, now = binding.load()
        if not _owns_check(state, attempt_id):
            raise ValueError("verification no longer owns this attempt")
        inputs = _inputs(binding, state)
        current = inputs.capture()
        inputs.assert_scope(current, state["accepted"])
        if not result["stable"] or result["after"] != current:
            raise ValueError("verification inputs changed; no result was accepted")
        _require_groups_finished(state)
        state["inflight"] = None
        observed = {"candidate": current, "regression": result["regression"], "goal": result["goal"],
                    "value": result["value"], "timely": now < state["deadline"]}
        if attempt_id is None:
            if state["config"]["metric"] and not result["regression"]["passed"]:
                raise ValueError("a measured baseline needs green regressions")
            state["baseline_result"], state["baseline_value"] = result_summary(observed), result["value"]
            state["status"] = "succeeded" if goal_met(observed) else "ready"
            if not observed["timely"]:
                state["status"] = "exhausted"
        else:
            state["attempt"]["result"], state["status"] = observed, "evaluated"
        return binding.save(state)


def _admit_process(binding: LoopBinding, attempt_id: str | None, pid: int) -> None:
    with binding.transaction():
        state, now = binding.load()
        if not _owns_check(state, attempt_id) or now >= state["deadline"]:
            raise ValueError("verification process admission expired or lost ownership")
        state["inflight"]["groups"].append(pid)
        binding.save(state)


def _abandon_check(binding: LoopBinding, attempt_id: str | None) -> None:
    with binding.transaction():
        state, _ = binding.load()
        if _owns_check(state, attempt_id):
            try:
                _require_groups_finished(state)
            except ValueError:
                return
            state["status"], state["inflight"] = "paused", None
            binding.save(state)


def _owns_check(state: dict, attempt_id: str | None) -> bool:
    return (state["status"] == "checking" and state["inflight"]["owner"] == os.getpid()
            and (state["attempt"] or {}).get("id") == attempt_id)


def _inputs(binding: LoopBinding, state: dict) -> LoopInputs:
    return LoopInputs(binding.project, state["config"]["owned"], state["config"]["verifiers"])
