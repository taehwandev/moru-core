"""Per-conversation state for the Antigravity hook adapter: identity, delivery markers and round counters.

State lives under MARKER_DIR, or in the judge service when one is configured, so the session being checked
cannot read or edit what it is checked against.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def workspace(payload: dict) -> str:
    paths = payload.get("workspacePaths")
    if isinstance(paths, list) and paths:
        return str(paths[0])
    return os.getcwd()


def session_id(payload: dict) -> str:
    return str(payload.get("conversationId") or "")


MARKER_DIR = Path.home() / ".moru" / "agy-hook"
MARKER_MAX_AGE_SECONDS = 7 * 24 * 3600


def _marker_target(conversation: str, text: str, kind: str) -> tuple[Path | None, str]:
    safe = "".join(ch for ch in conversation if ch.isalnum() or ch in "-_")
    if not safe:
        return None, ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return MARKER_DIR / f"{safe}.{kind}.digest", digest


def has_delivered(conversation: str, text: str, kind: str = "route") -> bool:
    """Whether this conversation already recorded ``text`` under ``kind`` without mutating state."""

    marker, digest = _marker_target(conversation, text, kind)
    if marker is None:
        return False
    try:
        return marker.read_text(encoding="utf-8") == digest
    except OSError:
        return False


def already_delivered(conversation: str, text: str, kind: str = "route") -> bool:
    """Whether this conversation already holds exactly this text; record it if not.

    The shared route cache only exists once a project has run a hook, so a new
    workspace would otherwise be re-sent the same text on every model call.
    """

    marker, digest = _marker_target(conversation, text, kind)
    if marker is None:
        return False
    try:
        if marker.read_text(encoding="utf-8") == digest:
            return True
    except OSError:
        pass
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(digest, encoding="utf-8")
        cutoff = time.time() - MARKER_MAX_AGE_SECONDS
        for old in MARKER_DIR.glob("*.digest"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
    except OSError:
        pass
    return False


def _verifier():
    sys.path.insert(0, str(SCRIPTS / "page_verify"))
    import verify

    return verify


STATE_TTL_SECONDS = 3600


def load_state(path: Path, kind: str) -> dict:
    """Hook state. With a judge service it lives there, out of reach of the session being checked.

    State untouched for STATE_TTL_SECONDS is dropped, so repeating an identical request much later
    starts clean instead of inheriting the earlier request's rounds.
    """

    state = _load_state(path, kind)
    if time.time() - float(state.get("at", 0) or 0) > STATE_TTL_SECONDS:
        return {}
    return state


def _load_state(path: Path, kind: str) -> dict:
    if os.environ.get("MORU_VERIFY_JUDGE_URL"):
        try:
            value = _verifier().remote_call("/state", {"op": "get", "key": f"{path.stem.split('.')[0]}.{kind}"}).get("value")
            return value if isinstance(value, dict) else {}
        except Exception:  # noqa: BLE001 - an unreachable service means no state, not a trapped stop
            return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: Path, kind: str, state: dict | None) -> None:
    """Persist ``state`` stamped with the time; None forgets it."""

    if state is not None:
        state = {**state, "at": time.time()}

    if os.environ.get("MORU_VERIFY_JUDGE_URL"):
        try:
            _verifier().remote_call("/state", {"op": "put", "key": f"{path.stem.split('.')[0]}.{kind}", "value": state})
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        if state is None:
            path.unlink(missing_ok=True)
        else:
            MARKER_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def verification_state_path(conversation: str) -> Path | None:
    safe = "".join(ch for ch in conversation if ch.isalnum() or ch in "-_")
    return MARKER_DIR / f"{safe}.verify.json" if safe else None


def continuations_for(payload: dict) -> tuple[Path | None, dict]:
    """How many times a stop hook already continued this conversation for the current user input.

    Claude tells its Stop hooks so through ``stop_hook_active``; Antigravity's ``executionNum`` does
    not accumulate, which let the finish gate block again after every edit (ten blocks in one run).
    """

    safe = "".join(ch for ch in session_id(payload) if ch.isalnum() or ch in "-_")
    if not safe:
        return None, {}
    path = MARKER_DIR / f"{safe}.stop.json"
    digest = hashlib.sha256(str(payload.get("lastUserInput") or "").encode("utf-8")).hexdigest()
    state = load_state(path, "stop")
    if state.get("input") != digest:
        state = {"input": digest, "continuations": 0}
    return path, state


def count_continuation(path: Path | None, state: dict) -> None:
    if path is None:
        return
    state["continuations"] = int(state.get("continuations", 0)) + 1
    save_state(path, "stop", state)


_MAX_TRANSCRIPT_TAIL_BYTES = 4 * 1024 * 1024
_BG_TASK_RUNNING_RE = re.compile(r"(?:^|\n)Tool is running as a background task with task id:\s*(\S+)")
_BG_TASK_DONE_RE = re.compile(r'Task id "([^"]+)" (?:finished|was cancel(?:l)?ed) with result:')
_BG_TASK_KILLED_RE = re.compile(r'(?:^|\n)Task "([^"]+)" cancel(?:l)?ed\.')
_SYS_TASK_SENDER_RE = re.compile(r"\[Message\]\s+timestamp=\S+\s+sender=(\S*?/task-\S+)")
_SERVER_RESTART_NOTICE = "[Notice] All your subagents and background tasks have been stopped"


def _call_is_daemon(call: dict) -> bool:
    if str(call.get("name") or "") != "run_command":
        return False
    args = call.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        return False
    flag = args.get("IsDaemon")
    return flag is True or str(flag or "").strip().lower() == "true"


def _read_latest_transcript_steps(transcript: Path) -> list[dict]:
    size = transcript.stat().st_size
    if size <= 0:
        return []
    start = max(0, size - _MAX_TRANSCRIPT_TAIL_BYTES)
    with transcript.open("rb") as handle:
        handle.seek(start)
        text = handle.read().decode("utf-8", errors="replace")
    if start > 0:
        newline = text.find("\n")
        text = text[newline + 1 :] if newline >= 0 else ""
    order: list[int] = []
    latest: dict[int, dict] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            step = json.loads(line)
        except ValueError:
            continue
        idx = step.get("step_index") if isinstance(step, dict) else None
        if isinstance(idx, int) and not isinstance(idx, bool):
            if idx not in latest:
                order.append(idx)
            latest[idx] = step
    return [latest[idx] for idx in order]


def _settle_system_messages(content: str, running_tasks: set[str]) -> None:
    if _SERVER_RESTART_NOTICE in content:
        running_tasks.clear()
        return
    for match in _BG_TASK_DONE_RE.finditer(content):
        running_tasks.discard(match.group(1).strip())
    for match in _SYS_TASK_SENDER_RE.finditer(content):
        running_tasks.discard(match.group(1).strip())


def has_inflight_background_task(payload: dict) -> bool:
    """Whether AGY is yielding the turn only to wait on a non-daemon background task."""

    raw_path = str(payload.get("transcriptPath") or "").strip()
    if not raw_path:
        return False
    transcript = Path(raw_path)
    if not transcript.is_file():
        return False
    try:
        steps = _read_latest_transcript_steps(transcript)
    except OSError:
        return False
    pending_daemons: list[bool] = []
    inflight_daemons: dict[int, bool] = {}
    running_tasks: set[str] = set()
    for step in steps:
        idx = int(step["step_index"])
        step_type = str(step.get("type") or "")
        content = str(step.get("content") or "")
        if step_type == "PLANNER_RESPONSE":
            calls = [item for item in (step.get("tool_calls") or []) if isinstance(item, dict)]
            pending_daemons = [_call_is_daemon(call) for call in calls]
        elif step_type == "SYSTEM_MESSAGE":
            _settle_system_messages(content, running_tasks)
        elif step_type not in {"USER_INPUT", "CHECKPOINT", "CONVERSATION_HISTORY"}:
            if str(step.get("source") or "") in {"USER_EXPLICIT", "SYSTEM", "SYSTEM_SDK"}:
                continue
            is_daemon = inflight_daemons[idx] if idx in inflight_daemons else (pending_daemons.pop(0) if pending_daemons else False)
            if str(step.get("status") or "DONE") in {"RUNNING", "ACTIVE"}:
                inflight_daemons[idx] = is_daemon
                match = _BG_TASK_RUNNING_RE.search(content)
                if match and not is_daemon:
                    running_tasks.add(match.group(1).strip())
            else:
                inflight_daemons.pop(idx, None)
                for match in _BG_TASK_KILLED_RE.finditer(content):
                    running_tasks.discard(match.group(1).strip())
                if "<SYSTEM_MESSAGE>" in content:
                    _settle_system_messages(content, running_tasks)
    return bool(running_tasks)
