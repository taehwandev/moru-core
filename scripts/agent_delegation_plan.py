"""Structured evidence for delegated or parallel agent work."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from support.global_state import project_state_dir_target


DELEGATION_PLAN_FILENAME = "agent-delegation-plan.json"
GLOB_CHARACTERS = "*?[]"
MULTI_AGENT_ROUTE_GATES = {
    "roles",
    "write scopes",
    "agent briefs",
    "integration review",
}
PARALLEL_SIGNALS = (
    "multi-agent",
    "subagent",
    "sub-agent",
    "parallel",
    "split",
    "worker",
    "병렬",
    "병렬화",
    "워커",
    "분할",
)
SEQUENTIAL_MULTI_AGENT_MARKER = "workers ran one at a time (no concurrent writers)"
SERIAL_SIGNALS = (
    "serial",
    "sequential",
    "single-agent",
    "single agent",
    "no subagent",
    "no sub-agent",
    "no parallel",
    "no worker",
    "no workers",
    "직렬",
    "단일 에이전트",
    "단일에이전트",
    "병렬 아님",
    "워커 없음",
    "워커 불필요",
    "병렬 안 함",
    "병렬하지 않",
)


def delegation_plan_path(project: Path) -> Path:
    return project_state_dir_target(project) / DELEGATION_PLAN_FILENAME


def read_delegation_plan(project: Path) -> dict[str, Any]:
    path = delegation_plan_path(project)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # path.exists() is true for a directory, and read_text then raises
        # IsADirectoryError (likewise PermissionError for an unreadable file).
        # Treat any unreadable plan as malformed and return the invalid_json
        # marker so structural validation fails closed with a clean message
        # instead of letting a raw OSError escape to the caller.
        return {"invalid_json": True, "path": str(path)}
    if isinstance(payload, dict):
        payload.setdefault("path", str(path))
        return payload
    return {"invalid_json": True, "path": str(path)}


def evidence_requires_delegation_plan(
    required_gates: list[str],
    gate_evidence: dict[str, str],
) -> bool:
    """Report whether this run must produce a concurrent-writer delegation plan.

    The plan coordinates writers that are active at the same time: its distinct
    contribution over the split-decision gate record is cross-worker
    ``owned_scope`` overlap rejection. A run that dispatched several workers one
    at a time has no concurrent writers to coordinate, so it records the
    canonical sequential marker instead of a plan. Route gates still win: a route
    carrying role/write-scope/brief/integration gates always requires the plan.
    """

    if MULTI_AGENT_ROUTE_GATES.intersection(required_gates):
        return True
    text = gate_evidence.get("multi-agent split decision", "").lower()
    if SEQUENTIAL_MULTI_AGENT_MARKER in text:
        return False
    parallel = any(signal in text for signal in PARALLEL_SIGNALS)
    serial = any(signal in text for signal in SERIAL_SIGNALS)
    return parallel and not serial


def validate_delegation_plan_evidence(
    required_gates: list[str],
    gate_evidence: dict[str, str],
    plan: dict[str, Any],
) -> list[str]:
    if not evidence_requires_delegation_plan(required_gates, gate_evidence):
        return []
    return validate_delegation_plan_structure(plan)


def validate_delegation_plan_structure(plan: dict[str, Any]) -> list[str]:
    """Return every recoverable delegation-plan schema failure in one pass."""

    if not plan:
        return [
            "parallel or multi-agent evidence requires structured "
            ".tao/agent-delegation-plan.json"
        ]
    if plan.get("invalid_json"):
        return ["agent delegation plan is not valid JSON"]

    failures: list[str] = []
    if plan.get("schema_version") != 1:
        failures.append("agent delegation plan has an unsupported schema_version")
    if plan.get("mode") != "parallel":
        failures.append(
            "agent delegation plan mode must be parallel for delegated or multi-agent work"
        )

    workers = plan.get("workers")
    if not isinstance(workers, list) or not workers:
        failures.append("agent delegation plan must include at least one worker")
    else:
        worker_ids: set[str] = set()
        owned_scopes: list[tuple[int, str]] = []
        worker_isolation: dict[int, bool] = {}
        for index, worker in enumerate(workers, start=1):
            if not isinstance(worker, dict):
                failures.append(f"agent delegation plan worker {index} must be an object")
                continue
            _require_text(worker, "id", f"worker {index}", failures)
            _require_text(worker, "role", f"worker {index}", failures)
            _require_string_list(worker, "owned_scope", f"worker {index}", failures)
            _require_string_list(worker, "forbidden_scope", f"worker {index}", failures)
            _require_contract(worker, f"worker {index}", failures)
            _require_string_list(worker, "acceptance", f"worker {index}", failures)
            _require_string_list(worker, "verification", f"worker {index}", failures)
            worker_isolation[index] = _worker_declares_worktree_isolation(
                worker, index, failures
            )
            worker_id = worker.get("id")
            if isinstance(worker_id, str) and worker_id.strip():
                normalized_id = worker_id.strip()
                if normalized_id in worker_ids:
                    failures.append(f"agent delegation plan worker {index} duplicates id {normalized_id}")
                worker_ids.add(normalized_id)
            worker_scopes = worker.get("owned_scope")
            if isinstance(worker_scopes, list):
                for scope in worker_scopes:
                    if not isinstance(scope, str) or not scope.strip():
                        continue
                    normalized_scope = scope.strip()
                    if _scope_is_noncanonical(normalized_scope):
                        failures.append(
                            f"agent delegation plan worker {index} owned_scope "
                            f"{normalized_scope!r} must be a normalized repo-relative POSIX path or glob"
                        )
                        continue
                    owned_scopes.append((index, normalized_scope))
        failures.extend(_owned_scope_overlap_failures(owned_scopes, worker_isolation))

    integration = plan.get("integration_review")
    if not isinstance(integration, dict):
        failures.append("agent delegation plan must include integration_review")
    else:
        _require_any_text(integration, ("owner", "integration_owner"), "integration_review", failures)
        _require_text(integration, "contract_drift_check", "integration_review", failures)
        _require_string_list(integration, "final_verification", "integration_review", failures)

    return failures


def worker_declares_worktree_isolation(plan: dict[str, Any], worker_id: str) -> bool:
    """Return a worker's isolation declaration, failing closed on an invalid id."""

    normalized_id = str(worker_id).strip()
    if not normalized_id:
        raise ValueError("worker_id must be a non-empty string")
    if plan.get("invalid_json"):
        raise ValueError(
            "delegation plan is not valid JSON; refusing to resolve worktree isolation"
        )
    workers = plan.get("workers")
    if not isinstance(workers, list):
        raise ValueError(
            f"delegation plan has no workers list to resolve worker_id {normalized_id!r}"
        )
    # The dispatch CLI path validates plan structure first
    # (workflow_dispatch_cli.dispatch_isolation_required), but this helper can be
    # called directly with an unvalidated plan dict where two workers share an id.
    # Collect every match and fail closed on duplicates rather than trusting file order.
    matches = [
        worker
        for worker in workers
        if isinstance(worker, dict)
        and isinstance(worker.get("id"), str)
        and worker["id"].strip() == normalized_id
    ]
    if len(matches) > 1:
        raise ValueError(
            f"delegation plan has {len(matches)} workers with duplicate id "
            f"{normalized_id!r}; refusing to resolve isolation from file order"
        )
    if not matches:
        raise ValueError(f"delegation plan has no worker with id {normalized_id!r}")
    return matches[0].get("isolation") == "worktree"


