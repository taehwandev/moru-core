#!/usr/bin/env python3
"""Adapt Antigravity lifecycle hooks to Moru's shared gates.

Antigravity runs a hook command with a camelCase JSON payload on stdin and reads
a JSON verdict from stdout. Moru's gates speak Claude Code's payload, so this
module only translates; every policy decision stays in the gate it calls.

Events:
- ``pre-invocation``: deliver the advisory workflow route and the request's task
  guidance once per user input, as a system message.
- ``pre-tool``: run the shared pre-mutation gate for run_command/write_file/
  edit_file. A deny or ask becomes advisory context unless MORU_AGY_GATE=strict.
- ``stop``: run the shared Stop gate; its block becomes ``continue`` once. For a session routed
  through the web 3D skill it then runs the independent page verifier and sends failures back
  for a fix (at most twice); when the verifier cannot run it reminds once to mark unobserved
  properties as unverified.

Every failure allows: a gate that traps a session is worse than one that misses.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = "antigravity"
EDIT_TOOLS = {"write_file": "Write", "edit_file": "Edit"}
UNCHANGED_NOTE = "unchanged since this session already received it"
TIMEOUT_SECONDS = 25


def workspace(payload: dict) -> str:
    paths = payload.get("workspacePaths")
    if isinstance(paths, list) and paths:
        return str(paths[0])
    return os.getcwd()


def session_id(payload: dict) -> str:
    return str(payload.get("conversationId") or "")


def run_script(name: str, args: list[str], stdin: dict | str, cwd: str, env: dict | None = None) -> str:
    text = stdin if isinstance(stdin, str) else json.dumps(stdin)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        input=text, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        cwd=cwd if Path(cwd).is_dir() else None, env={**os.environ, **(env or {})}, check=False,
    )
    return result.stdout


def parse_json(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


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


INDEPENDENT_CHECK_NOTICE = (
    "When you stop, an independent check opens the finished page in a real browser, uses its main action, drags and "
    "scrolls over the scene, and sends failures back. Before you finish, look at the running page yourself once, in its "
    "default view and while the main action runs, as the UI visual verification skill asks; a single pass is enough. "
    "Say in your final report what you could not verify."
)


def independent_check_available() -> bool:
    """Only promise the independent check when this session can actually run it."""

    try:
        sys.path.insert(0, str(SCRIPTS / "page_verify"))
        import verify

        return verify.can_judge() and verify.can_observe()
    except Exception:  # noqa: BLE001 - a missing check just means no notice
        return False


def pre_invocation(payload: dict) -> dict:
    cwd = workspace(payload)
    prompt = str(payload.get("lastUserInput") or "")
    claude = {"session_id": session_id(payload), "cwd": cwd, "prompt": prompt,
              "hook_event_name": "UserPromptSubmit"}
    route = run_script("workflow.py", ["route", "triage", "--advisory", "--hook-stdin"], claude, cwd,
                       {"SPILL_AI_TOOL": RUNTIME}).strip()
    if not route:
        return {}
    unchanged = UNCHANGED_NOTE in route
    # An unchanged route says nothing about a new request: a conversation can move to a different kind of
    # work, so project entry is recomputed once per distinct user input and still deduplicated below.
    if unchanged and (not prompt.strip() or already_delivered(session_id(payload), prompt, "input")):
        return {}
    entry = run_script("agent-entry.py", ["--runtime", RUNTIME, "--cwd", cwd, "--no-default-search-roots",
                                          "--request", prompt], "", cwd).strip()
    base = "" if unchanged else route
    text = base if not entry else f"{base}\n\n## Project entry\n{entry}".strip()
    if not text:
        return {}
    if "web-3d-interaction" in entry and independent_check_available():
        text += "\n\n" + INDEPENDENT_CHECK_NOTICE
    if already_delivered(session_id(payload), text):
        return {}
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}


def pre_tool(payload: dict) -> dict:
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    name = str(call.get("name") or "")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    if name == "run_command":
        tool, tool_input = "Bash", {"command": str(args.get("CommandLine") or "")}
    elif name in EDIT_TOOLS:
        path = args.get("Path") or args.get("TargetFile") or ""
        tool, tool_input = EDIT_TOOLS[name], {"file_path": str(path)}
    else:
        return {"decision": "allow"}
    cwd = workspace(payload)
    claude = {"session_id": session_id(payload), "cwd": cwd, "tool_name": tool, "tool_input": tool_input,
              "hook_event_name": "PreToolUse"}
    out = parse_json(run_script("claude_pretool_gate.py", [], claude, cwd, {"MORU_PRETOOL_RUNTIME": RUNTIME}))
    specific = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
    decision = specific.get("permissionDecision")
    reason = str(specific.get("permissionDecisionReason") or specific.get("additionalContext") or "")
    if decision in {"deny", "ask"}:
        if os.environ.get("MORU_AGY_GATE", "").strip().lower() == "strict":
            return {"decision": "deny", "reason": reason or "Blocked by the Moru workflow gate."}
        return {"decision": "allow", "reason": f"Moru workflow note (not enforced): {reason}".strip()}
    verdict = {"decision": "allow"}
    if reason:
        verdict["reason"] = reason
    return verdict


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


VERIFY_MAX_ROUNDS = 1


def verification_state_path(conversation: str) -> Path | None:
    safe = "".join(ch for ch in conversation if ch.isalnum() or ch in "-_")
    return MARKER_DIR / f"{safe}.verify.json" if safe else None


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
        if verify.find_dist(project) is None or not verify.can_judge():
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
        items, results = verify.verify_project(project, request, out, checklist=state.get("checklist"))
        # Before the last allowed check the failures go back for a fix; after it they are reported, once.
        last_check = rounds >= VERIFY_MAX_ROUNDS
        feedback = verify.remaining_text(results) if last_check else verify.feedback_text(results)
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


def stop(payload: dict) -> dict:
    cwd = workspace(payload)
    try:
        execution = int(payload.get("executionNum") or 0)
    except (TypeError, ValueError):
        execution = 0
    counter_path, counter = continuations_for(payload)
    claude = {"session_id": session_id(payload), "cwd": cwd, "hook_event_name": "Stop",
              "stop_hook_active": execution >= 1 or int(counter.get("continuations", 0)) >= 1}
    out = parse_json(run_script("claude_stop_gate.py", [], claude, cwd))
    if out.get("decision") == "block":
        count_continuation(counter_path, counter)
        return {"decision": "continue", "reason": str(out.get("reason") or "")}
    ran, verdict = verify_in_session(payload)
    if not ran:
        verdict = unverified_reminder(payload, execution)
    if verdict.get("decision") == "continue":
        count_continuation(counter_path, counter)
    return verdict


HANDLERS = {"pre-invocation": pre_invocation, "pre-tool": pre_tool, "stop": stop}
FAIL_OPEN = {"pre-invocation": {}, "pre-tool": {"decision": "allow"}, "stop": {}}


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else ""
    if event not in HANDLERS:
        return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        verdict = HANDLERS[event](payload if isinstance(payload, dict) else {})
    except Exception:  # noqa: BLE001 - a failing adapter must never trap the session
        verdict = FAIL_OPEN[event]
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
