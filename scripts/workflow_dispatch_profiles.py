"""Resolve runtime-neutral task stages into Codex worker profiles."""

from __future__ import annotations

from typing import Mapping

from workflow_request import CODEX_MODEL_BY_TIER, requires_code_authoring


WORK_KINDS = (
    "auto",
    "prd_design",
    "research",
    "analysis",
    "implementation",
    "complex_implementation",
    "repetitive",
    "final_review",
)

ORCHESTRATOR_PROFILE = {
    "role": "orchestrator",
    "model_tier": "frontier",
    "codex_model": CODEX_MODEL_BY_TIER["frontier"],
    "reasoning_effort": "medium",
}

WORK_PROFILES = {
    "prd_design": {"model_tier": "frontier", "reasoning_effort": "high"},
    "research": {"model_tier": "balanced", "reasoning_effort": "low"},
    "analysis": {"model_tier": "balanced", "reasoning_effort": "medium"},
    "implementation": {"model_tier": "balanced", "reasoning_effort": "medium"},
    "complex_implementation": {"model_tier": "frontier", "reasoning_effort": "high"},
    "repetitive": {"model_tier": "fast", "reasoning_effort": "low"},
    "final_review": {"model_tier": "frontier", "reasoning_effort": "xhigh"},
}

AUTO_WORK_KINDS = {
    "analysis": "analysis",
    "prd": "prd_design",
    "spec": "prd_design",
    "plan": "research",
    "planning": "research",
    "task": "analysis",
    "review": "final_review",
    "docs-review": "final_review",
}

IMPLEMENTATION_COMMANDS = {
    "build",
    "bugfix",
    "code-simplify",
    "docs",
    "editorial",
    "feature",
    "refactor",
    "workflow-setup",
    "writing",
}

NON_AUTHORING_REPETITIVE_COMMANDS = {"test"}


def select_work_kind(
    command: str,
    classification: Mapping[str, object],
    requested_kind: str,
    complexity_evidence: str = "",
) -> tuple[str, str]:
    if requested_kind != "auto":
        if requested_kind == "complex_implementation":
            effort = str(classification["effort"])
            if effort not in {"deep", "specialist"} and not complexity_evidence.strip():
                raise ValueError(
                    "Complex implementation requires deep/specialist classification or "
                    "--complexity-evidence from local inspection."
                )
            reason = complexity_evidence.strip() or f"{effort} effort is explicit complexity evidence"
            return requested_kind, f"complex implementation evidence: {reason}"
        if requested_kind == "repetitive":
            if _requires_code_authoring(command, classification):
                raise ValueError("Luna cannot write or modify code; select the Terra implementation profile instead.")
            if command not in NON_AUTHORING_REPETITIVE_COMMANDS:
                raise ValueError("Luna is limited to read-only non-authoring repetitive work.")
        return requested_kind, f"explicit work kind `{requested_kind}`"

    auto_work_kind = AUTO_WORK_KINDS.get(command)
    if auto_work_kind:
        return auto_work_kind, f"route `{command}` selects `{auto_work_kind}`"

    effort = str(classification["effort"])
    if command == "test" and effort == "quick" and not _requires_code_authoring(command, classification):
        return "repetitive", "quick non-authoring test route selects the read-only Luna profile"
    if command in IMPLEMENTATION_COMMANDS and effort in {"deep", "specialist"}:
        return "complex_implementation", f"{effort} effort is explicit complexity evidence"
    return "implementation", "normal implementation defaults to Terra medium"


def _requires_code_authoring(command: str, classification: Mapping[str, object]) -> bool:
    if command in IMPLEMENTATION_COMMANDS:
        return True
    return requires_code_authoring(str(classification.get("request") or ""))


def profile_for_work_kind(work_kind: str) -> dict[str, str]:
    try:
        profile = WORK_PROFILES[work_kind]
    except KeyError as error:
        raise ValueError(f"Unsupported work kind `{work_kind}`") from error
    model_tier = profile["model_tier"]
    return {
        "work_kind": work_kind,
        "model_tier": model_tier,
        "codex_model": CODEX_MODEL_BY_TIER[model_tier],
        "reasoning_effort": profile["reasoning_effort"],
    }
