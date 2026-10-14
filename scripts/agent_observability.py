"""Read-only content-free status API for the Moru Core layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone
import uuid

from agent_ipc import events_path
from agent_run_registry import registry_path
from agent_scheduler import scheduler_path
from agent_execution_capsule_state import read_json_object
from agent_state_lock import project_state_lock, state_lock
from agent_os_api import api_contract_manifest, runtime_adapter_catalog


API_VERSION = 2


def status_snapshot(project: Path) -> dict[str, Any]:
    project = project.resolve()
    captured_at = datetime.now(timezone.utc).isoformat()
    with project_state_lock(project):
        with state_lock(registry_path(project)):
            registry = read_json_object(registry_path(project))
        with state_lock(scheduler_path(project)):
            scheduler = read_json_object(scheduler_path(project))
        with state_lock(events_path(project)):
            events_payload = read_json_object(events_path(project))
    runs = registry.get("runs") if isinstance(registry.get("runs"), list) else []
    tasks = scheduler.get("tasks") if isinstance(scheduler.get("tasks"), list) else []
    events = events_payload.get("events") if isinstance(events_payload.get("events"), list) else []
    task_counts: dict[str, int] = {}
    for task in tasks:
        state = str(task.get("state") or "unknown")
        task_counts[state] = task_counts.get(state, 0) + 1
    event_counts: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "unknown")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    return {
        "api_version": API_VERSION,
        "snapshot_id": uuid.uuid4().hex,
        "captured_at": captured_at,
        "consistency": "project-state-lock",
        "api_contract": api_contract_manifest(),
        "runtime_adapters": runtime_adapter_catalog(),
        "active_runs": sum(run.get("state") in {"running", "paused"} for run in runs if isinstance(run, dict)),
        "task_counts": task_counts,
        "events": event_counts,
        "registry_present": registry_path(project).exists(),
        "scheduler_present": scheduler_path(project).exists(),
    }
