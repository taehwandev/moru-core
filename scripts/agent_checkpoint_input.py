"""Normalize user checkpoint input before the strict on-disk validator.

Owner: checkpoint CLI input; allowed imports: continuation fields and packet enums;
forbidden imports: registry, ledger and provider APIs; callers/tests: checkpoint
hook and test_agent_hook_checkpoint; verification: shorthand preserves outstanding work.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from agent_continuation_fields import CHECKPOINT_RE, MAX_SHORT_TEXT, MAX_TEXT, prose
from agent_continuation_packet import VERIFICATION_KINDS


def bounded_text(value, field, limit, warnings):
    if not isinstance(value, str) or len(value) <= limit:
        return value
    failures = []
    prose(value, field, failures, limit)
    if any(item["rule"] != "prose_too_long" for item in failures):
        return value  # Keep security and malformed-input failures visible.
    warnings.append(f"Warning: truncated {field} to {limit} characters.")
    return value[:limit]


def step_name(value):
    if not value or (len(value) <= 64 and CHECKPOINT_RE.fullmatch(value)):
        return value
    errors = []
    prose(value, "last_completed", errors, len(value))
    if errors:
        raise ValueError('invalid --last-completed; example: --last-completed "tests passed"')
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")[:64] or "completed-step"


def _verification(value, index):
    # Only an explicit kind and verdict can become verification evidence.
    words = value.lower().split()
    if len(words) != 2 or words[0] not in VERIFICATION_KINDS:
        return value
    result = {"passed": "success", "pass": "success", "ok": "success", "failed": "fail"}.get(words[1], words[1])
    return {"id": f"check-{index}", "kind": words[0], "result": result,
            "evidence_sha256": None, "completed_at": None}


def _scope_path(value, project):
    if not isinstance(value, str) or ".." in value.split("/"):
        return value
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(project):
        return path.relative_to(project).as_posix()
    return value.removeprefix("./")


def normalize_work(work, project, warnings):
    for key, value in work.items():
        if key == "objective":
            work[key] = bounded_text(value, key, MAX_TEXT, warnings)
            continue
        if isinstance(value, (str, dict)) and key in {
                "decisions", "remaining_work", "verification", "changed_scope", "inspected_scope"}:
            value = work[key] = [value]
        if key == "requirements" and isinstance(value, dict):
            rows = value.get("items")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        for field in ("outcome", "owner", "gate"):
                            if field in row:
                                row[field] = bounded_text(row[field], f"{key}.{field}", MAX_TEXT, warnings)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if key == "acceptance_criteria" and isinstance(item, str) and len(item) > MAX_SHORT_TEXT:
                raise ValueError(
                    f"acceptance_criteria[{index}] has {len(item)} Unicode characters "
                    f"(maximum {MAX_SHORT_TEXT}); preserve each qualifier in bounded criteria. "
                    'Example: "All results include skipped checks".')
            if key in {"blockers", "non_goals"}:
                limit = MAX_TEXT if key == "blockers" else MAX_SHORT_TEXT
                value[index] = bounded_text(item, key, limit, warnings)
            elif key == "remaining_work" and isinstance(item, (str, dict)):
                row = {"action": item} if isinstance(item, str) else item
                row.setdefault("checkpoint", f"work-{index + 1}")
                value[index] = row
            elif key == "decisions" and isinstance(item, str):
                value[index] = {"id": f"decision-{index + 1}", "status": "accepted", "text": item}
            elif key == "verification" and isinstance(item, str):
                value[index] = _verification(item, index + 1)
            row = value[index]
            if isinstance(row, dict):
                _normalize_row(key, row, project, warnings)
    return work


def _normalize_row(key, row, project, warnings):
    field = {"remaining_work": "action", "decisions": "text", "evidence_refs": "summary"}.get(key)
    if field and field in row:
        limit = MAX_SHORT_TEXT if key == "evidence_refs" else MAX_TEXT
        row[field] = bounded_text(row[field], f"{key}.{field}", limit, warnings)
    if key in {"changed_scope", "inspected_scope"}:
        for name in ("path", "from", "to"):
            if name in row:
                row[name] = _scope_path(row[name], project)
    if key == "verification" and isinstance(row.get("completed_at"), str):
        stamp = row["completed_at"]
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?[+-](?:[01]\d|2[0-3]):[0-5]\d", stamp):
            try:
                row["completed_at"] = datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat()
            except (ValueError, OverflowError):
                pass  # The strict validator reports the field.
