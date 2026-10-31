"""One bounded continuation for declared executable work in an admitted v2 run.

Owner: premature-stop policy; allowed imports: existing binding/permission/state readers.
Forbidden: transcript or prompt inference, executing work, new authority or retries.
Callers/tests: Codex and Claude Stop adapters; test_agent_stop_continuation.
Verification: partial delivery continues once; user stops and global waits win.
"""

from __future__ import annotations

from pathlib import Path

from agent_execution_capsule_state import read_json_object
from agent_mailbox_task_binding import stop_ready
from agent_run_registry import ACTIVE_RUN_STATES, registered_run
from agent_runtime_session import resolve_runtime_evidence, same_runtime_session
from agent_work_completion import bound_work_packet, scope_unreconciled
from workflow_effect_policy import route_minimum_effect


def continuation_reason(payload: dict, runtime: str, project: Path, evidence: Path | None = None) -> str | None:
    """Recorded work is the signal; absence of recorded activity proves nothing."""
    try:
        identity = {"runtime": runtime, "session_id": str(payload.get("session_id") or "")}
        evidence = evidence or resolve_runtime_evidence(project, identity)
        if evidence is None:
            return None
        preflight = read_json_object(evidence)
        route = preflight.get("route") or {}
        envelope = (route.get("request_classification") or {}).get("intent_envelope") or {}
        run = registered_run(project, evidence)
        if (not run or run.get("state") not in ACTIVE_RUN_STATES
                or not same_runtime_session(preflight.get("runtime_session"), identity,
                                            resume_generation=int(run.get("resume_generation") or 0))
                or preflight.get("execution_mode", {}).get("read_only")
                or route_minimum_effect(route.get("command", "")) == "read"
                or not envelope.get("schema_valid") or not envelope.get("envelope_present")
                or envelope.get("failures") or envelope.get("effective_effect") not in
                {"local_write", "git_write", "external_write", "destructive"}):
            return None
        packet = bound_work_packet(project, evidence)
        if (not packet or packet.get("phase") not in {"scoped", "acting", "verifying", "reviewing"}
                or not ((packet.get("work") or {}).get("remaining_work") or scope_unreconciled(preflight, packet))
                or not stop_ready(payload, identity, project, independent_work=True)):
            return None
        return (
            "This existing user-approved task has remaining work or has not reconciled its "
            "full requested scope. Reconcile the bounded scope first, then continue remaining "
            "independent work in the same run, within its approved scope; a completed subset "
            "or passed route checks do not complete the full request. This reminder grants no "
            "new authority. Keep permission and safety checks. If a user decision, permission, "
            "stop, or unresolved operation prevents progress, record that blocker and end the "
            "turn honestly. Update remaining_work from observed results before finish. "
            "This automatic continuation is limited to one per turn."
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return None  # Untrusted/missing state never traps a session or supplies authority.
