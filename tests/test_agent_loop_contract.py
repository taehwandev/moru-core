"""Corrupt persisted state cannot fabricate proof or reset consumed budgets."""

from __future__ import annotations

import copy
import unittest

from _moru_test_support import ROOT
from agent_loop_contract import validate_config, validate_state
import test_agent_loop_state as fixture


def valid_state():
    return {"schema_version": 1, "run_id": "a" * 32, "config": fixture.loop_config(),
            "created_at": 100.0, "deadline": 160.0, "updated_at": 100.0,
            "status": "ready", "iterations": 0, "model_calls": 0,
            "accepted": {"head": "a" * 40, "index": "b" * 64, "outside": "c" * 64,
                         "owned": {}, "verifiers": {}},
            "baseline_value": None, "attempt": None, "history": [],
            "baseline_result": None, "inflight": None}


class LoopContractTests(unittest.TestCase):
    def test_enrollment_rejects_nonfinite_or_nonpositive_noise_floor(self):
        for value in (float("nan"), float("inf"), True, 0, -1, 10 ** 1000):
            with self.subTest(value_type=type(value).__name__):
                config = fixture.loop_config()
                config["metric"]["min_delta"] = value
                with self.assertRaises(ValueError):
                    validate_config(config)

    def test_unknown_fields_or_schema_are_not_silently_ignored(self):
        for key, value in (("schema_version", 2), ("unrecognized", True)):
            state = valid_state()
            state[key] = value
            with self.assertRaises(ValueError):
                validate_state(state, state["run_id"])

    def test_persisted_deadline_cannot_extend_the_contract(self):
        state = valid_state()
        state["deadline"] += 1
        with self.assertRaisesRegex(ValueError, "deadline"):
            validate_state(state, state["run_id"])

    def test_consumed_budget_requires_its_actual_attempt_history(self):
        for key in ("iterations", "model_calls"):
            state = valid_state()
            state[key] = 1
            with self.assertRaisesRegex(ValueError, "history"):
                validate_state(state, state["run_id"])

    def test_passing_result_requires_typed_positive_observed_counts(self):
        result = {"regression": {"exit": 0, "tests": 1, "passed": True},
                  "goal": {"exit": 0, "tests": 1, "passed": True}, "value": 5, "timely": True}
        for field, value in (("exit", 1), ("tests", 0), ("tests", True), ("passed", "yes")):
            state = valid_state()
            state["baseline_result"] = copy.deepcopy(result)
            state["baseline_result"]["goal"][field] = value
            with self.assertRaises(ValueError):
                validate_state(state, state["run_id"])

    def test_inflight_group_record_is_bound_to_checking_state(self):
        state = valid_state()
        state["inflight"] = {"owner": 123, "groups": [456]}
        with self.assertRaises(ValueError):
            validate_state(state, state["run_id"])
        state["status"] = "checking"
        validate_state(state, state["run_id"])
        state["inflight"]["groups"] = [456, 456]
        with self.assertRaises(ValueError):
            validate_state(state, state["run_id"])
