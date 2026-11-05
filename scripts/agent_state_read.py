"""Shared read-only state locations and JSON decoding, without lifecycle imports.

Owner: state read primitives. Allowed: stdlib and support.global_state.
Forbidden: registry/scheduler mutations, capsule, IPC and policy imports.
Callers/tests: those state owners and observability; test_agent_state_read.
Verification: path/re-export identity, JSON edge cases and status parity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from support.global_state import project_state_dir_target

REGISTRY_FILENAME = "run-registry.json"
SCHEDULER_FILENAME = "scheduler.json"
EVENTS_FILENAME = "events.json"


def evidence_binding_key(project: Path, evidence_path: Path) -> str:
    """Canonical content-free key, independent of registry policy imports."""
    try:
        value = evidence_path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        value = str(evidence_path.resolve())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def registry_path(project: Path) -> Path:
    return project_state_dir_target(project.resolve()) / REGISTRY_FILENAME


def scheduler_path(project: Path) -> Path:
    return project_state_dir_target(project.resolve()) / SCHEDULER_FILENAME


def events_path(project: Path) -> Path:
    return project_state_dir_target(project.resolve()) / EVENTS_FILENAME


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {"invalid_json": True}
    return payload if isinstance(payload, dict) else {"invalid_json": True}
