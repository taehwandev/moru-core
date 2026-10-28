"""Content-free queue and capacity primitives for the Moru Core scheduler."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_ipc import emit_event
from agent_state_lock import project_state_lock, state_lock
from support.global_state import project_state_dir_target


SCHEMA_VERSION = 1
SCHEDULER_FILENAME = "scheduler.json"
TASK_STATES = frozenset({"queued", "running", "completed", "failed", "cancelled"})
MAX_TASKS = 200


def scheduler_path(project: Path) -> Path:
    return project_state_dir_target(project.resolve()) / SCHEDULER_FILENAME


def choose_capacity(independent_slices: int, requested_workers: int = 1) -> int:
    """Choose a bounded worker capacity; small or dependent work stays serial."""

    if independent_slices < 2:
        return 1
    return max(2, min(3, requested_workers))


def enqueue_task(
    project: Path,
    run_id: str,
    *,
    priority: int = 0,
    independent_slices: int = 1,
    requested_workers: int = 1,
    max_retries: int = 0,
    partial_result_id: str | None = None,
) -> dict[str, Any]:
    if not run_id or not isinstance(run_id, str):
        raise ValueError("run_id is required")
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "task_id": uuid.uuid4().hex,
        "run_id": run_id,
        "project_id": _opaque_project_id(project),
        "priority": int(priority),
        "independent_slices": max(0, int(independent_slices)),
        "requested_workers": max(1, int(requested_workers)),
        "attempt": 1,
        "max_attempts": max(1, int(max_retries) + 1),
        "state": "queued",
        "queued_at": now,
        "updated_at": now,
    }
    if partial_result_id:
        task["partial_result_id"] = str(partial_result_id)
    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        payload["tasks"].append(task)
        payload["tasks"] = payload["tasks"][-MAX_TASKS:]
        _write_scheduler(path, payload)
    _safe_event(project, "task.queued", run_id=run_id, task_id=task["task_id"], state="queued")
    return task


def claim_next(project: Path, *, capacity: int = 1) -> dict[str, Any] | None:
    """Claim the highest-priority queued task when capacity is available."""

    if capacity < 1:
        raise ValueError("capacity must be positive")
    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        running = [task for task in payload["tasks"] if task.get("state") == "running"]
        if len(running) >= capacity:
            return None
        queued = [task for task in payload["tasks"] if task.get("state") == "queued"]
        if not queued:
            return None
        target = max(queued, key=lambda task: (int(task.get("priority", 0)), task.get("queued_at", "")))
        target["state"] = "running"
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_scheduler(path, payload)
    _safe_event(project, "task.claimed", run_id=str(target["run_id"]), task_id=str(target["task_id"]), state="running")
    return target


def claim_task(project: Path, task_id: str, *, capacity: int = 1) -> dict[str, Any] | None:
    """Claim one specific queued task without allowing another task to win the race."""

    if capacity < 1:
        raise ValueError("capacity must be positive")
    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        running = [task for task in payload["tasks"] if task.get("state") == "running"]
        if len(running) >= capacity:
            return None
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") != "queued":
                continue
            task["state"] = "running"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(project, "task.claimed", run_id=str(task["run_id"]), task_id=task_id, state="running")
    return task


def transition_task(
    project: Path,
    task_id: str,
    state: str,
    *,
    expected_state: str | None = None,
    expected_attempt: int | None = None,
) -> dict[str, Any] | None:
    """Transition a task; with expectations, skip a task another owner has since moved."""

    if state not in TASK_STATES:
        raise ValueError(f"unsupported task state: {state}")
    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id:
                continue
            if expected_state is not None and task.get("state") != expected_state:
                return None
            if expected_attempt is not None and int(task.get("attempt", 1)) != expected_attempt:
                return None
            task["state"] = state
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(project, "task.transitioned", run_id=str(task["run_id"]), task_id=task_id, state=state)
    return task


def heartbeat_task(project: Path, task_id: str, *, expected_attempt: int | None = None) -> dict[str, Any] | None:
    """Refresh a running task lease without changing its lifecycle state."""

    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") != "running":
                continue
            if expected_attempt is not None and int(task.get("attempt", 1)) != expected_attempt:
                return None
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(project, "task.heartbeat", run_id=str(task["run_id"]), task_id=task_id, state="running")
    return task


def checkpoint_task(project: Path, task_id: str, result_id: str) -> dict[str, Any] | None:
    """Record an opaque partial-result checkpoint for later retry/resume."""

    if not result_id:
        raise ValueError("result_id is required")
    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") != "running":
                continue
            task["partial_result_id"] = result_id
            task["partial_updated_at"] = datetime.now(timezone.utc).isoformat()
            task["updated_at"] = task["partial_updated_at"]
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(project, "worker.partial", run_id=str(task["run_id"]), task_id=task_id, state="paused", result_id=result_id)
    return task


def cancel_task(project: Path, task_id: str) -> dict[str, Any] | None:
    """Cancel a queued or running task through the standard terminal transition."""

    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") not in {"queued", "running"}:
                continue
            task["state"] = "cancelled"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(project, "task.cancelled", run_id=str(task["run_id"]), task_id=task_id, state="cancelled")
    return task


def retry_task(project: Path, task_id: str) -> dict[str, Any] | None:
    """Requeue a failed task only while its bounded retry budget remains."""

    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") != "failed":
                continue
            if int(task.get("attempt", 1)) >= int(task.get("max_attempts", 1)):
                return None
            task["attempt"] = int(task.get("attempt", 1)) + 1
            task["state"] = "queued"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(
        project,
        "task.requeued",
        run_id=str(task["run_id"]),
        task_id=task_id,
        state="queued",
        result_id=str(task.get("partial_result_id")) if task.get("partial_result_id") else None,
    )
    return task


def resume_task(project: Path, task_id: str) -> dict[str, Any] | None:
    """Requeue a failed task and retain its opaque partial-result resume token."""

    path = scheduler_path(project)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("task_id") != task_id or task.get("state") != "failed":
                continue
            if not task.get("partial_result_id") or int(task.get("attempt", 1)) >= int(task.get("max_attempts", 1)):
                return None
            task["attempt"] = int(task.get("attempt", 1)) + 1
            task["state"] = "queued"
            task["resume_requested_at"] = datetime.now(timezone.utc).isoformat()
            task["updated_at"] = task["resume_requested_at"]
            _write_scheduler(path, payload)
            break
        else:
            return None
    _safe_event(
        project,
        "task.resumed",
        run_id=str(task["run_id"]),
        task_id=task_id,
        state="queued",
        result_id=str(task["partial_result_id"]),
    )
    return task


def recover_stale_tasks(project: Path, *, stale_after_seconds: int = 3600) -> list[dict[str, Any]]:
    """Mark queued/running tasks stale so maintenance can apply bounded retry."""

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    path = scheduler_path(project)
    recovered: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    with project_state_lock(project), state_lock(path):
        payload = _read_scheduler(path)
        for task in payload["tasks"]:
            if task.get("state") not in {"queued", "running"}:
                continue
            try:
                updated = datetime.fromisoformat(str(task.get("updated_at")))
            except (TypeError, ValueError):
                continue
            if updated >= cutoff:
                continue
            task["state"] = "failed"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            recovered.append(task)
        if recovered:
            _write_scheduler(path, payload)
    for task in recovered:
        _safe_event(project, "task.recovered", run_id=str(task["run_id"]), task_id=str(task["task_id"]), state="failed")
    return recovered


def _read_scheduler(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("tasks"), list):
        return {"schema_version": SCHEMA_VERSION, "tasks": []}
    return payload


def _write_scheduler(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _opaque_project_id(project: Path) -> str:
    return hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()


def _safe_event(project: Path, event_type: str, *, run_id: str, task_id: str, state: str, result_id: str | None = None) -> None:
    try:
        emit_event(project, event_type, run_id=run_id, task_id=task_id, state=state, result_id=result_id)
    except (OSError, ValueError):
        return
