"""Validate a provider observation supplied by the caller; never execute repo code."""

from __future__ import annotations

import json
from pathlib import Path


def observe_pull_request(project: Path, head: str, target: str, git, observation: Path | None = None) -> tuple[str, str]:
    branch = git(project, "symbolic-ref", "--short", "HEAD")
    if observation is None or not branch:
        return "", "a provider-observed pull request result is required"
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
