"""Completion checks for explicitly recorded work, independent of route gates.

Owner: bound semantic work checkpoint; allowed imports: existing local state readers.
Forbidden: prompt parsing, execution, provider calls and inferred authorization.
Callers/tests: finish check, Stop continuation; test_agent_work_completion.
Verification: a passed subset cannot close recorded outstanding delivery work.
"""

from __future__ import annotations

from pathlib import Path

from agent_continuation_checkpoint import binding_record
from agent_continuation_store import continuation_path, read_continuation_packet
from agent_execution_capsule_state import read_json_object
from workflow_effect_policy import route_minimum_effect


def bound_work_packet(project: Path, evidence: Path) -> dict | None:
    """Read a valid packet for these exact admitted inputs, never older work."""
    preflight = read_json_object(evidence)
    if Path(str(preflight.get("project") or "")).resolve() != project.resolve():
        return None
    version = (preflight.get("route") or {}).get("lifecycle_version")
    if type(version) is not int or version != 2:
        return None
    result = read_continuation_packet(project, continuation_path(project, evidence.parent.name))
    packet = result.get("packet") or {}
    if (result.get("status") != "ok" or packet.get("run_id") != evidence.parent.name
            or packet.get("binding") != binding_record(evidence, preflight)):
        return None
    return packet


def work_completion_failures(project: Path, evidence: Path) -> list[str]:
    """A finish receipt must not erase declared unfinished work or blockers."""
    preflight = read_json_object(evidence)
    route = preflight.get("route") or {}
    version = route.get("lifecycle_version")
    if type(version) is not int or version != 2 or route_minimum_effect(route.get("command", "")) == "read":
        return []
    path = continuation_path(project, evidence.parent.name)
    if not path.exists() and not path.is_symlink():
        return []  # Older/worker runs need not carry a semantic checkpoint.
    try:
        packet = bound_work_packet(project, evidence)
    except (OSError, ValueError, RuntimeError):
        packet = None
    if packet is None:
        return ["work completion checkpoint is unreadable or stale; reconcile it before finish"]
    work = packet.get("work") or {}
    failures = []
    if scope_unreconciled(preflight, packet):
        failures.append("requested scope has not been reconciled; record its bounded objective, acceptance and remaining outcomes before finish")
    if work.get("remaining_work"):
        failures.append("requested work remains unfinished; complete or explicitly resolve every declared outcome before finish")
    if work.get("blockers") or packet.get("phase") == "blocked":
        failures.append("requested work has unresolved blockers; report partial progress without a completion receipt")
    if packet.get("phase") == "reconcile_required" or (packet.get("checkpoint") or {}).get("mutation_pending"):
        failures.append("requested work has an unresolved operation; reconcile its actual outcome before finish")
    return failures


def scope_unreconciled(preflight: dict, packet: dict) -> bool:
    """Recognize the runtime's own placeholder, never classify user language."""
    route = preflight.get("route") or {}
    if route.get("command") == "small-change":
        return False
    envelope = (route.get("request_classification") or {}).get("intent_envelope") or {}
    if not envelope.get("schema_valid") or not envelope.get("envelope_present") or envelope.get("failures"):
        return False  # Historical/unadmitted records retain their existing contract.
    work = packet.get("work") or {}
    return (not work.get("acceptance_criteria")
            and work.get("objective") in (None, "", f"{route.get('command')} workflow"))
