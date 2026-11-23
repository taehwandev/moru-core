"""Fail-closed validation for provider-neutral execution capsules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_execution_capsule_bindings import (
    file_binding_failures,
    gate_ledger_failures,
    git_binding_failures,
    preflight_identity_failures,
)
from agent_execution_capsule_state import (
    PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
    REUSE_POLICY,
    SCHEMA_VERSION,
    git_states_for_paths,
    is_sha256,
    native_capsule_probe,
)
from agent_execution_capsule_docs import required_doc_failures
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_route_state import request_fingerprint, route_fingerprint
from agent_worktree_fingerprint import WorktreeFingerprintLimitExceeded


_TOP_LEVEL_FIELDS = {
    "schema_version", "created_at", "phase", "route_fingerprint", "request_fingerprint",
    "preflight_evidence", "required_docs",
    "project_git", "rules_git", "gate_ledger", "reuse_policy",
}
_FILE_HASH_FIELDS = {"filename", "sha256"}
_GIT_FIELDS = {"head", "worktree_fingerprint", "worktree_signature"}
_DOC_FIELDS = {"path", "size_bytes", "sha256"}


def validate_execution_capsule(
    capsule: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    route: dict[str, Any],
) -> list[str]:
    shape_failures = _shape_failures(capsule)
    if shape_failures:
        return shape_failures
    failures: list[str] = []
    if capsule["phase"] != "ready":
        failures.append("execution capsule phase is not ready")
    if capsule["route_fingerprint"] != route_fingerprint(route):
        failures.append("execution capsule route fingerprint does not match")
    if capsule["request_fingerprint"] != request_fingerprint(_request_intake(evidence_path)):
        failures.append("execution capsule request fingerprint does not match")
    failures.extend(
        file_binding_failures(
            capsule["preflight_evidence"], evidence_path, "preflight evidence"
        )
    )
    failures.extend(preflight_identity_failures(evidence_path, project, rules))

    if capsule["phase"] == "ready":
        failures.extend(required_doc_failures(capsule["required_docs"], rules, route))

    try:
        project_git, rules_git = git_states_for_paths(
            project,
            rules,
            project_record=capsule["project_git"],
            rules_record=capsule["rules_git"],
        )
    except WorktreeFingerprintLimitExceeded:
        failures.append("execution capsule worktree exceeds bounded fingerprint limits")
    except (OSError, RuntimeError):
        failures.append("execution capsule project/rules git state is unavailable")
    else:
        failures.extend(
            git_binding_failures(
                capsule["project_git"], project, "project", current=project_git
            )
        )
        failures.extend(
            git_binding_failures(
                capsule["rules_git"], rules, "rules", current=rules_git
            )
        )
    ledger_path = gate_evidence_path_for_preflight(evidence_path)
    if capsule.get("gate_ledger") is not None:
        failures.extend(
            file_binding_failures(
                capsule["gate_ledger"],
                ledger_path,
                "gate ledger",
            )
        )
    elif capsule["phase"] == "ready":
        failures.append("execution capsule ready phase requires gate ledger evidence")
    failures.extend(gate_ledger_failures(ledger_path, evidence_path, route))
    return list(dict.fromkeys(failures))


def validate_source_docs_binding(
    capsule: dict[str, Any],
    project: Path,
    rules: Path,
    evidence_path: Path,
    route: dict[str, Any],
    documented_updates: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Validate the pre-edit document snapshot without requiring a clean tree.

    Finish runs after implementation, so full capsule reuse validation would
    correctly reject the changed worktree.  The source-docs gate instead needs
    the stable subset: the same preflight, route, project/rules identities, and
    hashes of the documents the route required before work began. An exact
    required-doc path may differ only when the final structured documentation
    gate explicitly declares it as an updated artifact.
    """

    project = project.resolve()
    rules = rules.resolve()
    evidence_path = evidence_path.resolve()
    shape_failures = _shape_failures(capsule)
    if shape_failures:
        return shape_failures
    failures: list[str] = []
    if capsule["phase"] != "ready":
        failures.append("execution capsule phase is not ready for source docs")
    if capsule["route_fingerprint"] != route_fingerprint(route):
        failures.append("execution capsule route fingerprint does not match source docs")
    if capsule["request_fingerprint"] != request_fingerprint(_request_intake(evidence_path)):
        failures.append("execution capsule request fingerprint does not match source docs")
    failures.extend(
        file_binding_failures(
            capsule["preflight_evidence"], evidence_path, "source-docs preflight evidence"
        )
    )
    failures.extend(preflight_identity_failures(evidence_path, project, rules))
    failures.extend(
        required_doc_failures(
            capsule["required_docs"],
            rules,
            route,
            documented_updates=documented_updates,
        )
    )
    return list(dict.fromkeys(failures))


