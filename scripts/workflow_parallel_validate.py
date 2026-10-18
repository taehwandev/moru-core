"""Validation for workflow route parallel execution hints."""

from __future__ import annotations


PARALLEL_PHASE_MODES = {"serial", "parallel", "conditional_parallel"}


def validate_parallel_execution_plan(plan: object, gates: list[str]) -> list[str]:
    failures: list[str] = []
    if not isinstance(plan, dict):
        return ["parallel_execution must be an object"]
    if plan.get("schema_version") != 1:
        failures.append("parallel_execution.schema_version must be 1")
    if not isinstance(plan.get("strategy"), str) or not plan["strategy"].strip():
        failures.append("parallel_execution.strategy must be a non-empty string")
    _validate_delegation_policy(plan.get("delegation_policy"), failures)

    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        return [*failures, "parallel_execution.phases must be a non-empty list"]

    phase_ids: set[str] = set()
    route_gates = set(gates)
    for index, phase in enumerate(phases, start=1):
        if not isinstance(phase, dict):
            failures.append(f"parallel_execution phase {index} must be an object")
            continue
        phase_id = _validate_phase_header(phase, index, phase_ids, failures)
        _validate_string_list(phase, "after", phase_id, failures, allow_empty=True)
        for key in ("gates", "tasks", "constraints"):
            _validate_string_list(phase, key, phase_id, failures)
        _validate_phase_gates(phase, phase_id, route_gates, failures)
    return failures


def _validate_delegation_policy(policy: object, failures: list[str]) -> None:
    if not isinstance(policy, dict):
        failures.append("parallel_execution.delegation_policy must be an object")
        return
    mode = policy.get("mode")
    if mode not in {"on_demand", "serial"}:
        failures.append(
            "parallel_execution.delegation_policy.mode must be on_demand or serial"
        )
    for key, expected in (
        ("default_execution", "same_session"),
        ("cross_runtime_policy", "optional_existing_access"),
    ):
        if policy.get(key) != expected:
            failures.append(f"parallel_execution.delegation_policy.{key} must be {expected}")
    if policy.get("explicit_user_request_required") is not False:
        failures.append(
            "parallel_execution.delegation_policy.explicit_user_request_required must be false"
        )
    minimum = policy.get("minimum_independent_slices")
    maximum = policy.get("maximum_workers")
    if mode == "serial":
        if minimum != 0 or maximum != 0:
            failures.append(
                "serial parallel_execution policy must set minimum_independent_slices and maximum_workers to 0"
            )
    elif not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2:
        failures.append(
            "parallel_execution.delegation_policy.minimum_independent_slices must be at least 2"
        )
    elif not isinstance(maximum, int) or isinstance(maximum, bool) or not 2 <= maximum <= 3:
        failures.append(
            "parallel_execution.delegation_policy.maximum_workers must be between 2 and 3"
        )
    for key in ("required_preconditions", "serial_fallbacks"):
        value = policy.get(key)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            failures.append(
                f"parallel_execution.delegation_policy.{key} must be a non-empty string list"
            )


def _validate_phase_header(
    phase: dict[str, object],
    index: int,
    phase_ids: set[str],
    failures: list[str],
) -> str:
    phase_id = phase.get("id")
    label = str(phase_id or index)
    if not isinstance(phase_id, str) or not phase_id.strip():
        failures.append(f"parallel_execution phase {index} missing id")
    elif phase_id in phase_ids:
        failures.append(f"parallel_execution phase id `{phase_id}` is duplicated")
    else:
        phase_ids.add(phase_id)
    mode = phase.get("mode")
    if mode not in PARALLEL_PHASE_MODES:
        failures.append(f"parallel_execution phase `{label}` has invalid mode `{mode}`")
    return label


def _validate_string_list(
    phase: dict[str, object],
    key: str,
    phase_id: str,
    failures: list[str],
    *,
    allow_empty: bool = False,
) -> None:
    value = phase.get(key)
    valid = isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
    if not valid or (not allow_empty and not value):
        failures.append(f"parallel_execution phase `{phase_id}` requires non-empty string list `{key}`")


def _validate_phase_gates(
    phase: dict[str, object],
    phase_id: str,
    route_gates: set[str],
    failures: list[str],
) -> None:
    phase_gates = phase.get("gates")
    if not isinstance(phase_gates, list):
        return
    unknown = [gate for gate in phase_gates if gate not in route_gates]
    if unknown:
        failures.append(
            f"parallel_execution phase `{phase_id}` references unknown gate(s): {', '.join(unknown)}"
        )
