"""Validate a provider observation supplied by the caller; never execute repo code."""

from __future__ import annotations

import json
from pathlib import Path

from support.native_probe_transport import NativeProbe


def _native_observation(operation: str, payload: dict) -> tuple[str, str] | None:
    result = NativeProbe.request("--completion-probe", operation, payload)
    if result is not None and set(result) == {"observation", "reason"}:
        observation, reason = result["observation"], result["reason"]
        if isinstance(observation, str) and isinstance(reason, str) and bool(observation) != bool(reason):
            return observation, reason
    return None


def observe_upstream(listed: str | None, remote: str, merge: str, head: str) -> tuple[str, str]:
    native = _native_observation("publication-upstream-proof", {
        "listed": listed or "", "remote": remote, "merge": merge, "head": head,
    })
    if native is not None:
        return native
    fields = (listed or "").split()
    if not fields or fields[0] != head:
        return "", "the upstream branch does not point at HEAD"
    return f"{remote} {merge} is {head}", ""


def observe_pull_request(project: Path, head: str, target: str, git, observation: Path | None = None) -> tuple[str, str]:
    branch = git(project, "symbolic-ref", "--short", "HEAD")
    if observation is None or not branch:
        return "", "a provider-observed pull request result is required"
    native = _native_observation("publication-pr-proof", {
        "path": str(observation), "branch": branch, "head": head, "target": target,
    })
    if native is not None:
        return native
    return _observe_pull_request_python(observation, branch, head, target)


def _observe_pull_request_python(observation: Path, branch: str, head: str, target: str) -> tuple[str, str]:
    try:
        if observation.stat().st_size > 65536:
            return "", "the provider observation is too large"
        answer = json.loads(observation.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", "the provider observation could not be read as JSON"
    if not isinstance(answer, dict) or answer.get("exists") is not True:
        return "", "no pull request was observed for this branch"
    if (answer.get("source_branch"), answer.get("source_commit"), answer.get("target_branch")) != (branch, head, target):
        return "", "the observed pull request does not match this branch, reviewed commit and target"
    if answer.get("state") not in ("OPEN", "MERGED"):
        return "", "the observed pull request is not open or merged"
    return f"caller-observed pull request {answer['state']}: {branch}@{head} -> {target}", ""