def validate_preflight_snapshot(
    snapshot: dict[str, Any],
    project: Path,
    evidence_path: Path,
    rules: Path,
    route: dict[str, Any],
    documented_updates: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Validate the no-worker source-doc snapshot captured at parent start."""

    project = project.resolve()
    evidence_path = evidence_path.resolve()
    rules = rules.resolve()
    failures = _preflight_snapshot_shape_failures(snapshot)
    if failures:
        return failures
    if snapshot["route_fingerprint"] != route_fingerprint(route):
        failures.append("preflight snapshot route fingerprint does not match source docs")
    if snapshot["request_fingerprint"] != request_fingerprint(_request_intake(evidence_path)):
        failures.append("preflight snapshot request fingerprint does not match source docs")
    failures.extend(preflight_identity_failures(evidence_path, project, rules))
    failures.extend(
        required_doc_failures(
            snapshot["required_docs"],
            rules,
            route,
            documented_updates=documented_updates,
        )
    )
    return list(dict.fromkeys(failures))


def _native_shape(kind: str, record: Any) -> list[str] | None:
    result = native_capsule_probe("capsule-shape", kind, record)
    failures = result.get("failures") if result is not None else None
    if type(failures) is list and len(failures) <= 1 and all(type(item) is str for item in failures):
        return failures
    return None


def _shape_failures(capsule: dict[str, Any]) -> list[str]:
    native = _native_shape("capsule", capsule)
    if native is not None:
        return native
    if not capsule:
        return ["execution capsule is missing"]
    if capsule.get("invalid_json"):
        return ["execution capsule is not valid JSON"]
    if capsule.get("schema_version") != SCHEMA_VERSION:
        return ["execution capsule has an unsupported schema version"]
    if set(capsule) - _TOP_LEVEL_FIELDS:
        return ["execution capsule contains unsupported fields"]
    if capsule.get("phase") not in {"preflight", "ready"}:
        return ["execution capsule has an invalid phase"]
    if not isinstance(capsule.get("created_at"), str) or not capsule["created_at"]:
        return ["execution capsule created_at is missing"]
    if not is_sha256(capsule.get("route_fingerprint")):
        return ["execution capsule route fingerprint is malformed"]
    if not is_sha256(capsule.get("request_fingerprint")):
        return ["execution capsule request fingerprint is malformed"]
    if not _is_file_hash(capsule.get("preflight_evidence")):
        return ["execution capsule preflight evidence is malformed"]
    if not _is_git(capsule.get("project_git")) or not _is_git(capsule.get("rules_git")):
        return ["execution capsule git state is malformed"]
    if capsule.get("reuse_policy") != REUSE_POLICY:
        return ["execution capsule reuse policy does not match"]
    if not isinstance(capsule.get("required_docs"), list) or any(
        not _is_doc(item) for item in capsule["required_docs"]
    ):
        return ["execution capsule required docs are malformed"]
    if "gate_ledger" in capsule and not _is_file_hash(capsule["gate_ledger"]):
        return ["execution capsule gate ledger is malformed"]
    return []


def _is_file_hash(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == _FILE_HASH_FIELDS
            and isinstance(value.get("filename"), str) and bool(value["filename"])
            and Path(value["filename"]).name == value["filename"] and is_sha256(value.get("sha256")))


def _is_git(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == _GIT_FIELDS
            and isinstance(value.get("head"), str) and bool(value["head"])
            and is_sha256(value.get("worktree_fingerprint"))
            and is_sha256(value.get("worktree_signature")))


def _is_doc(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == _DOC_FIELDS
            and isinstance(value.get("path"), str) and bool(value["path"])
            and isinstance(value.get("size_bytes"), int) and value["size_bytes"] >= 0
            and is_sha256(value.get("sha256")))


def _preflight_snapshot_shape_failures(snapshot: dict[str, Any]) -> list[str]:
    native = _native_shape("preflight", snapshot)
    if native is not None:
        return native
    expected = {
        "schema_version",
        "route_fingerprint",
        "request_fingerprint",
        "required_docs",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != expected:
        return ["preflight snapshot is malformed"]
    if snapshot.get("schema_version") != PREFLIGHT_SNAPSHOT_SCHEMA_VERSION:
        return ["preflight snapshot has an unsupported schema version"]
    if not is_sha256(snapshot.get("route_fingerprint")):
        return ["preflight snapshot route fingerprint is malformed"]
    if not is_sha256(snapshot.get("request_fingerprint")):
        return ["preflight snapshot request fingerprint is malformed"]
    if not isinstance(snapshot.get("required_docs"), list) or any(
        not _is_doc(item) for item in snapshot["required_docs"]
    ):
        return ["preflight snapshot required docs are malformed"]
    return []


def _request_intake(evidence_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    intake = payload.get("request_intake") if isinstance(payload, dict) else None
    return dict(intake) if isinstance(intake, dict) else {}
