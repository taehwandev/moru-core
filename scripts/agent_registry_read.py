"""Prepared native registry reads with the canonical Python compatibility path.

Owner: registry read integration. Allowed: state locations/keys, state vocabulary
and private native transport. Forbidden: claims, ownership decisions, mutation,
caches and per-candidate subprocesses. Callers/tests: runtime-session discovery;
test_native_registry_read and registry/session regressions verify parity.
"""
from __future__ import annotations

from pathlib import Path

from agent_run_states import ACTIVE_RUN_STATES
from agent_state_read import evidence_binding_key, registry_path
from support.native_probe_transport import NativeProbe


def _request(project: Path, operation: str, **fields) -> dict | None:
    state = registry_path(project).parent
    return NativeProbe.request("--registry-read-probe", operation, {
        "state_dir": str(state), "legacy_key": evidence_binding_key(project, state / "preflight.json"),
        **fields,
    })


def active_runs(project: Path) -> list[dict]:
    result = _request(project, "active", states=sorted(ACTIVE_RUN_STATES))
    if result is not None:
        return result["value"]
    from agent_run_registry import active_runs as legacy
    return legacy(project)


def active_run_bindings(project: Path, states: frozenset[str] = ACTIVE_RUN_STATES) -> dict[str, dict]:
    result = _request(project, "bindings", states=sorted(states)) if all(isinstance(s, str) for s in states) else None
    if result is not None:
        return {key: run for key, run in result["value"]}
    from agent_run_registry import active_run_bindings as legacy
    return legacy(project, states)


def latest_run_id(project: Path, evidence_path: Path) -> str | None:
    state = registry_path(project).parent
    result = _request(project, "latest", evidence_key=evidence_binding_key(project, evidence_path),
        legacy_default=evidence_path.resolve() == state / "preflight.json", evidence_name=evidence_path.name)
    if result is not None:
        return result["value"]
    from agent_run_registry import latest_run_id as legacy
    return legacy(project, evidence_path)
