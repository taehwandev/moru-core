"""Registry-owned loop state transactions; enrollment never grants authority.

Owner: loop admission and storage. Imports: existing run registry, session and
atomic state contracts. Callers/tests: LoopRun and binding tests. No source I/O.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

from agent_execution_capsule_state import atomic_write_json, read_json_object
from agent_loop_contract import validate_state
from agent_run_registry import ledger_writable_run_claim_transaction, registry_path, route_fingerprint
from agent_runtime_session import (resolve_owned_runtime_evidence, resolve_runtime_evidence,
                                   runtime_session, same_runtime_session)
from support.global_state import project_state_dir_target
from workflow_effect_policy import route_minimum_effect


class LoopBinding:
    def __init__(self, project: Path, run_id: str | None = None):
        self.project = project.resolve()
        if run_id is not None:
            if not re.fullmatch(r"[0-9a-f]{32}", run_id):
                raise ValueError("invalid loop run id")
            self.evidence = project_state_dir_target(self.project) / "runs" / run_id / "preflight.json"
        else:
            self.evidence = _current_binding(self.project)[0]
        if self.evidence is None or self.evidence.name != "preflight.json":
            raise ValueError("loop requires an exact registered run")
        self.run_id = self.evidence.parent.name
        if not re.fullmatch(r"[0-9a-f]{32}", self.run_id):
            raise ValueError("loop requires a durable run directory")
        self.path = self.evidence.parent / "loop.json"
        if self.path.resolve() != self.path or self.evidence.resolve() != self.evidence:
            raise ValueError("loop state cannot follow symlinks")

    @contextmanager
    def transaction(self):
        if self.path.resolve() != self.path or self.evidence.resolve() != self.evidence:
            raise ValueError("loop state cannot follow symlinks")
        active, identity = _current_binding(self.project)
        if active != self.evidence:
            raise ValueError("loop is not this session's active run")
        with ledger_writable_run_claim_transaction(
                self.project, self.evidence, self.run_id, self.path) as owned:
            preflight = read_json_object(self.evidence)
            runs = read_json_object(registry_path(self.project)).get("runs", [])
            run = next((item for item in runs if item.get("run_id") == self.run_id), {})
            route = preflight.get("route") or {}
            if (not owned or run.get("state") != "running"
                    or run.get("command") != route.get("command")
                    or run.get("route_fingerprint") != route_fingerprint(route)
                    or preflight.get("project") != str(self.project)
                    or preflight.get("execution_mode", {}).get("read_only", True)
                    or route_minimum_effect(route.get("command", "")) == "read"
                    or not same_runtime_session(preflight.get("runtime_session"), identity,
                                                resume_generation=int(run.get("resume_generation") or 0))):
                raise ValueError("loop requires the current writable run owner")
            yield

    def read(self) -> dict:
        if self.path.is_symlink() or self.path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("invalid loop state file")
        state = json.loads(self.path.read_text(encoding="utf-8"))
        validate_state(state, self.run_id)
        return state

    def load(self) -> tuple[dict, float]:
        state = self.read()
        now = time.time()
        if now < state["updated_at"]:
            raise ValueError("clock moved backwards; budgets cannot be extended")
        state["updated_at"] = now
        return state, now

    def save(self, state: dict) -> dict:
        validate_state(state, self.run_id)
        atomic_write_json(self.path, state)
        return state


def _current_binding(project: Path) -> tuple:
    identity = runtime_session()
    evidence = resolve_runtime_evidence(project)
    if evidence is None and not identity:
        evidence = resolve_owned_runtime_evidence(project)
        if evidence is not None:
            identity = read_json_object(evidence).get("runtime_session") or {}
    return evidence, identity


def _require_groups_finished(state: dict) -> None:
    for group in (state["inflight"] or {}).get("groups", []):
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise ValueError("verification child group cannot be probed; reconcile its handle") from error
        raise ValueError("verification child group is still live; reconcile its handle")


def _require_no_check(state: dict) -> None:
    inflight = state["inflight"]
    if inflight is not None:
        _require_groups_finished(state)
        try:
            os.kill(inflight["owner"], 0)
        except ProcessLookupError:
            return
        except PermissionError as error:
            raise ValueError("verification process cannot be probed; reconcile its handle") from error
        raise ValueError("verification process is still live; wait for its handle")
