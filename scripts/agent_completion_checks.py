"""Thin bindings for native completion quality, coverage and progress decisions.

Owner: native completion integration. Allowed: existing ledger, local atomic
storage and native protocol. Forbidden: decision algorithms, command execution,
authority, new continuation budgets, providers and global state writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from support.completion_native import completion_available, completion_native


def quality_notes(records: list[dict]) -> list[str]:
    selected = [row for row in records if row.get("gate") == "tests" and row.get("fields")]
    if not selected:
        return []
    result = completion_native("quality", {"records": selected})
    labels = {"fixed_output_check": "a fixed-output command does not observe the requested artifact",
              "zero_test_count": "a zero-test result needs an actual observing check"}
    return [f"Verification quality warning [{row['gate']}]: {labels[row['rule']]}"
            for row in (result or {}).get("warnings", []) if row.get("rule") in labels]


def requirement_update(current: dict, previous: dict | None) -> None:
    result = completion_native("requirements", {"current": current, "previous": previous})
    if result is None:
        raise ValueError("requirements need an available matching native runtime; build/install it before recording this opt-in contract")
    if result.get("failures"):
        raise ValueError("; ".join(result["failures"]))


def _gates(evidence: Path) -> list[dict]:
    from agent_gate_evidence import gate_evidence_path_for_preflight, read_gate_evidence_ledger

    ledger = read_gate_evidence_ledger(gate_evidence_path_for_preflight(evidence))
    return ledger.get("entries", [])


def coverage_failures(project: Path, evidence: Path, work: dict, route: dict) -> list[str]:
    if "requirements" not in work:
        return []
    result = completion_native("coverage", {"current": work["requirements"], "project": str(project.resolve()),
        "gates": _gates(evidence), "allowed_gates": route.get("gates", [])})
    if result is None:
        return ["requirements coverage is unavailable; restore the matching native runtime before finish"]
    return result["failures"]


def progress_note(project: Path, evidence: Path, work: dict, identity: dict) -> str:
    from agent_execution_capsule_state import atomic_write_json
    try:
        import fcntl
        if not completion_available():
            return ""
        if evidence.parent.resolve() != evidence.parent or not evidence.parent.is_relative_to(project / ".moru/runs"):
            return ""
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        path = evidence.parent / f"completion-progress-{key}.json"
        if path.is_symlink():
            return ""
        lock = path.with_name("." + path.name + ".lock")
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(descriptor, "a+b") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return ""
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists() and path.stat().st_size > 4096:
                return ""
            previous = json.loads(path.read_text()) if path.exists() else None
            result = completion_native("progress", {"work": work, "gates": _gates(evidence), "previous": previous})
            if result is None:
                return ""
            atomic_write_json(path, result)
        return (" Acceptance progress has not changed across three Stop observations; inspect the remaining outcomes and blockers. "
                "This diagnosis grants no retry or completion authority.") if result.get("stalled") else ""
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return ""
