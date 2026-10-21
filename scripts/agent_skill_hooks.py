"""Closeout adapters for retrospective skill-document maintenance."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_hook_gate_records import preflight_evidence_path
from agent_hook_runtime import finish_with_result
from agent_skill_feedback import (
    record_skill_curation,
    record_skill_draft,
    record_skill_feedback,
    record_skill_maintenance,
    record_skill_review,
)
from agent_skill_state import CURRENT_TASK_REVIEW_THRESHOLD


def skill_feedback_hook(args: Any) -> int:
    proposal, unreadable = _draft_proposal_with_status(args)
    if unreadable:
        return finish_with_result(
            "skill-feedback",
            False,
            ["skill feedback failed: draft proposal file cannot be read"],
            args.output,
            {"skill_feedback": {"created": False, "reason": "unreadable_proposal_file"}},
            0,
            invocation_error=True,
        )
    extra = (
        {
            "proposal": proposal,
            "change_type": str(getattr(args, "change_type", "") or ""),
            "promotion_target": str(getattr(args, "promotion_target", "") or ""),
        }
        if proposal.strip()
        else {}
    )
    feedback, details = record_skill_feedback(
        project=args.project,
        rules=getattr(args, "rules", Path(__file__).resolve().parents[1]),
        evidence_path=preflight_evidence_path(args),
        outcome=args.skill_feedback_outcome,
        skill_id=args.skill_id,
        signal=args.feedback_signal,
        gap_type=str(getattr(args, "feedback_gap", "") or ""),
        **extra,
    )
    stage_ok = not extra or not (feedback.get("created") or feedback.get("idempotent")) or bool(
        (feedback.get("review") or {}).get("updated")
    )
    success = feedback.get("reason") != "retrospective_gate_required" and stage_ok
    return finish_with_result(
        "skill-feedback",
        success,
        details,
        args.output,
        {"skill_feedback": feedback},
        0,
        invocation_error=not success,
    )


def skill_draft_hook(args: Any) -> int:
    draft, details = record_skill_draft(
        project=args.project,
        rules=getattr(args, "rules", Path(__file__).resolve().parents[1]),
        evidence_path=preflight_evidence_path(args),
        skill_id=args.skill_id,
        signal=args.feedback_signal,
        proposal=_draft_proposal(args),
    )
    return finish_with_result(
        "skill-draft", True, details, args.output, {"skill_draft": draft}, 0
    )


def _draft_proposal(args: Any) -> str:
    return _draft_proposal_with_status(args)[0]


def _draft_proposal_with_status(args: Any) -> tuple[str, bool]:
    """Prefer a file so a bounded rationale never depends on shell quoting."""

    source = getattr(args, "draft_proposal_file", "")
    if source:
        try:
            return Path(source).read_text(encoding="utf-8"), False
        except OSError:
            return "", True
    return str(getattr(args, "draft_proposal", "") or ""), False


def skill_review_hook(args: Any) -> int:
    review, details = record_skill_review(
        project=args.project,
        rules=getattr(args, "rules", Path(__file__).resolve().parents[1]),
        candidate_id=args.feedback_candidate_id,
        decision=args.skill_review_outcome,
        gap_type=args.feedback_gap,
        change_type=args.change_type,
        promotion_target=args.promotion_target,
    )
    return finish_with_result(
        "skill-review", True, details, args.output, {"skill_review": review}, 0
    )


def skill_curate_hook(args: Any) -> int:
    curation, details = record_skill_curation(
        min_occurrences=CURRENT_TASK_REVIEW_THRESHOLD
    )
    return finish_with_result(
        "skill-curate", True, details, args.output, {"skill_curation": curation}, 0
    )


def skill_maintenance_hook(args: Any) -> int:
    maintenance, details = record_skill_maintenance(
        project=args.project,
        rules=args.rules,
        candidate_id=args.feedback_candidate_id,
        outcome=args.skill_maintenance_outcome,
        verification_kind=args.verification_kind,
        target=args.maintenance_target,
        test_selector=args.maintenance_test_selector,
        evidence_path=preflight_evidence_path(args),
    )
    success = bool(maintenance.get("updated"))
    verification = maintenance.get("verification") or {}
    if verification:
        details.append(
            f"verification: {verification['kind']} exited {verification['returncode']}"
        )
        for stream in ("stdout", "stderr"):
            if verification.get(stream):
                details.append(f"verification {stream}: {verification[stream]}")
    return finish_with_result(
        "skill-maintenance", success, details, args.output,
        {"skill_maintenance": maintenance}, 0, pending_closeout=not success,
    )