def _worker_declares_worktree_isolation(
    worker: dict[str, Any], index: int, failures: list[str]
) -> bool:
    """Validate optional isolation; only ``worktree`` permits scope overlap."""

    isolation = worker.get("isolation")
    if isolation is None:
        return False
    if isolation != "worktree":
        failures.append(
            f"agent delegation plan worker {index} isolation must be \"worktree\" when set"
        )
        return False
    return True


def _owned_scope_overlap_failures(
    owned_scopes: list[tuple[int, str]],
    worker_isolation: dict[int, bool],
) -> list[str]:
    """Reject overlapping scope unless both writers are worktree-isolated."""

    failures: list[str] = []
    for left_index, (left_worker, left_scope) in enumerate(owned_scopes):
        for right_worker, right_scope in owned_scopes[left_index + 1 :]:
            if left_worker == right_worker or not _scopes_overlap(left_scope, right_scope):
                continue
            if worker_isolation.get(left_worker) and worker_isolation.get(right_worker):
                continue
            failures.append(
                "agent delegation plan workers "
                f"{left_worker} and {right_worker} have overlapping owned_scope: "
                f"{left_scope} <> {right_scope}; overlap requires both workers to "
                "declare worktree isolation"
            )
    return failures


def _scopes_overlap(left: str, right: str) -> bool:
    """Report whether two owned scopes can touch the same path.

    Fail closed: when overlap cannot be cheaply disproven, require isolation.
    Glob scopes use real matching where possible and otherwise overlap.
    """

    left_scope = left.strip().rstrip("/")
    right_scope = right.strip().rstrip("/")
    if left_scope == right_scope:
        return True
    if not left_scope or not right_scope:
        return False
    if _scope_is_noncanonical(left_scope) or _scope_is_noncanonical(right_scope):
        return True
    left_glob = _has_glob(left_scope)
    right_glob = _has_glob(right_scope)
    if left_glob and right_glob:
        return _globs_overlap(left_scope, right_scope)
    if left_glob or right_glob:
        glob_scope, literal_scope = (
            (left_scope, right_scope) if left_glob else (right_scope, left_scope)
        )
        return _glob_matches_literal(glob_scope, literal_scope)
    # Both scopes are literal. Internal whitespace means a malformed scope we
    # cannot reason about, so fail closed and treat it as overlapping.
    if _has_internal_whitespace(left_scope) or _has_internal_whitespace(right_scope):
        return True
    return _is_path_prefix(left_scope, right_scope) or _is_path_prefix(right_scope, left_scope)


