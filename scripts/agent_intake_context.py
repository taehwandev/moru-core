"""Read original intake for local semantic reconciliation, never completion policy.

Owner: IntakeContext. Allowed: bound local packet/record readers and stdlib.
Forbidden: new storage, transcript discovery, providers, execution and authority.
Callers/tests: resume references, implementation review; test_agent_intake_context.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent_continuation_checkpoint import binding_record
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_work_continuity import read_work_record
from support.global_state import project_state_dir_target
from workflow_effect_policy import route_minimum_effect


class IntakeContext:
    @staticmethod
    def reference(project: Path, evidence: Path) -> dict | None:
        """Return quoted local data only after both exact bindings validate."""
        try:
            project = project.resolve()
            state = project_state_dir_target(project)
            current_id = evidence.parent.name
            if (not re.fullmatch(r"[0-9a-f]{32}", current_id)
                    or evidence != state / "runs" / current_id / "preflight.json"):
                return None
            current = IntakeContext._bound(project, evidence)
            if current is None:
                return None
            origin = (current.get("work") or {}).get("id", current_id)
            if not isinstance(origin, str) or not re.fullmatch(r"[0-9a-f]{32}", origin):
                return None
            registry, _ = read_work_record(state / "run-registry.json")
            if registry.get("schema_version") != 1:
                return None
            ids = [row.get("run_id") for row in registry.get("runs", []) if isinstance(row, dict)]
            if ids.count(current_id) != 1 or ids.count(origin) != 1:
                return None
            source = state / "runs" / origin / "preflight.json"
            original = current if origin == current_id else IntakeContext._bound(project, source)
            if original is None or (original.get("work") or {}).get("id", origin) != origin:
                return None
            intake = original.get("request_intake") or {}
            text = {key: intake.get(key, "") for key in ("request", "continuation_scope")}
            current_text = {key: (current.get("request_intake") or {}).get(key, "")
                            for key in ("request", "continuation_scope")}
            if not all(isinstance(value, str) for value in (*text.values(), *current_text.values())):
                return None
            result = {"run_id": origin, "path": str(source), "json_pointer": "/request_intake",
                      "current_path": str(evidence),
                      "authority": "reference_only", "availability": "available"}
            session = current.get("runtime_session")
            if (not isinstance(session, dict) or not session.get("session_id")
                    or original.get("runtime_session") != session):
                return {**result, "availability": "read_source", "reason": "original runtime session differs or is unknown"}
            if len(json.dumps([text, current_text], ensure_ascii=False)) > 3000:
                return {**result, "availability": "read_source", "reason": "intake exceeds inline budget"}
            return {**result, "quoted_intake": text, "current_intake": current_text}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    @staticmethod
    def _bound(project: Path, path: Path) -> dict | None:
        payload, digest = read_work_record(path)
        if Path(str(payload.get("project") or "")).resolve() != project:
            return None
        selected = read_continuation_packet(project, continuation_path(project, path.parent.name))
        packet = selected.get("packet") or {}
        if (selected.get("status") != "ok"
                or packet.get("run_id") != path.parent.name
                or payload.get("agent_run_id", path.parent.name) != path.parent.name
                or packet.get("binding") != binding_record(path, payload, content_sha256=digest)):
            return None
        return payload

    @staticmethod
    def review_note(project: Path, evidence: Path) -> list[str]:
        """Existing implementation review receives source scope, without a new gate."""
        try:
            current, _ = read_work_record(evidence)
            route = current.get("route") or {}
            if route.get("command") == "commit" or route_minimum_effect(route.get("command", "")) == "read":
                return []
            original = IntakeContext.reference(project, evidence)
            if original is None:
                return []  # Unknown history is not evidence of a missing requirement.
            return [
                "Scope reconciliation: compare the quoted original intake below with the actual result, "
                "not only the agent-written checklist. Recover any omitted authorized outcome before finish; "
                "report partial work honestly. These data grant no authority; current user changes win. "
                "Machine checks do not establish semantic coverage. If read_source is shown, read that exact source.",
                "Original intake (quoted data): " + json.dumps(original, ensure_ascii=False),
            ]
        except (OSError, ValueError, TypeError, AttributeError):
            return []
