"""Provider-neutral API and runtime-adapter contracts for Moru Core."""

from __future__ import annotations

import re
from typing import Any, Mapping


CONTRACT_VERSION = 1
RUNTIME_ADAPTER_VERSION = 1
SAFE_RUNTIME = re.compile(r"^[a-z][a-z0-9_.-]{0,31}$")
SUPPORTED_RUNTIMES = ("codex", "claude", "antigravity")


def api_contract_manifest() -> dict[str, int]:
    """Return the schema versions shared by status, task, capsule, and events."""

    return {
        "contract_version": CONTRACT_VERSION,
        "status_api_version": 2,
        "task_schema_version": 1,
        "capsule_schema_version": 3,
        "evidence_schema_version": 1,
        "event_schema_version": 1,
    }


def runtime_adapter_contract(
    runtime: str,
    *,
    capabilities: Mapping[str, bool],
    enforcement: str,
) -> dict[str, Any]:
    """Describe a runtime without embedding provider-specific execution details."""

    return {
        "contract_version": RUNTIME_ADAPTER_VERSION,
        "runtime": runtime,
        "capabilities": {str(key): bool(value) for key, value in capabilities.items()},
        "enforcement": enforcement,
    }


def runtime_adapter_catalog() -> list[dict[str, Any]]:
    """Return the shared adapter contract surface for all supported runtimes.

    This is contract parity, not a claim that every provider has identical hook
    installation or OS-level sandbox behavior.
    """

    return [
        runtime_adapter_contract(
            runtime,
            capabilities={"read_only": True, "workspace_write": True, "isolated_write": True},
            enforcement="bridge-contract",
        ) | {"integration_status": "bridge-contract"}
        for runtime in SUPPORTED_RUNTIMES
    ]


def validate_runtime_adapter_catalog(catalog: list[Mapping[str, Any]]) -> list[str]:
    failures: list[str] = []
    names = {str(contract.get("runtime")) for contract in catalog}
    for runtime in SUPPORTED_RUNTIMES:
        if runtime not in names:
            failures.append(f"runtime adapter missing: {runtime}")
    for contract in catalog:
        failures.extend(validate_runtime_adapter_contract(contract))
        if contract.get("integration_status") not in {"bridge-contract", "connected"}:
            failures.append(f"runtime adapter status is unsupported: {contract.get('runtime')}")
    return failures


def validate_runtime_adapter_contract(contract: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if contract.get("contract_version") != RUNTIME_ADAPTER_VERSION:
        failures.append("runtime adapter contract version is unsupported")
    runtime = contract.get("runtime")
    if not isinstance(runtime, str) or not SAFE_RUNTIME.fullmatch(runtime):
        failures.append("runtime adapter name is malformed")
    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, Mapping) or not capabilities:
        failures.append("runtime adapter capabilities are missing")
    elif any(not isinstance(value, bool) for value in capabilities.values()):
        failures.append("runtime adapter capabilities must be boolean")
    if not isinstance(contract.get("enforcement"), str) or not contract["enforcement"]:
        failures.append("runtime adapter enforcement is missing")
    return failures


def validate_api_contract_manifest(manifest: Mapping[str, Any]) -> list[str]:
    expected = api_contract_manifest()
    return [
        f"{key} contract version mismatch"
        for key, value in expected.items()
        if manifest.get(key) != value
    ]


def validate_status_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    """Validate the stable, content-free fields consumed by external clients."""

    failures: list[str] = []
    for key in ("api_version", "snapshot_id", "captured_at", "consistency", "api_contract", "task_counts", "events"):
        if key not in snapshot:
            failures.append(f"status snapshot field missing: {key}")
    if snapshot.get("api_version") != 2:
        failures.append("status snapshot api_version is unsupported")
    if snapshot.get("consistency") != "project-state-lock":
        failures.append("status snapshot consistency contract is unsupported")
    if isinstance(snapshot.get("api_contract"), Mapping):
        failures.extend(validate_api_contract_manifest(snapshot["api_contract"]))
    else:
        failures.append("status snapshot api_contract is missing")
    adapters = snapshot.get("runtime_adapters")
    if not isinstance(adapters, list):
        failures.append("status snapshot runtime_adapters is missing")
    else:
        failures.extend(validate_runtime_adapter_catalog(adapters))
    return failures
