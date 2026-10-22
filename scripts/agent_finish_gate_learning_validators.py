"""Finish evidence validation for lightweight retrospective learning."""

from __future__ import annotations

import re
from pathlib import Path

from agent_skill_catalog import NO_SKILL_IDS, normalize_skill_id, parse_skill_ids


RETROSPECTIVE_OUTCOMES = {
    "no_reusable_gap",
    "reusable_gap",
    "no_skill_used",
}
RETROSPECTIVE_OBSERVATION_STATES = {
    "not_needed",
    "recorded",
}
# Every one of the 27 routes requires the `retrospective check` gate, and this
# is the skill that governs how to record it, so every run that reaches finish
# has used it whether or not its route listed the document. Leaving it out
# refused the one retrospective most likely to be true: the one about
# retrospectives.
ALWAYS_LOADED_SKILL_IDS = frozenset({"retrospective_learning"})
CAUSAL_RETROSPECTIVE_CONTRACT = "causal_v1"
CAUSAL_RETROSPECTIVE_FIELDS = ("alignment_evidence", "causal_assessment", "learning_decision")
EFFICIENCY_ASSESSMENTS = ("no_waste", "unmeasured", "improvement_needed")
MEMORY_DECISION_FIELDS = ("memory_decision", "memory_reason", "memory_record")


def validate_retrospective_check(
    evidence: str,
    *,
    allowed_skill_ids: set[str] | None = None,
    loaded_skill_ids: set[str] | None = None,
    contract: str = "legacy",
    memory_contract: str = "legacy",
    project: Path | None = None,
    scope: str = "all",
) -> list[str]:
    """Require an explicit skill check and same-closeout gap resolution."""

    text = evidence.strip()
    if not text:
        return ["retrospective check evidence is required"]

    skills_checked = _field(text, "skills checked")
    outcome = _field(text, "outcome").lower()
    observation = _field(text, "observation").lower()
    missing = [
        label
        for label, value in (
            ("skills checked", skills_checked),
            ("outcome", outcome),
            ("observation", observation),
        )
        if not value
    ]
    if missing:
        return [
            "retrospective check evidence must state " + ", ".join(missing)
        ]

    failures: list[str] = []
    if outcome not in RETROSPECTIVE_OUTCOMES:
        failures.append(
            "retrospective check outcome must be no_reusable_gap, "
            "reusable_gap, or no_skill_used"
        )
    if observation not in RETROSPECTIVE_OBSERVATION_STATES:
        failures.append(
            "retrospective check observation must be not_needed or recorded"
        )
    if failures:
        return failures

    if outcome == "reusable_gap" and observation != "recorded":
        failures.append(
            "retrospective check with reusable_gap must record one skill observation "
            "before same-closeout maintenance"
        )
    if outcome in {"no_reusable_gap", "no_skill_used"} and observation != "not_needed":
        failures.append(
            f"retrospective check with {outcome} must use observation: not_needed"
        )
    normalized_skills = parse_skill_ids(skills_checked)
    if outcome == "no_skill_used" and skills_checked.lower() not in NO_SKILL_IDS:
        failures.append(
            "retrospective check with no_skill_used must set skills checked to none"
        )
    if outcome != "no_skill_used" and skills_checked.lower() in NO_SKILL_IDS:
        failures.append(
            "retrospective check must name the skill or skills evaluated"
        )
    if outcome != "no_skill_used":
        raw_skills = [item.strip() for item in skills_checked.split(",") if item.strip()]
        if not raw_skills or len(normalized_skills) != len(raw_skills) or any(
            not skill for skill in normalized_skills
        ):
            failures.append(
                "retrospective check skills checked must contain canonical skill slugs"
            )
        else:
            # Only ask which skills this run loaded once the names parse. A
            # list that is not yet canonical slugs has one mistake to fix, and
            # answering it with two failures sends the reader after the wrong
            # one first.
            if allowed_skill_ids is not None:
                unknown = [
                    raw
                    for raw, normalized in zip(raw_skills, normalized_skills)
                    if normalize_skill_id(normalized) not in allowed_skill_ids
                ]
                if unknown:
                    failures.append(
                        "retrospective check named unknown canonical skills: "
                        + ", ".join(unknown)
                    )
            failures.extend(
                _unloaded_skill_failures(normalized_skills, loaded_skill_ids)
            )
    failures.extend(_causal_assessment_failures(text, contract, outcome))
    failures.extend(_efficiency_failures(text, outcome))
    failures.extend(validate_project_memory_decision(text, memory_contract, project, scope))
    return failures


