"""Classify worker failures without replaying work whose effects are uncertain.

Owner: dispatch recovery policy and bounded CLI-event normalization.
Allowed imports: standard library only. Forbidden: execution, state writes,
permissions and provider calls. Caller: dispatch launch; tests: mirrored module.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_RETRIES = 2
_TRANSIENT = {"ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "ETIMEDOUT", "UNAVAILABLE",
              "RATE_LIMIT_EXCEEDED", "OVERLOADED", "RESOURCE_EXHAUSTED", "SERVER_ERROR",
              "INTERNAL_SERVER_ERROR", "RATE_LIMIT_ERROR", "DEADLINE_EXCEEDED"}
_ACTIONS = {
    "CANCELLED": "honor_cancellation", "ABORTED": "honor_cancellation",
    "INVALID_ARGUMENT": "correct_invocation_and_retry", "INVALID_REQUEST_ERROR": "correct_invocation_and_retry",
    "UNAUTHENTICATED": "check_existing_auth", "INVALID_API_KEY": "check_existing_auth",
    "PERMISSION_DENIED": "use_approved_permission_path", "EACCES": "use_approved_permission_path",
    "EPERM": "use_approved_permission_path", "ENOENT": "resolve_tool_path",
    "INSUFFICIENT_QUOTA": "check_quota", "EXISTING_TURN": "wait_existing_execution",
    "HTTP_400": "correct_invocation_and_retry", "HTTP_401": "check_existing_auth",
    "HTTP_403": "use_approved_permission_path", "HTTP_402": "check_quota",
}
_TRANSIENT_HTTP = {"HTTP_408", "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}


def recovery_message(action: str) -> str:
    if action in {"inspect_failure_and_correct_owner", "retry_transient"}:
        return ""
    return {
        "correct_invocation_and_retry": "Correct the reported arguments or working directory, then rerun the failed step; no framework edit is required.",
        "check_existing_auth": "Check existing host authentication and session access before concluding credentials are missing; preserve credential-change approval.",
        "use_approved_permission_path": "Reuse existing user authority and the native permission path; retry only after the actual permission condition changes.",
        "resolve_tool_path": "Resolve the installed tool path or documented project setup, then rerun the failed step.",
        "honor_cancellation": "Honor cancellation; do not relaunch the worker.",
        "observe_before_retry": "Inspect existing work and reconcile external effects before resuming; do not replay the whole worker.",
        "wait_existing_execution": "Read or wait on the existing execution handle; do not submit a duplicate turn.",
        "retry_budget_exhausted": "Automatic retries are exhausted; diagnose or change the failed condition before another attempt.",
    }.get(action, f"{action}: diagnose the failing owner and continue only after its condition is corrected.")


@dataclass(frozen=True)
class WorkerOutcome:
    returncode: int
    error_code: str = "UNKNOWN"
    replay_safe: bool = False
    retry_after: float = 0
    retry_allowed: bool = True

    @property
    def action(self) -> str:
        if self.returncode == 0:
            return "complete"
        code = self.error_code.upper()
        if self.returncode in {130, -2, 143, -15}:
            return "honor_cancellation"
        if code in _ACTIONS:
            return _ACTIONS[code]
        if self.returncode == 2 and code == "UNKNOWN":
            return "correct_invocation_and_retry"
        if code not in _TRANSIENT and code not in _TRANSIENT_HTTP:
            return "inspect_failure_and_correct_owner"
        if self.retry_allowed is not True:
            return "inspect_failure_and_correct_owner"
        if not self.replay_safe:
            return "observe_before_retry"
        if not math.isfinite(self.retry_after) or self.retry_after < 0 or self.retry_after > 30:
            return "wait_retry_window"
        return "retry_transient"

    def delay(self, attempt: int) -> float:
        return max(min(2 ** max(0, min(attempt - 1, 5)), 30), self.retry_after)


def _error_code(error: dict) -> str:
    code = str(error.get("code") or "").upper()
    if code in _ACTIONS:
        return code
    status = error.get("status_code", error.get("status"))
    if str(status).isdigit():
        return f"HTTP_{status}"
    if code.isdigit():
        return f"HTTP_{code}"
    if code in _TRANSIENT or code.startswith("HTTP_"):
        return code
    # Older CLI error events expose only a message. Normalize transport syntax
    # here, never scan agent prose or successful tool output for error words.
    message = str(error.get("message") or "")
    match = re.search(r"\b(?:HTTP|status(?: code)?)\s*[:=]?\s*(\d{3})\b", message, re.I)
    if match:
        return f"HTTP_{match.group(1)}"
    for marker in ("ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "ETIMEDOUT"):
        if marker in message.upper():
            return marker
    if any(marker in message.lower() for marker in ("error sending request", "connection reset", "temporary failure in name resolution")):
        return "UNAVAILABLE"
    return "UNKNOWN"


def read_worker_outcome(returncode: int, path: Path, offset: int = 0) -> WorkerOutcome:
    """Only complete, pre-tool CLI failure streams are candidates for replay."""
    if returncode == 0:
        return WorkerOutcome(0)
    try:
        if path.is_symlink():
            return WorkerOutcome(returncode)
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            return WorkerOutcome(returncode)
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        return WorkerOutcome(returncode)
    safe, failure = True, {}
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("invalid event")
        except ValueError:
            safe = False
            continue
        kind = str(event.get("type") or "")
        if kind in {"error", "turn.failed"}:
            error = event.get("error", event)
            failure = dict(error) if isinstance(error, dict) else {"message": str(error)}
            for key in ("retryable", "retry_after_seconds", "turn_in_progress", "outcome_unknown"):
                if key not in failure and key in event:
                    failure[key] = event[key]
            if failure.get("turn_in_progress") or failure.get("outcome_unknown"):
                safe = False
        elif kind.startswith("item."):
            item = event.get("item") or {}
            if not isinstance(item, dict) or item.get("type") not in {"agent_message", "reasoning", "todo_list"}:
                safe = False
        elif kind not in {"thread.started", "turn.started", "turn.completed"}:
            safe = False
    if failure.get("turn_in_progress") or failure.get("outcome_unknown"):
        return WorkerOutcome(returncode, "EXISTING_TURN")
    try:
        retry_after = float(failure.get("retry_after_seconds", 0))
    except (TypeError, ValueError):
        retry_after = float("inf")
    return WorkerOutcome(returncode, _error_code(failure), safe and bool(failure), retry_after,
                         failure.get("retryable", True) is True)
