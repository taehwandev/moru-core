"""The stop-time checks of the Antigravity hook adapter for pages routed through the web 3D skill."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from agy_hook_state import (
    MARKER_DIR, SCRIPTS, already_delivered, load_state, save_state, session_id, verification_state_path, workspace)

RUNTIME = "antigravity"


NOT_JUDGED_NOTE = (
    "No model judgement of the request's acceptance items is configured, so only the basic checks ran: the page loads, "
    "the main action responds, and pointer input reaches the controls and the scene. Everything else the request asks "
    "for is unverified by this check: look at the running page yourself and say plainly in your final report what "
    "you could not verify."
)


THREE_D_SKILL = "web-3d-interaction"


UNVERIFIED_REMINDER = (
    "Before you finish: say in your final report which user-visible properties (motion direction, "
    "framing of every camera mode, lighting, controls) you observed in a running page, and mark "
    "every one you did not observe as unverified. A build or unit tests do not cover them."
)


def routed_through_3d(payload: dict) -> bool:
    """Whether this conversation's Moru run was routed through the web 3D skill.

    Reads only the run's recorded route documents, never the transcript or the
    model's messages.
    """

    try:
        sys.path.insert(0, str(SCRIPTS))
        from agent_run_registry import RUN_STATES
        from agent_runtime_session import resolve_runtime_evidence

        evidence = resolve_runtime_evidence(
            Path(workspace(payload)), {"runtime": RUNTIME, "session_id": session_id(payload)},
            frozenset(RUN_STATES), latest_of_several=True,
        )
        if evidence is None:
            return False
        docs = json.loads(Path(evidence).read_text(encoding="utf-8")).get("route", {}).get("required_docs", [])
        return any(THREE_D_SKILL in str(doc) for doc in docs)
    except Exception:  # noqa: BLE001 - a reminder is advisory and must never trap a stop
        return False


def unverified_reminder(payload: dict, execution: int) -> dict:
    """Once per conversation, ask for an honest verification statement at stop."""

    if execution >= 1 or not routed_through_3d(payload):
        return {}
    if already_delivered(session_id(payload), UNVERIFIED_REMINDER, "stop"):
        return {}
    return {"decision": "continue", "reason": UNVERIFIED_REMINDER}


VERIFY_MAX_ROUNDS = 1


def verify_in_session(payload: dict) -> tuple[bool, dict]:
    """Run the independent page verifier from the stop hook and send failures back.

    Returns (ran, verdict). ``ran`` is False when verification could not run here
    (no built page, no browser, no judge), so the caller can fall back to the
    unverified-properties reminder. The checklist is derived once from the request
    and reused for the re-check, and at most VERIFY_MAX_ROUNDS fixes are requested.
    """

    state_path = verification_state_path(session_id(payload))
    if state_path is None or not routed_through_3d(payload):
        return False, {}
    try:
        sys.path.insert(0, str(SCRIPTS / "page_verify"))
        import verify

        project = Path(workspace(payload))
        if verify.find_dist(project) is None or not verify.can_observe():
            return False, {}
        state = load_state(state_path, "verify")
        digest = hashlib.sha256(str(payload.get("lastUserInput") or "").encode("utf-8")).hexdigest()
        if state.get("input") != digest:
            state = {"input": digest}  # a new request must not inherit the last one's checklist or rounds
        rounds = int(state.get("rounds", 0))
        if rounds >= VERIFY_MAX_ROUNDS + 1:
            return True, {}
        fingerprint = verify.project_fingerprint(project)
        if rounds and state.get("fingerprint") == fingerprint:
            # Nothing changed since the last check, so another one would only repeat it. Failures it found
            # and nobody fixed are still reported, once.
            held = verify.remaining_text(state.get("results") or [])
            if held and not state.get("reported"):
                state["reported"] = True
                save_state(state_path, "verify", state)
                return True, {"decision": "continue", "reason": held}
            return True, {}
        request = str(state.get("request") or payload.get("lastUserInput") or "")
        out = MARKER_DIR / "verify" / (state_path.stem.split(".")[0]) / f"round{rounds}"
        try:
            items, results = verify.verify_project(project, request, out, checklist=state.get("checklist"))
        finally:
            if os.environ.get("MORU_VERIFY_JUDGE_URL"):
                # With a judge service the checklist and the evidence live there. Leaving them in this home would
                # let the checked session read what it is checked against (one run did, right after a failure).
                shutil.rmtree(out, ignore_errors=True)
        # Before the last allowed check the failures go back for a fix; after it they are reported, once.
        last_check = rounds >= VERIFY_MAX_ROUNDS
        feedback = verify.remaining_text(results) if last_check else verify.feedback_text(results)
        if not verify.judge_configured():
            feedback = (feedback + "\n\n" if feedback else "") + NOT_JUDGED_NOTE if (
                feedback or not already_delivered(session_id(payload), NOT_JUDGED_NOTE, "not-judged")) else ""
        kept = [{k: r.get(k) for k in ("id", "claim", "verdict", "reason")} for r in results]
        save_state(state_path, "verify", {"input": digest, "rounds": rounds + 1, "request": request, "checklist": items,
                                          "fingerprint": fingerprint, "results": kept,
                                          "reported": bool(feedback and last_check),
                                          "last": [{"id": r["id"], "verdict": r["verdict"]} for r in results]})
        return True, ({"decision": "continue", "reason": feedback} if feedback else {})
    except Exception as error:  # noqa: BLE001 - verification is advisory and must never trap a stop
        try:  # a silent fail-open hides why a fix loop ended, so leave the reason beside the state
            MARKER_DIR.mkdir(parents=True, exist_ok=True)
            state_path.with_suffix(".error").write_text(f"{type(error).__name__}: {str(error)[:400]}", encoding="utf-8")
        except OSError:
            pass
        # An independent check that could not run is not a pass: say so once, so it cannot end the run unseen.
        crash = f"{type(error).__name__}: {str(error)[:200]}"
        if not already_delivered(session_id(payload), crash, "verify-crash"):
            return True, {"decision": "continue", "reason": (
                f"The independent check of the page could not run ({crash}). Nothing was independently verified: "
                "do not call the page verified, and say so plainly in your final report.")}
        return False, {}
