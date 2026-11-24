"""Preview, before review, what the structure review will ask of the working tree.

Owner: the pre-review structure notice that gate-batch prints while the review
hook is still outstanding. Allowed imports: structure review, its command
runner and the local native probe. Forbidden: gate records, review state and any write.
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
from support.native_probe_transport import NativeProbe

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
    changed_count = len((structure.get("discovery") or {}).get("path_metadata") or {})
    failures = structure.get("failures") or []
    warnings = structure.get("warnings") or []
    if not failures and not warnings and changed_count <= DEFAULT_CHANGED_PATH_LIMIT:
        return []
    native = NativeProbe.request("--completion-probe", "structure-report", {
        "mode": "advisory", "changed_count": changed_count,
        "path_limit": DEFAULT_CHANGED_PATH_LIMIT, "item_limit": PREVIEW_ITEM_LIMIT,
        "failures": failures, "warnings": warnings,
    })
    lines = native.get("lines") if native is not None else None
    expected = (int(bool(failures)) + int(bool(warnings)) + int(changed_count > DEFAULT_CHANGED_PATH_LIMIT))
    if isinstance(lines, list) and len(lines) == expected and all(isinstance(line, str) for line in lines):
        return lines
    return _advisory_lines(changed_count, failures, warnings)


def _advisory_lines(changed_count: int, failures: list[str], warnings: list[str]) -> list[str]:
    lines: list[str] = []
    if changed_count > DEFAULT_CHANGED_PATH_LIMIT:
        lines.append(
            f"Review preview: working tree has {changed_count} changed paths "
            f"(default limit {DEFAULT_CHANGED_PATH_LIMIT}); pass --max-changed-paths {changed_count} "
            "(or narrow scope with --review-scope pathspec --review-path <owned-path>) on review."
        )
    if failures:
        lines.append(f"Review preview: structure review will fail on {_summary(failures)}; fix before review.")
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
