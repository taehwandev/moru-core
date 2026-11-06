"""Fail-closed union of current, run-bound scoped review attestations.

Owner: publication review coverage; allowed imports: attestation validation,
read-only Git/source binding; forbidden imports: command execution/authority.
Callers/tests: PublicationAdmission / test_agent_publication_review_union.
Verification: temporary Git repositories with independent reviewed scopes.
"""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path

from agent_review_attestation import ReviewAttestation, _attestation_id, _record_shape_failures
from agent_review_scope_inputs import scoped_review_binding, scoped_review_digest
from support.bounded_git import run_git


def _verify_integrity(record: object) -> None:
    if (not isinstance(record, dict) or _record_shape_failures(record)
            or record["attestation_id"] != _attestation_id(record)):
        raise ValueError("review attestation archive integrity does not match")


def review_scope_for_receipt(project: Path, evidence: Path, evidence_hash: str) -> dict | None:
    """Preserve single-review compatibility and require exact aggregate coverage."""
    project, evidence = project.resolve(), evidence.resolve()
    latest_path = ReviewAttestation.path(evidence)
    archive = ReviewAttestation.archive_dir(evidence)
    preflight = json.loads(evidence.read_text())
    if not latest_path.exists() and not archive.exists():
        if "review hook" in preflight["route"].get("gates", []):
            raise ValueError("scoped review coverage is incomplete")
        return None
    latest = json.loads(latest_path.read_text())
    _verify_integrity(latest)
    rules = Path(preflight["rules"]).resolve()
    records = {latest["attestation_id"]: latest}
    for path in sorted(archive.glob("*.json")):
        record = json.loads(path.read_text())
        _verify_integrity(record)
        if path.stem != record.get("attestation_id"):
            raise ValueError("review attestation archive integrity does not match")
        records[path.stem] = record
    if not latest.get("project_inputs"):
        if latest["review_scope"].startswith("pathspec:") or ReviewAttestation.failures(
            project=project, rules=rules, evidence_path=evidence, route=preflight["route"],
            ledger_fields=ReviewAttestation.ledger_fields(latest), ledger_source="review",
            attestation=latest,
        ):
            raise ValueError("scoped review coverage is incomplete")
        return None
    paths, covered, components = set(), set(), []
    for record in records.values():
        if not record.get("project_inputs"):
            continue
        if record["preflight_evidence"]["sha256"] != evidence_hash:
            continue
        failures = ReviewAttestation.failures(
            project=project, rules=rules, evidence_path=evidence, route=preflight["route"],
            ledger_fields=ReviewAttestation.ledger_fields(record), ledger_source="review",
            attestation=record,
        )
        if failures:
            continue
        binding = scoped_review_binding(project, record["review_paths"], include_index=True)
        digest = hashlib.sha256(json.dumps(
            binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        if (digest != record["project_inputs"]
                or len(binding["changed_paths"]) != record["changed_path_count"]):
            continue
        paths.update(record["review_paths"])
        covered.update(binding["changed_paths"])
        components.append(record)
    staged = run_git(
        ["git", "diff", "--cached", "--name-only", "-z", "--no-renames", "--"],
        cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if staged.returncode:
        raise ValueError("scoped review inputs unavailable")
    staged_paths = {name.decode(errors="surrogateescape") for name in staged.stdout.split(b"\0") if name}
    if not covered or covered != staged_paths:
        raise ValueError("scoped review coverage is incomplete")
    selected = sorted(paths)
    inputs = scoped_review_binding(project, selected, include_index=True)
    if (any(scoped_review_digest(project, record["review_paths"], include_index=True)
            != record["project_inputs"] for record in components)
            or inputs != scoped_review_binding(project, selected, include_index=True)):
        raise ValueError("scoped review coverage changed during capture")
    return {
        "paths": selected,
        "inputs": inputs,
        "attestation_ids": sorted(record["attestation_id"] for record in components),
    }
