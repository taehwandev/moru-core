"""Identity and evidence bindings used by execution-capsule validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_execution_capsule_state import git_state, sha256_file
from agent_gate_evidence import read_gate_evidence_ledger
from agent_route_state import preflight_evidence_sha256, route_fingerprint


def preflight_identity_failures(
    evidence_path: Path,
    project: Path,
    rules: Path,
) -> list[str]:
    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["execution capsule preflight identity is unavailable"]
    if not isinstance(preflight, dict):
        return ["execution capsule preflight identity is malformed"]
    failures: list[str] = []
    try:
        recorded_project = Path(str(preflight["project"])).expanduser().resolve()
    except (KeyError, OSError, RuntimeError, ValueError):
        recorded_project = None
    try:
        recorded_rules = Path(str(preflight["rules"])).expanduser().resolve()
    except (KeyError, OSError, RuntimeError, ValueError):
        recorded_rules = None
    if recorded_project != project:
        failures.append("execution capsule preflight project identity does not match")
    if recorded_rules != rules:
        failures.append("execution capsule preflight rules identity does not match")
    resolved_evidence = evidence_path.resolve()
    legacy_root = project / ".tao"
    migrated_state = project / ".moru"
    migrated_runs = migrated_state / "runs"
    linked_runs = legacy_root / "runs"
    migrated_link_ready = (
        (migrated_state / "state-ready").is_file()
        and not migrated_state.is_symlink()
        and migrated_runs.is_dir()
        and not migrated_runs.is_symlink()
        and linked_runs.is_symlink()
        and linked_runs.resolve() == migrated_runs.resolve()
    )
    in_legacy_root = resolved_evidence.is_relative_to(legacy_root)
    in_migrated_runs = migrated_link_ready and resolved_evidence.is_relative_to(migrated_runs)
    if not in_legacy_root and not in_migrated_runs:
        failures.append(
            "execution capsule preflight evidence is outside the current project evidence root"
        )
    return failures


def gate_ledger_failures(
    ledger_path: Path,
    evidence_path: Path,
    route: dict[str, Any],
) -> list[str]:
    ledger = read_gate_evidence_ledger(ledger_path)
    if not ledger:
        return ["execution capsule parent gate ledger is missing"]
    if not isinstance(ledger, dict):
        return ["execution capsule parent gate ledger is malformed"]
    if ledger.get("invalid_json"):
        return ["execution capsule parent gate ledger is not valid JSON"]
    failures: list[str] = []
    if ledger.get("schema_version") != 1:
        failures.append("execution capsule parent gate ledger schema does not match")
    canonical_evidence_path = str(evidence_path.resolve())
    recorded_evidence = ledger.get("preflight_evidence")
    try:
        recorded_evidence_path = str(Path(str(recorded_evidence)).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        recorded_evidence_path = ""
    if recorded_evidence_path != canonical_evidence_path:
        failures.append("execution capsule parent gate ledger preflight path does not match")
    if ledger.get("preflight_evidence_sha256") != preflight_evidence_sha256(evidence_path):
        failures.append("execution capsule parent gate ledger preflight hash does not match")
    if ledger.get("route_fingerprint") != route_fingerprint(route):
        failures.append("execution capsule parent gate ledger route does not match")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        failures.append("execution capsule parent gate ledger entries are malformed")
    elif not any(
        entry.get("gate") == "request intake"
        and entry.get("status") == "SUCCESS"
        and isinstance(entry.get("evidence"), str)
        and bool(entry["evidence"].strip())
        for entry in entries
    ):
        failures.append(
            "execution capsule parent gate ledger lacks request intake SUCCESS evidence"
        )
    return failures


def file_binding_failures(
    record: dict[str, Any],
    path: Path,
    label: str,
) -> list[str]:
    failures = (
        []
        if record["filename"] == path.name
        else [f"execution capsule {label} filename does not match"]
    )
    if not path.is_file():
        failures.append(f"execution capsule {label} is missing")
    elif record["sha256"] != sha256_file(path):
        failures.append(f"execution capsule {label} hash does not match")
    return failures


def git_binding_failures(
    record: dict[str, Any],
    path: Path,
    label: str,
    *,
    current: dict[str, str] | None = None,
) -> list[str]:
    try:
        current = current or git_state(path)
    except (OSError, RuntimeError):
        return [f"execution capsule {label} git state is unavailable"]
    failures = []
    if record["head"] != current["head"]:
        failures.append(f"execution capsule {label} git HEAD changed")
    if record["worktree_fingerprint"] != current["worktree_fingerprint"]:
        failures.append(f"execution capsule {label} worktree status changed")
    return failures