def _has_glob(scope: str) -> bool:
    return any(character in scope for character in GLOB_CHARACTERS)


def _has_internal_whitespace(scope: str) -> bool:
    """Scopes are already stripped, so any remaining whitespace is internal."""

    return any(character.isspace() for character in scope)


def _scope_is_noncanonical(scope: str) -> bool:
    """Reject aliases that could make two equivalent repo paths look disjoint."""

    return (
        scope.startswith("/")
        or "\\" in scope
        or "//" in scope
        or any(part in {".", ".."} for part in scope.rstrip("/").split("/"))
    )


def _is_path_prefix(prefix: str, path: str) -> bool:
    """Report whether ``prefix`` names ``path`` or one of its parent directories."""

    if prefix == "":
        return True
    return prefix == path or path.startswith(f"{prefix}/")


def _glob_static_prefix(scope: str) -> str:
    """Return the wildcard-free directory subtree anchoring a glob."""

    positions = [scope.find(character) for character in GLOB_CHARACTERS if character in scope]
    cutoff = min(positions) if positions else len(scope)
    prefix = scope[:cutoff]
    separator = prefix.rfind("/")
    return prefix[:separator] if separator != -1 else ""


def _glob_matches_literal(glob_scope: str, literal_scope: str) -> bool:
    """Decide glob/literal overlap from direct matches and anchored subtrees."""

    if fnmatch.fnmatchcase(literal_scope, glob_scope):
        return True
    static_prefix = _glob_static_prefix(glob_scope)
    return _is_path_prefix(static_prefix, literal_scope) or _is_path_prefix(
        literal_scope, static_prefix
    )


def _globs_overlap(left_scope: str, right_scope: str) -> bool:
    """Treat glob pairs as disjoint only across unrelated anchored subtrees."""

    left_static = _glob_static_prefix(left_scope)
    right_static = _glob_static_prefix(right_scope)
    return _is_path_prefix(left_static, right_static) or _is_path_prefix(
        right_static, left_static
    )


def _require_text(payload: dict[str, Any], key: str, label: str, failures: list[str]) -> None:
    if not isinstance(payload.get(key), str) or not payload[key].strip():
        failures.append(f"agent delegation plan {label} missing non-empty {key}")


def _require_any_text(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    label: str,
    failures: list[str],
) -> None:
    if any(isinstance(payload.get(key), str) and payload[key].strip() for key in keys):
        return
    failures.append(f"agent delegation plan {label} missing non-empty {'/'.join(keys)}")


def _require_string_list(payload: dict[str, Any], key: str, label: str, failures: list[str]) -> None:
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        failures.append(f"agent delegation plan {label} missing non-empty {key} list")


def _require_contract(payload: dict[str, Any], label: str, failures: list[str]) -> None:
    value = payload.get("contract")
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, dict) and value:
        return
    failures.append(f"agent delegation plan {label} missing contract")
