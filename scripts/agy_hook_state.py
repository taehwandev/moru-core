"""Per-conversation state for the Antigravity hook adapter: identity, delivery markers and round counters.

State lives under MARKER_DIR, or in the judge service when one is configured, so the session being checked
cannot read or edit what it is checked against.
"""

from __future__ import annotations

import hashlib
import json
import os
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


def already_delivered(conversation: str, text: str, kind: str = "route") -> bool:
    """Whether this conversation already holds exactly this text; record it if not.

    The shared route cache only exists once a project has run a hook, so a new
    workspace would otherwise be re-sent the same text on every model call.
    """

    safe = "".join(ch for ch in conversation if ch.isalnum() or ch in "-_")
    if not safe:
        return False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    marker = MARKER_DIR / f"{safe}.{kind}.digest"
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
