"""Prepared native registry reads with the canonical Python compatibility path.

Owner: registry read integration. Allowed: state locations/keys, state vocabulary
and private native transport. Forbidden: claims, ownership decisions, mutation,
caches and per-candidate subprocesses. Callers/tests: runtime-session discovery;
test_native_registry_read and registry/session regressions verify parity.
"""
from __future__ import annotations

from pathlib import Path
import sys

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


def retention_states(path: Path, states: frozenset[str]) -> tuple[bool, dict | None]:
    """Read a retention map without locks; decline before any deletion decision."""
    if type(path) is not type(Path()) or type(states) not in (set, frozenset) or any(type(s) is not str for s in states):
        return False, None
    try:
        result = NativeProbe.request("--registry-read-probe", "retention-states", {
            "state_dir": str(path.parent), "states": sorted(states),
            "int_digits": getattr(sys, "get_int_max_str_digits", lambda: 0)()})
    except (OSError, ValueError, RuntimeError):
        return False, None
    if type(result) is not dict or set(result) != {"value"}:
        return False, None
    rows = result["value"]
    if rows is None:
        return True, None
    if type(rows) is not list:
        return False, None
    values = {}
    for row in rows:
        if (type(row) is not list or len(row) != 2 or any(type(v) is not str for v in row)
                or not row[0] or row[0] in values or row[1] not in states):
            return False, None
        values[row[0]] = row[1]
    return True, values


def retention_identities(paths: list[Path]) -> dict | None:
    """Project a whole preview in one process, preserving complete identities."""
    if type(paths) is not list or any(type(path) is not type(Path()) for path in paths):
        return None
    if not paths:
        return {}
    try:
        result = NativeProbe.request("--registry-read-probe", "retention-identities", {"paths": [str(path) for path in paths]})
    except (OSError, ValueError, RuntimeError):
        return None
    if type(result) is not dict or set(result) != {"value"} or type(result["value"]) is not list:
        return None
    if len(result["value"]) != len(paths):
        return None
    identities = [_identity_rows(rows) for rows in result["value"]]
    return dict(zip(paths, identities)) if all(value is not None for value in identities) else None


def _identity_rows(rows) -> tuple | None:
    if type(rows) is not list:
        return None
    previous = None
    for index, row in enumerate(rows):
        if (type(row) is not list or len(row) != 7 or type(row[0]) is not str
                or any(type(value) is not int for value in row[1:]) or any(value < 0 for value in row[1:5])):
            return None
        name = row[0]
        order = tuple(name.split("/"))
        if index == 0:
            if name != ".":
                return None
        elif (not name or name.startswith("/") or any(part in {"", ".", ".."} for part in order)
              or previous is not None and order <= previous):
            return None
        else:
            previous = order
    return tuple(tuple(row) for row in rows) if rows else None


def retention_bytes(paths: list[Path]) -> int | None:
    if type(paths) is not list or any(type(path) is not type(Path()) for path in paths):
        return None
    if not paths:
        return 0
    try:
        result=NativeProbe.request("--registry-read-probe","retention-bytes",{"paths":[str(path) for path in paths]})
    except (OSError,ValueError,RuntimeError):
        return None
    if type(result) is not dict or set(result)!={"value"}:
        return None
    value=result["value"]
    if (type(value) is not str or not value or len(value)>24 or not value.isascii() or not value.isdecimal()
            or len(value)>1 and value.startswith("0")):
        return None
    return int(value)
