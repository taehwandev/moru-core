"""Preview, before review, what the structure review will ask of the working tree.

Owner: the pre-review structure notice that gate-batch prints while the review
hook is still outstanding. Allowed imports: the structure review and the command
runner it already uses. Forbidden: gate records, review state and any write.
Callers/tests: agent_hook_gate_records.gate_batch_hook,
tests/test_agent_review_structure_preview.py.

Review rejects a call that lacks --structure-review-evidence for a large changed
file, or that grows a block past the line limit, and the agent learns it only
from that rejection. Most source files here are already over the review-pressure
size, so nearly every review paid one rejected call. This runs the same check
review runs, on the same working tree, and reports it while the agent is still
assembling the review call. It never blocks and never records anything.
"""

from __future__ import annotations

from pathlib import Path

from agent_command_runtime import run_command
from agent_review_structure import (
    REVIEW_FUNCTION_LINE_LIMIT,
    REVIEW_SOURCE_FILE_LINE_LIMIT,
    structure_review,
)

PREVIEW_ITEM_LIMIT = 3
DEFAULT_CHANGED_PATH_LIMIT = 25


def structure_review_preview(project: Path) -> list[str]:
    """Lines naming what review will reject in the current working tree, or none."""

    try:
        structure = structure_review(
            project, REVIEW_SOURCE_FILE_LINE_LIMIT, REVIEW_FUNCTION_LINE_LIMIT, run_command,
        )
    except (OSError, RuntimeError, ValueError):
        return []
    lines: list[str] = []
    changed_count = len((structure.get("discovery") or {}).get("path_metadata") or {})
    if changed_count > DEFAULT_CHANGED_PATH_LIMIT:
        lines.append(
            f"Review preview: working tree has {changed_count} changed paths "
            f"(default limit {DEFAULT_CHANGED_PATH_LIMIT}); pass --max-changed-paths {changed_count} "
            "(or narrow scope with --review-scope pathspec --review-path <owned-path>) on review."
        )
    failures = structure.get("failures") or []
    if failures:
        lines.append(f"Review preview: structure review will fail on {_summary(failures)}; fix before review.")
    warnings = structure.get("warnings") or []
    if warnings:
        lines.append(
            "Review preview: review will require --structure-review-evidence because "
            f"{_summary(warnings)}. In it, state per file whether the change expands its public "
            "owner surface and why the code stays there."
        )
    return lines


def _summary(items: list[str]) -> str:
    shown = "; ".join(items[:PREVIEW_ITEM_LIMIT])
    if len(items) > PREVIEW_ITEM_LIMIT:
        shown += f"; and {len(items) - PREVIEW_ITEM_LIMIT} more"
    return shown
