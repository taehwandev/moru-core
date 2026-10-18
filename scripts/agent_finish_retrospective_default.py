"""Derive a default `retrospective check` at finish when the agent recorded none.

Owner: the finish-time default for the retrospective gate. Allowed imports: gate
evidence, route state and the skill catalog. Forbidden: Git, provider calls and
any other gate. Callers/tests: agent-hook finish,
tests/test_agent_finish_retrospective_default.py.

Most closeouts recorded the same answer -- no reusable gap, nothing to observe --
in a gate-batch call of their own, and 69% of 140 sampled entries named skills
the run had not loaded to get there. Finish now records that answer itself, as
it already does for commit readiness, and says it was derived. An agent that
found a gap still records `reusable_gap` before finish, and that record wins.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_gate_evidence import (
    GateEvidenceAccessError,
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
)
from agent_route_state import required_docs_for_route
from agent_skill_catalog import skill_ids_from_doc_paths

RETROSPECTIVE_GATE = "retrospective check"
# Every route's retrospective is governed by this skill, so it is always loaded.
ALWAYS_LOADED_SKILL = "retrospective_learning"


def retrospective_left_to_finish(evidence: dict, diagnostics: dict) -> bool:
    """True only when the ledger holds no retrospective record of any status.

    A failed, malformed or incomplete agent record stays authoritative: finish
    reports it instead of replacing it with the default.
    """

    return RETROSPECTIVE_GATE not in evidence and not any(
        RETROSPECTIVE_GATE in (diagnostics.get(key) or {})
        for key in ("failed_gates", "invalid_statuses", "missing_fields")
    )


def derive_retrospective_default(evidence_path: Path) -> str:
    """Record the default retrospective when the route needs one and none exists."""

    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        route = preflight.get("route") or {}
        if RETROSPECTIVE_GATE not in (route.get("gates") or []):
            return ""
        evidence, diagnostics = merge_gate_evidence_from_ledger(route=route, evidence_path=evidence_path)
        if not retrospective_left_to_finish(evidence, diagnostics):
            return ""
        loaded = sorted(skill_ids_from_doc_paths(required_docs_for_route(route) or []))
        skills = ", ".join(loaded or [ALWAYS_LOADED_SKILL])
        record_gate_evidence(
            evidence_path=evidence_path,
            preflight=preflight,
            gate=RETROSPECTIVE_GATE,
            evidence=(
                f"skills checked: {skills}; outcome: no_reusable_gap; observation: not_needed; "
                "derived at finish because the agent recorded no retrospective"
            ),
            fields={
                "skills_checked": skills,
                "outcome": "no_reusable_gap",
                "observation": "not_needed",
            },
            source="finish",
        )
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, GateEvidenceAccessError):
        return ""
    return "retrospective check: derived at finish (no reusable gap recorded by the agent)"