_BARE_DISMISSAL_RE = re.compile(
    r"^(?:"
    r"none|n/?a|not[_\s]+(?:needed|applicable|required)|"
    r"no[_\s]+(?:change|changes|update|updates|action|edit|edits|modification|modifications)"
    r"(?:[_\s]+(?:is|are))?(?:[_\s]+(?:needed|required|necessary|warranted))?|"
    r"no-?op|nothing|skip(?:ped)?"
    r")$",
    re.IGNORECASE,
)
_NO_CHANGE_PREFIX_RE = re.compile(
    r"^no\s+(?:additional\s+|further\s+)?(?:canonical\s+)?"
    r"(?:skill(?:-doc|\s+doc|\s+file)?|rule|guidance|doc|documentation|script\.md|skill\.md)"
    r"(?:\s+or\s+(?:skill|rule|guidance|doc|documentation))?\s+"
    r"(?:change|changes|update|updates|edit|edits|modification|modifications|action)"
    r"\b",
    re.IGNORECASE,
)
_GROUNDING_MARKER_RE = re.compile(
    r"(?:"
    r"\b(?:keep|keeps|kept|retain|retains|retained|preserve|preserves|preserved|because|since)\b|"
    r"\balready\s+(?:cover|covers|covered|enforce|enforces|enforced|block|blocks|blocked|"
    r"validate|validates|validated|handle|handles|handled|check|checks|checked)\b|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|"
    r"\b[a-z0-9]+_[a-z0-9_]+\b|"
    r"\b(?:SKILL|AGENTS|README)\.md\b|"
    r"\b(?:AC|T|PR|ISSUE)[-_]?\d+\b"
    r")",
    re.IGNORECASE,
)
_KNOWN_FIELD_LABELS = (
    "skills checked",
    "outcome",
    "observation",
    "alignment evidence",
    "causal assessment",
    "learning decision",
    *(name.replace("_", " ") for name in MEMORY_DECISION_FIELDS),
    "efficiency evidence",
    "efficiency cause",
    "efficiency reduction",
    "efficiency verification",
    "efficiency",
)


def _is_ungrounded_learning_decision(decision: str) -> bool:
    cleaned = decision.strip().strip("\"'`-.;: ")
    if not cleaned:
        return True
    if _BARE_DISMISSAL_RE.fullmatch(cleaned):
        return True
    if _NO_CHANGE_PREFIX_RE.search(cleaned):
        remainder = _NO_CHANGE_PREFIX_RE.sub("", cleaned, count=1)
        if not _GROUNDING_MARKER_RE.search(remainder):
            return True
    return False


def validate_project_memory_decision(text: str, contract: str, project: Path | None, scope: str) -> list[str]:
    """Read back a durable lesson; a promise to capture is not completion.

    This is read-only and proves persistence, not the truth of the lesson or
    the agent's reason for withholding capture. Historical manifests stay frozen.
    """
    if contract == "legacy":
        return []
    if contract != "decision_v1":
        return [f"unsupported project memory contract: {contract!r}"]
    decision, reason, reference = (_field(text, name.replace("_", " ")) for name in MEMORY_DECISION_FIELDS)
    if decision not in {"stored", "not_needed"} or not reason:
        return ["retrospective memory decision requires memory_decision (stored|not_needed) and memory_reason"]
    if decision == "not_needed":
        return ["memory_record must be absent for not_needed"] if reference else []
    if project is None or not re.fullmatch(r"[0-9a-f]{16}:[0-9a-f]{64}", reference):
        return ["stored memory decision requires this project's memory_record as <id>:<digest>"]

    from agent_project_memory import _recall, _source_status, recall_lines, scan_records

    try:
        records, _ = scan_records(project)
        record_id, digest = reference.split(":")
        record = next((item for item in _recall(project, scope, records=records)
                       if item["id"] == record_id and item["digest"] == digest), None)
        if record is None:
            return ["memory_record is missing, changed, expired, retired, replaced or outside this route's scope"]
        if _source_status(project, record).get("warning"):
            return ["memory_record source evidence changed or is unavailable; verify and replace it before closeout"]
        single = [item for item in records if item["id"] in {record_id, record.get("replaces")}]
        if not recall_lines(project, scope, records=single):
            return ["memory_record cannot fit the existing recall budget; shorten or replace it before closeout"]
    except (OSError, ValueError):
        return ["memory_record could not be verified in this project's store"]
    return []


