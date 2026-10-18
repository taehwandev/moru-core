"""Closed enrollment and persistence boundaries for opt-in loop runs.

Owner: loop JSON validation. Imports: standard library only. No execution,
source writes or authorization. Callers/tests: loop state and contract tests.
"""

from __future__ import annotations

import json
import math


CONFIG_FIELDS = {"objective", "owned", "verifiers", "directory", "goal_pattern",
                 "regression_pattern", "max_iterations", "max_seconds", "max_model_calls", "metric"}
STATE_FIELDS = {"schema_version", "run_id", "config", "created_at", "deadline",
                "updated_at", "status", "iterations", "model_calls", "accepted",
                "baseline_value", "attempt", "history", "baseline_result", "inflight"}
STATES = {"ready", "attempting", "checking", "evaluated", "paused", "succeeded", "exhausted", "cancelled"}


def bounded_text(value: object, maximum: int = 280) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 for char in value)):
        raise ValueError("expected bounded single-line text")
    return value


def finite_number(value: object) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("expected finite numeric value")
    return float(value)


def positive_count(value: object, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("count is outside the declared bounds")
    return value


def validate_config(config: dict) -> None:
    if not isinstance(config, dict) or set(config) != CONFIG_FIELDS:
        raise ValueError("invalid loop contract fields")
    bounded_text(config["objective"])
    positive_count(config["max_iterations"], 1000)
    positive_count(config["max_seconds"], 86400)
    positive_count(config["max_model_calls"], 10000)
    for key in ("directory", "goal_pattern", "regression_pattern"):
        bounded_text(config[key], 240)
    for key in ("owned", "verifiers"):
        if not isinstance(config[key], list) or not 1 <= len(config[key]) <= 64:
            raise ValueError("loop file lists must contain 1 to 64 paths")
    metric = config["metric"]
    if metric is not None:
        if (not isinstance(metric, dict) or set(metric) != {"direction", "min_delta"}
                or metric["direction"] not in {"min", "max"}
                or finite_number(metric["min_delta"]) <= 0):
            raise ValueError("invalid measurement contract")


def validate_state(state: dict, run_id: str) -> None:
    if (not isinstance(state, dict) or set(state) != STATE_FIELDS
            or type(state["schema_version"]) is not int or state["schema_version"] != 1
            or state["run_id"] != run_id
            or state["status"] not in STATES):
        raise ValueError("invalid or incompatible loop state")
    validate_config(state["config"])
    for key in ("created_at", "deadline", "updated_at"):
        finite_number(state[key])
    if state["deadline"] != state["created_at"] + state["config"]["max_seconds"]:
        raise ValueError("loop deadline differs from enrollment")
    for key, limit in (("iterations", "max_iterations"), ("model_calls", "max_model_calls")):
        if type(state[key]) is not int or not 0 <= state[key] <= state["config"][limit]:
            raise ValueError("invalid consumed budget")
    _snapshot(state["accepted"])
    if state["baseline_value"] is not None:
        finite_number(state["baseline_value"])
    if not isinstance(state["history"], list) or len(state["history"]) > state["iterations"]:
        raise ValueError("invalid loop history")
    if state["attempt"] is not None:
        _attempt(state["attempt"])
    for item in state["history"]:
        _attempt(item)
        if item["verdict"] == "pending":
            raise ValueError("history cannot contain an unresolved verdict")
    rows = [*state["history"], *([state["attempt"]] if state["attempt"] else [])]
    if (len(rows) != state["iterations"]
            or sum(row["calls"] for row in rows) != state["model_calls"]
            or len({row["id"] for row in rows}) != len(rows)):
        raise ValueError("attempt history differs from consumed budgets")
    if state["inflight"] is not None:
        inflight = state["inflight"]
        if (not isinstance(inflight, dict) or set(inflight) != {"owner", "groups"}
                or not isinstance(inflight["groups"], list) or len(inflight["groups"]) > 2
                or len(set(inflight["groups"])) != len(inflight["groups"])):
            raise ValueError("invalid verification process group record")
        positive_count(inflight["owner"], 2 ** 31)
        for group in inflight["groups"]:
            positive_count(group, 2 ** 31)
    if (state["status"] == "checking") != (state["inflight"] is not None):
        raise ValueError("invalid verification process state")
    if state["status"] in {"attempting", "evaluated"} and state["attempt"] is None:
        raise ValueError("active loop is missing its attempt")
    if state["baseline_result"] is not None:
        _result(state["baseline_result"], candidate=False)
    if len(json.dumps(state, allow_nan=False).encode()) > 2 * 1024 * 1024:
        raise ValueError("loop state exceeds storage budget")


def _snapshot(value: object) -> None:
    if (not isinstance(value, dict)
            or set(value) != {"head", "index", "outside", "owned", "verifiers"}
            or not all(isinstance(value[key], str) for key in ("head", "index", "outside"))
            or not all(isinstance(value[key], dict) for key in ("owned", "verifiers"))):
        raise ValueError("invalid accepted input snapshot")


def _attempt(value: object) -> None:
    if (not isinstance(value, dict)
            or set(value) != {"id", "hypothesis", "started_at", "calls", "result", "verdict"}
            or not isinstance(value["id"], str) or len(value["id"]) != 32
            or type(value["calls"]) is not int or value["calls"] < 1
            or value["verdict"] not in {"pending", "accepted", "rejected"}):
        raise ValueError("invalid loop attempt")
    bounded_text(value["hypothesis"])
    finite_number(value["started_at"])
    if value["result"] is not None:
        _result(value["result"], candidate=value["verdict"] == "pending")


def _result(value: object, *, candidate: bool) -> None:
    keys = {"regression", "goal", "value", "timely"} | ({"candidate"} if candidate else set())
    if not isinstance(value, dict) or set(value) != keys or type(value["timely"]) is not bool:
        raise ValueError("invalid observed loop result")
    if candidate:
        _snapshot(value["candidate"])
    if value["value"] is not None:
        finite_number(value["value"])
    for name in ("regression", "goal"):
        check = value[name]
        if (not isinstance(check, dict) or set(check) != {"exit", "tests", "passed"}
                or type(check["exit"]) is not int or type(check["tests"]) is not int
                or check["tests"] < 0 or type(check["passed"]) is not bool
                or check["passed"] and (check["exit"] != 0 or check["tests"] == 0)):
            raise ValueError("invalid observed check result")


def budget_allows(state: dict, now: float, calls: int = 0, *, new_attempt: bool = False) -> bool:
    config = state["config"]
    if state["status"] == "exhausted":
        return False
    if (now >= state["deadline"]
            or new_attempt and state["iterations"] >= config["max_iterations"]
            or (new_attempt or calls > 0) and state["model_calls"] >= config["max_model_calls"]):
        state["status"] = "exhausted"
        return False
    if state["model_calls"] + calls > config["max_model_calls"]:
        raise ValueError("requested calls exceed the remaining model-call budget")
    return True


def goal_met(result: dict) -> bool:
    return result["timely"] and result["regression"]["passed"] and result["goal"]["passed"]


def candidate_improves(state: dict, result: dict) -> bool:
    metric = state["config"]["metric"]
    if metric is None:
        return goal_met(result)
    direction = 1 if metric["direction"] == "max" else -1
    return direction * (result["value"] - state["baseline_value"]) >= metric["min_delta"]


def result_summary(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "candidate"}
