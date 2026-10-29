"""Optional task-boundary advice; never a gate or a compaction action.

Owner: successful-finish context nudge. Allowed imports: standard library.
Forbidden: provider calls, transcript content output, writes, runtime mutation.
Callers/tests: agent-hook.py; test_agent_finish_context and hook continuation.
Verification: synthetic local transcripts and successful-finish wiring tests.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_THRESHOLD = 200_000
MAX_TAIL_BYTES = 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _latest_context_tokens(transcript: Path) -> int | None:
    """Only numeric input usage from the latest main assistant entry, if known."""
    with transcript.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - MAX_TAIL_BYTES)
        stream.seek(offset)
        if offset:
            stream.readline()  # Discard a possibly partial first record.
        lines = stream.read(MAX_TAIL_BYTES).splitlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            return None  # Do not reuse pre-compaction usage.
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            return None
        values = [usage.get("input_tokens"), usage.get("cache_creation_input_tokens", 0),
                  usage.get("cache_read_input_tokens", 0)]
        if not all(type(value) is int and value >= 0 for value in values):
            return None
        return sum(values)
    return None


def context_nudge(session: dict[str, str], run_id: str, *, threshold: int = DEFAULT_THRESHOLD) -> str:
    """Fail quietly when runtime, exact session transcript or usage is unknown."""
    if session.get("runtime") != "claude":  # Codex already compacts automatically.
        return ""
    session_id = session.get("session_id", "")
    if not _SAFE_ID.fullmatch(session_id) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        return ""
    try:
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
        transcripts = list((config / "projects").glob(f"*/{session_id}.jsonl"))
        if len(transcripts) != 1:
            return ""
        tokens = _latest_context_tokens(transcripts[0])
    except (OSError, ValueError):
        return ""
    if tokens is None or tokens < threshold:
        return ""
    return ("For the user: next unrelated work -> new session or /compact; related follow-up -> "
            f"keep, or rotate with start --continue-from {run_id}.")