def _causal_assessment_failures(text: str, contract: str, outcome: str = "") -> list[str]:
    """Check presence and grounded learning_decision without keyword-reclassifying causal_assessment."""

    if contract not in ("legacy", CAUSAL_RETROSPECTIVE_CONTRACT):
        return [f"unsupported retrospective contract: {contract!r}"]
    labels = tuple(name.replace("_", " ") for name in CAUSAL_RETROSPECTIVE_FIELDS)
    if contract == "legacy" and not any(_field(text, label) for label in labels):
        return []  # Historical runs retain their original evidence contract.
    missing = [label for label in labels if not _field(text, label)]
    if missing:
        return ["retrospective causal assessment requires " + ", ".join(missing)]
    if contract != CAUSAL_RETROSPECTIVE_CONTRACT:
        return []
    decision = _full_field(text, "learning decision")
    if _is_ungrounded_learning_decision(decision):
        if outcome == "reusable_gap":
            return [
                "retrospective learning decision for reusable_gap must name the repair artifact "
                "and verification check, not a no-change dismissal"
            ]
        return [
            "retrospective learning decision must name the specific existing check, rule, or owner "
            "kept (e.g. 'Keep existing <check/rule>; ...') or use reusable_gap with a skill update, "
            "not an ungrounded 'No skill change needed' dismissal"
        ]
    return []


def _efficiency_failures(text: str, outcome: str) -> list[str]:
    """Validate opt-in causal assessment without invalidating historical ledgers."""

    assessment = _field(text, "efficiency")
    labels = ("efficiency evidence", "efficiency cause", "efficiency reduction", "efficiency verification")
    if not assessment and not any(_field(text, label) for label in labels):
        return []
    if assessment not in EFFICIENCY_ASSESSMENTS:
        return ["retrospective efficiency must be no_waste, unmeasured, or improvement_needed"]
    required = labels if assessment == "improvement_needed" else labels[:1]
    missing = [label for label in required if not _field(text, label)]
    failures = ["retrospective efficiency requires " + ", ".join(missing)] if missing else []
    if assessment == "improvement_needed" and outcome != "reusable_gap":
        failures.append("retrospective efficiency improvement_needed requires reusable_gap and same-closeout maintenance")
    return failures


def _unloaded_skill_failures(
    normalized_skills: list[str],
    loaded_skill_ids: set[str] | None,
) -> list[str]:
    """Require one named skill to be one this run actually loaded.

    The retrospective documents say the named skill must be one the agent
    "actually loaded and applied" in six places, and nothing enforced it: the
    only skill check proved the slug was *a* known bundle, which every bundle
    in the repository satisfies. A run could therefore close `no_reusable_gap`
    against skills it never opened, and across 140 recorded gate entries 69%
    took exactly that path.

    One overlap is the bar, not all of them. An agent may legitimately consult
    a skill the route did not require, and rejecting the extra names would
    punish the more thorough retrospective. What cannot stand is a list with no
    connection at all to what this run read.
    """

    if not loaded_skill_ids or not normalized_skills:
        # A route with no resolvable skill bundle gives nothing to check
        # against. Refusing here would block every such run on the strength of
        # missing evidence rather than wrong evidence.
        return []
    loaded = set(loaded_skill_ids) | ALWAYS_LOADED_SKILL_IDS
    if any(skill in loaded for skill in normalized_skills):
        return []
    return [
        "retrospective check must name at least one skill this run actually "
        "loaded; this run loaded " + ", ".join(sorted(loaded))
    ]


def _field(evidence: str, label: str) -> str:
    match = re.search(
        rf"(?:^|[;\n])\s*{re.escape(label)}\s*[:=]\s*([^;\n]+)",
        evidence,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _full_field(evidence: str, label: str) -> str:
    """Extract a field value preserving internal semicolons up to the next field label or newline."""
    other_labels = "|".join(re.escape(item) for item in _KNOWN_FIELD_LABELS if item != label.lower())
    pattern = rf"(?:^|[;\n])\s*{re.escape(label)}\s*[:=]\s*(.+?)(?=(?:;\s*(?:{other_labels})\s*[:=])|\n|$)"
    match = re.search(pattern, evidence, flags=re.IGNORECASE)
    return match.group(1).strip() if match else _field(evidence, label)
