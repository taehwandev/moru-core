"""Runtime-neutral capability and sandbox policy for Moru Core tasks."""

from __future__ import annotations

from typing import Any


READ_ONLY_WORK_KINDS = frozenset({"analysis", "repetitive"})
SANDBOX_MODES = frozenset({"read-only", "workspace-write", "isolated-write"})
ENFORCEMENT_MODES = frozenset({"runtime-read-only", "runtime-workspace-write", "filesystem-boundary"})


def capability_profile(work_kind: str, *, isolation_required: bool = False) -> dict[str, Any]:
    if work_kind in READ_ONLY_WORK_KINDS:
        return {
            "work_kind": work_kind,
            "authoring_policy": "read-only non-authoring",
            "sandbox_mode": "read-only",
            "enforcement": "runtime-read-only",
            "enforcement_scope": "runtime-read-only",
            "filesystem": "read-only",
            "network": "deny",
            "child_process": "deny",
        }
    return {
        "work_kind": work_kind,
        "authoring_policy": "code authoring allowed",
        # The runtime sandbox remains workspace-write for compatibility;
        # isolation is enforced by explicit filesystem and worker boundaries.
        "sandbox_mode": "workspace-write",
        "isolation_mode": "isolated-write" if isolation_required else "workspace",
        # The worker's real working directory: a dedicated git worktree when
        # isolated, otherwise the shared project checkout. workspace-write inside
        # the worktree directory is correct, so sandbox_mode is unchanged.
        "working_dir_kind": "worktree" if isolation_required else "workspace",
        "enforcement": "filesystem-boundary" if isolation_required else "runtime-workspace-write",
        "enforcement_scope": "worker-evidence-and-state" if isolation_required else "project-workspace",
        "filesystem": "isolated-write" if isolation_required else "workspace-write",
        "network": "runtime-policy",
        "child_process": "explicit-isolation-only",
    }


def validate_capability_profile(profile: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if profile.get("sandbox_mode") not in SANDBOX_MODES:
        failures.append("sandbox_mode must be read-only, workspace-write, or isolated-write")
    if profile.get("sandbox_mode") == "read-only" and profile.get("authoring_policy") != "read-only non-authoring":
        failures.append("read-only sandbox requires non-authoring policy")
    enforcement = profile.get("enforcement")
    if enforcement not in ENFORCEMENT_MODES:
        failures.append("enforcement must identify the runtime or filesystem boundary")
    if profile.get("sandbox_mode") == "isolated-write" and profile.get("filesystem") != "isolated-write":
        failures.append("isolated-write sandbox requires isolated filesystem capability")
    isolation_mode = profile.get("isolation_mode", "workspace")
    if isolation_mode not in {"workspace", "isolated-write"}:
        failures.append("isolation_mode must be workspace or isolated-write")
    if isolation_mode == "isolated-write" and profile.get("filesystem") != "isolated-write":
        failures.append("isolated-write isolation requires isolated filesystem capability")
    if profile.get("sandbox_mode") == "read-only" and enforcement != "runtime-read-only":
        failures.append("read-only sandbox requires runtime-read-only enforcement")
    if isolation_mode == "isolated-write" and enforcement != "filesystem-boundary":
        failures.append("isolated-write isolation requires filesystem-boundary enforcement")
    scope = profile.get("enforcement_scope")
    if scope not in {"runtime-read-only", "runtime-workspace-write", "worker-evidence-and-state", "project-workspace"}:
        failures.append("enforcement_scope is unsupported")
    if isolation_mode == "isolated-write" and scope != "worker-evidence-and-state":
        failures.append("isolated-write isolation requires worker-evidence-and-state scope")
    working_dir_kind = profile.get("working_dir_kind")
    if working_dir_kind is not None and working_dir_kind not in {"workspace", "worktree"}:
        failures.append("working_dir_kind must be workspace or worktree")
    if working_dir_kind == "worktree" and isolation_mode != "isolated-write":
        failures.append("worktree working_dir requires isolated-write isolation")
    return failures
