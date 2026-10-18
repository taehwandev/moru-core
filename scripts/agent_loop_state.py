"""Enrollment, attempt budgets and recovery for an existing Moru writable run.

Owner: LoopRun. Imports: loop contract/storage/input/candidate owners.
Forbidden: source/Git writes, model launches, wakeups and gate fabrication.
Callers/tests: loop CLI, test_agent_loop_state and integration tests.
"""

from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path

from agent_loop_binding import LoopBinding, _require_no_check
from agent_loop_candidate import evaluate, resolve
from agent_loop_check import LoopCheck
from agent_loop_contract import bounded_text, budget_allows, positive_count, validate_config
from agent_loop_inputs import LoopInputs


class LoopRun:
    def __init__(self, project: Path, run_id: str | None = None):
        self.binding = LoopBinding(project, run_id)
        self.project = self.binding.project

    def status(self) -> dict:
        return self.binding.read()

    def start(self, config: dict) -> dict:
        validate_config(config)
        inputs = LoopInputs(self.project, config["owned"], config["verifiers"])
        LoopCheck(self.project, config, self.binding.path.parent / "loop-artifacts").validate(inputs)
        with self.binding.transaction():
            if self.binding.path.exists():
                raise ValueError("this run already has a loop; budgets cannot reset")
            now = time.time()
            self.binding.save({"schema_version": 1, "run_id": self.binding.run_id,
                "config": copy.deepcopy(config), "created_at": now, "deadline": now + config["max_seconds"],
                "updated_at": now, "status": "ready", "iterations": 0, "model_calls": 0,
                "accepted": inputs.capture(), "baseline_value": None, "attempt": None,
                "history": [], "baseline_result": None, "inflight": None})
        return self.evaluate()

    def begin(self, hypothesis: str, calls: int = 1) -> dict:
        bounded_text(hypothesis)
        positive_count(calls, 10000)
        with self.binding.transaction():
            state, now = self.binding.load()
            if state["status"] != "ready" or state["baseline_result"] is None:
                raise ValueError("loop must have a baseline and no pending attempt")
            inputs = _inputs(self.project, state)
            inputs.assert_restored(inputs.capture(), state["accepted"])
            if budget_allows(state, now, calls, new_attempt=True):
                state["iterations"] += 1
                state["model_calls"] += calls
                state["attempt"] = {"id": uuid.uuid4().hex, "hypothesis": hypothesis,
                                    "started_at": now, "calls": calls, "result": None, "verdict": "pending"}
                state["status"] = "attempting"
            return self.binding.save(state)

    def reserve(self, calls: int) -> dict:
        positive_count(calls, 10000)
        with self.binding.transaction():
            state, now = self.binding.load()
            if state["status"] != "attempting":
                raise ValueError("calls require an active attempt")
            inputs = _inputs(self.project, state)
            inputs.assert_scope(inputs.capture(), state["accepted"])
            if budget_allows(state, now, calls):
                state["model_calls"] += calls
                state["attempt"]["calls"] += calls
            return self.binding.save(state)

    def evaluate(self) -> dict:
        return evaluate(self.binding)

    def resolve(self, accept: bool) -> dict:
        return resolve(self.binding, accept)

    def pause(self) -> dict:
        with self.binding.transaction():
            state, _ = self.binding.load()
            if state["status"] in {"succeeded", "exhausted", "cancelled"}:
                raise ValueError("terminal loop cannot pause")
            _require_no_check(state)
            state["status"], state["inflight"] = "paused", None
            return self.binding.save(state)

    def resume(self) -> dict:
        with self.binding.transaction():
            state, now = self.binding.load()
            if state["status"] not in {"paused", "checking"}:
                raise ValueError("loop is not paused or interrupted")
            _require_no_check(state)
            inputs = _inputs(self.project, state)
            inputs.assert_scope(inputs.capture(), state["accepted"])
            state["inflight"] = None
            state["status"] = "attempting" if state["attempt"] else "ready"
            if state["attempt"]:
                state["attempt"]["result"] = None
            budget_allows(state, now)
            return self.binding.save(state)

    def cancel(self) -> dict:
        with self.binding.transaction():
            state, _ = self.binding.load()
            if state["status"] == "succeeded":
                raise ValueError("a successful loop cannot be rewritten as cancelled")
            _require_no_check(state)
            state["status"], state["inflight"] = "cancelled", None
            return self.binding.save(state)


def _inputs(project: Path, state: dict) -> LoopInputs:
    return LoopInputs(project, state["config"]["owned"], state["config"]["verifiers"])
