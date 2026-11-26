"""Final validation, diff, and VibeGuard checks for finish-check."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import (
    atomic_write_json,
    file_hash_record,
    git_states_for_paths,
    read_json_object,
)
from agent_finish_common import add_gate_signal, parse_overall, run_command, vibeguard_command
from agent_inprocess import run_workflow_validate
from agent_vibeguard_cache import cached_vibeguard, skipped_vibeguard
from agent_workspace_policy import (
    is_non_git_workspace,
    non_git_writing_workspace_note,
    writing_diff_result,
)
from support.global_state import project_state_dir_target


REVIEW_VALIDATION_SCHEMA_VERSION = 3
REVIEW_VALIDATION_FILENAME = "review-workflow-validation.json"


def non_git_audit_note(project, rules, audit, runner):
    """Confirm the entire warning set before accepting Git-only findings outside Git."""
    overall = audit.get("overall")
    status = overall.get("status") if isinstance(overall, dict) else overall
    if status != "Needs review" or audit.get("returncode") != 0 or not is_non_git_workspace(project):
        return ""
    allowed = {("environment", "This is not a Git repository. Change tracking is limited before automatic fixes."),
               ("security", ".gitignore is missing, so local secret files may be committed.")}
    try:
        result = runner([*vibeguard_command(project, rules), "--json", "--lang", "en"], project)
        if result["returncode"] != 0:
            return ""
        report = json.loads(result["stdout"])
        summary = report["summary"]
        findings = report["findings"]
        warnings = [f for f in findings if f["severity"] != "info"]
        if (Path(report["root"]).resolve() == project.resolve() and summary["status"] == "warn"
                and summary["blocks"] == 0 and summary["warnings"] == len(warnings) and warnings
                and all(f["severity"] == "warn" and (f["category"], f["message"]) in allowed for f in warnings)):
            return "Full audit reported only Git tracking warnings in this non-Git directory."
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return ""


def run_final_checks(
    moru_root: Path,
    project: Path,
    rules: Path,
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
    read_only: bool = False,
    intrinsically_read_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    review_validation = reusable_review_workflow_validation(project, rules)
    validate = review_validation or run_workflow_validate(moru_root)
    diff_check = (
        {
            "command": ["git", "diff", "--check"],
            "cwd": str(project),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped": True,
            "review_note": non_git_writing_workspace_note(project),
        }
        if is_non_git_workspace(project)
        else (
            {
                "command": [],
                "cwd": str(project),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "skipped": True,
                "review_note": (
                    "current successful review diff check: "
                    f"{review_validation['diff_check']['review_scope']}"
                ),
            }
            if review_validation
            else (
                {
                    "command": ["git", "diff", "--check"],
                    "cwd": str(project),
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "skipped": True,
                    "review_note": (
                        "intrinsically read-only analysis; pre-existing worktree diff check skipped"
                    ),
                }
                if read_only and intrinsically_read_only
                else writing_diff_result(project, run_command(["git", "diff", "--check"], project))
            )
        )
    )
    vibeguard = (
        skipped_vibeguard(project)
        if read_only
        else cached_vibeguard(
            project=project,
            rules=rules,
            run_command=run_command,
            vibeguard_command=vibeguard_command,
            parse_overall=parse_overall,
        )
    )
    if not allow_vibeguard_review:
        allow_vibeguard_review = non_git_audit_note(project, rules, vibeguard, run_command)
        if allow_vibeguard_review:
            vibeguard["review_note"] = allow_vibeguard_review
    _record_final_check_signals(validate, diff_check, vibeguard, allow_vibeguard_review, gate_signals, failures)
    return validate, diff_check, vibeguard, vibeguard["overall"]["status"]


def _record_final_check_signals(
    validate: dict[str, Any],
    diff_check: dict[str, Any],
    vibeguard: dict[str, Any],
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
) -> None:
    if validate["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "workflow validate", "failed", "non-zero exit")
        failures.append("workflow validate failed")
    elif validate.get("reused"):
        add_gate_signal(gate_signals, "SUCCESS", "workflow validate", "reused", "current review result")
    else:
        add_gate_signal(gate_signals, "SUCCESS", "workflow validate", "executed", "exit 0")
    if diff_check["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "diff check", "failed", "non-zero exit")
        failures.append("git diff --check failed")
    elif diff_check.get("skipped") or diff_check.get("git_returncode"):
        add_gate_signal(gate_signals, "SUCCESS", "diff check", "review accepted", diff_check["review_note"])
    else:
        add_gate_signal(gate_signals, "SUCCESS", "diff check", "executed", "exit 0")
    _record_vibeguard_signal(vibeguard, allow_vibeguard_review, gate_signals, failures)


def _record_vibeguard_signal(
    vibeguard: dict[str, Any],
    allow_vibeguard_review: str | None,
    gate_signals: list[dict[str, str]],
    failures: list[str],
) -> None:
    overall = vibeguard["overall"]["status"]
    if vibeguard.get("skipped"):
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "skipped", overall)
    elif vibeguard["returncode"] != 0:
        add_gate_signal(gate_signals, "FAIL", "VibeGuard", "failed", "non-zero exit")
        failures.append("final VibeGuard audit failed")
    elif overall != "Ready" and not allow_vibeguard_review:
        add_gate_signal(gate_signals, "FAIL", "VibeGuard", "blocked", overall)
        failures.append(
            "final VibeGuard is not Ready; report the state and pass "
            "--allow-vibeguard-review with a reason if the review is acceptable"
        )
    elif overall != "Ready":
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "review accepted", allow_vibeguard_review or overall)
    else:
        add_gate_signal(gate_signals, "SUCCESS", "VibeGuard", "executed", overall)


def record_successful_review_workflow_validation(
    project: Path,
    rules: Path,
    evidence_path: Path,
    validate: dict[str, Any],
    diff_check: dict[str, Any],
    review_scope: str,
    *,
    review_paths: Sequence[str] | None = None,
) -> tuple[dict[str, str], dict[str, str]] | None:
    """Persist successful review checks with their exact source snapshot.

    Returns the project and rules states it captured, so the attestation written
    right after can revalidate them instead of fingerprinting both trees again.
    """

    if (
        validate.get("returncode") != 0
        or diff_check.get("returncode") != 0
        or not review_scope.strip()
        or not evidence_path.is_file()
    ):
        return None
    scoped_paths = (
        [item for item in (str(p).strip() for p in review_paths) if item]
        if review_paths and review_scope.strip().startswith("pathspec:")
        else []
    )
    try:
        project_git, rules_git = (
            git_states_for_paths(project, rules, project_paths=scoped_paths)
            if scoped_paths
            else git_states_for_paths(project, rules)
        )
        evidence_relative = evidence_path.resolve().relative_to(
            project_state_dir_target(project.resolve()).resolve()
        )
        evidence = {
            "path": evidence_relative.as_posix(),
            "sha256": file_hash_record(evidence_path)["sha256"],
        }
    except (OSError, RuntimeError, ValueError):
        return None
    diff_record: dict[str, Any] = {
        "returncode": 0,
        "review_scope": review_scope.strip(),
    }
    if scoped_paths:
        diff_record["review_paths"] = scoped_paths
    try:
        atomic_write_json(
            review_validation_path(project),
            {
                "schema_version": REVIEW_VALIDATION_SCHEMA_VERSION,
                "preflight_evidence": evidence,
                "project_git": project_git,
                "rules_git": rules_git,
                "workflow_validate": {"returncode": 0},
                "diff_check": diff_record,
            },
        )
    except OSError:
        # This project-level record only caches workflow validation for finish.
        # The run-bound review attestation remains the authoritative evidence,
        # so a sandbox that permits the run directory but not the shared .moru
        # root must not turn a successful review into a structural failure.
        pass
    return project_git, rules_git


def reusable_review_workflow_validation(project: Path, rules: Path) -> dict[str, Any] | None:
    """Return the review result only while its project/rules state is current."""

    record = read_json_object(review_validation_path(project))
    if not _valid_review_validation_record(record):
        return None
    state_dir = project_state_dir_target(project.resolve())
    evidence_path = (state_dir / record["preflight_evidence"]["path"]).resolve()
    scoped_paths = record["diff_check"].get("review_paths")
    try:
        evidence_path.relative_to(state_dir.resolve())
        current_evidence = {
            "path": record["preflight_evidence"]["path"],
            "sha256": file_hash_record(evidence_path)["sha256"],
        }
        if not evidence_path.is_file() or current_evidence != record["preflight_evidence"]:
            return None
        project_git, rules_git = (
            git_states_for_paths(
                project,
                rules,
                project_record=record["project_git"],
                rules_record=record["rules_git"],
                project_paths=scoped_paths,
            )
            if scoped_paths
            else git_states_for_paths(
                project,
                rules,
                project_record=record["project_git"],
                rules_record=record["rules_git"],
            )
        )
    except (OSError, RuntimeError, ValueError):
        return None
    if project_git != record["project_git"] or rules_git != record["rules_git"]:
        return None
    return {
        "command": [],
        "cwd": str(rules),
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "reused": True,
        "source": "review",
        "diff_check": record["diff_check"],
    }


def review_validation_path(project: Path) -> Path:
    return project_state_dir_target(project.resolve()) / REVIEW_VALIDATION_FILENAME


def _valid_review_validation_record(record: dict[str, Any]) -> bool:
    if set(record) != {
        "schema_version",
        "preflight_evidence",
        "project_git",
        "rules_git",
        "workflow_validate",
        "diff_check",
    }:
        return False
    if record.get("schema_version") != REVIEW_VALIDATION_SCHEMA_VERSION:
        return False
    if not isinstance(record.get("preflight_evidence"), dict):
        return False
    if set(record["preflight_evidence"]) != {"path", "sha256"}:
        return False
    if not isinstance(record["preflight_evidence"].get("path"), str):
        return False
    if not isinstance(record["preflight_evidence"].get("sha256"), str):
        return False
    for key in ("project_git", "rules_git"):
        value = record.get(key)
        if not isinstance(value, dict) or set(value) != {
            "head",
            "worktree_fingerprint",
            "worktree_signature",
        }:
            return False
    if record.get("workflow_validate") != {"returncode": 0}:
        return False
    diff_check = record.get("diff_check")
    if not isinstance(diff_check, dict):
        return False
    allowed_keys = {"returncode", "review_scope"}
    if not allowed_keys.issubset(diff_check) or not set(diff_check).issubset(allowed_keys | {"review_paths"}):
        return False
    if diff_check.get("returncode") != 0:
        return False
    if not isinstance(diff_check.get("review_scope"), str) or not diff_check["review_scope"].strip():
        return False
    if "review_paths" in diff_check:
        review_paths = diff_check["review_paths"]
        if (
            not isinstance(review_paths, list)
            or not review_paths
            or not all(isinstance(item, str) and bool(item.strip()) for item in review_paths)
        ):
            return False
    return True
