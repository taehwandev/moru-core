"""The stop-time checks of the Antigravity hook adapter for pages routed through the web 3D skill."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
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

_NON_INTERACTIVE_WORK_RE = re.compile(
    r"\b(headless|film|movie|cinematic|cutscene|short film|render(?:ing|er|ed)?|stills?|frames?|"
    r"mp4|ffmpeg|video|blender|bpy|glb|gltf|fbx|mesh|rig(?:ging)?|armature|asset(?:s)?|prop(?:s)?|"
    r"texture(?:s)?|material(?:s)?|choreo|choreography|storyboard|shot(?:s)?|shotlist|offline)\b|"
    r"\.(?:blend|glb|gltf|fbx|mp4)\b",
    re.IGNORECASE,
)
_INTERACTIVE_UI_RE = re.compile(
    r"\b(ui|hud|button|buttons|control|controls|menu|modal|dialog|panel|toolbar|sidebar|form|"
    r"slider|toggle|click|interactive|orbit|zoom|camera controls|page shell|index\.html|"
    r"landing page|web app|webapp|dashboard|overlay)\b|"
    r"(?:버튼|메뉴|모달|다이얼로그|패널|툴바|사이드바|슬라이더|토글|클릭|컨트롤|화면|레이아웃|오버레이|인터랙티브|웹\s*앱)",
    re.IGNORECASE,
)
_PAGE_SHELL_OUTSIDE_RE = re.compile(
    r"(?:do\s+not\s+touch|outside\s+(?:your\s+|the\s+agent'?s\s+)?owned\s+paths?|not\s+owned)[^\n]*"
    r"(?:index\.html|page\s+shell|src/ui|ui\s+shell|controls)",
    re.IGNORECASE,
)
_OWNED_SCOPE_RE = re.compile(r"(?:you\s+own|owned\s+paths?)\s*:\s*([^\n]+)", re.IGNORECASE)
_PAGE_SHELL_EXTENSIONS = frozenset({
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx", ".vue", ".svelte",
})
_WEB_SOURCE_EXTENSIONS = frozenset({".js", ".ts", ".mjs", ".cjs"})
_NON_SHELL_ROOTS = frozenset({
    "tools", "blender", "_shots", "shots", "renders", "output",
    "tests", "test", "docs", "orchestra",
})


def _is_page_shell_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    path = Path(normalized)
    suffix = path.suffix.lower()
    if suffix in _PAGE_SHELL_EXTENSIONS:
        return True
    parts = [part.lower() for part in path.parts]
    if parts and parts[0] in _NON_SHELL_ROOTS:
        return False
    return suffix in _WEB_SOURCE_EXTENSIONS


def _explicit_owned_paths(request: str) -> list[str]:
    if not request:
        return []
    match = _OWNED_SCOPE_RE.search(request)
    if not match:
        return []
    owned_text = match.group(1)
    # Stop before sentence breaks or prohibition clauses (e.g. ". do not touch index.html")
    # so excluded/prohibited paths are never misparsed as owned paths.
    owned_text = re.split(
        r"(?:\.\s+|;|\b(?:do\s+not|don't|never|outside|except|excluding)\b)",
        owned_text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tokens = [
        token.strip(" ,.;:`'\"")
        for token in re.split(r"[\s,]+", owned_text)
        if token.strip(" ,.;:`'\"")
    ]
    return [token for token in tokens if "/" in token or "." in token]


def _path_matches_owned_scope(rel_path: str, owned_tokens: list[str]) -> bool:
    normalized = rel_path.replace("\\", "/").lstrip("./")
    for raw in owned_tokens:
        token = raw.replace("\\", "/").lstrip("./").rstrip("*")
        if not token:
            continue
        if token.endswith("/"):
            if normalized.startswith(token):
                return True
        elif normalized == token or normalized.startswith(token + "/"):
            return True
    return False


def _latest_commit_paths(project: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "-m", "--first-parent", "HEAD"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _changed_repo_paths(project: Path) -> list[str] | None:
    if not project.is_dir() or not (project / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if len(line) < 4:
            continue
        text = line[3:].strip()
        if " -> " in text:
            text = text.split(" -> ", 1)[1].strip()
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            text = text[1:-1]
        if text:
            paths.append(text)
    if not paths:
        return _latest_commit_paths(project)
    return paths


def _out_of_scope_shell_paths(changed: list[str] | None, owned: list[str]) -> list[str]:
    if not changed or not owned:
        return []
    return [
        item for item in changed
        if _is_page_shell_path(item) and not _path_matches_owned_scope(item, owned)
    ]


def _page_shell_excluded_by_request(request: str) -> bool:
    if not request:
        return False
    if _PAGE_SHELL_OUTSIDE_RE.search(request):
        return True
    path_like = _explicit_owned_paths(request)
    if not path_like:
        return False
    return not any(
        _is_page_shell_path(token.rstrip("/*"))
        or Path(token.rstrip("/*")).suffix.lower() in _PAGE_SHELL_EXTENSIONS
        or "index.html" in token.lower()
        or "/ui" in token.lower()
        or token.lower().startswith("ui/")
        for token in path_like
    )


_APP_ENTRY_STEMS = frozenset({"index", "main", "app"})


def _is_explicit_shell_or_entry(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    path = Path(normalized)
    suffix = path.suffix.lower()
    if suffix in _PAGE_SHELL_EXTENSIONS:
        return True
    parts = [part.lower() for part in path.parts]
    if parts and parts[0] in _NON_SHELL_ROOTS:
        return False
    return suffix in _WEB_SOURCE_EXTENSIONS and path.stem.lower() in _APP_ENTRY_STEMS


def _should_verify_interactive_page(project: Path, request: str) -> bool:
    """Decide from changed paths first; always verify out-of-scope page-shell changes."""

    changed = _changed_repo_paths(project)
    owned = _explicit_owned_paths(request)
    shell_excluded = _page_shell_excluded_by_request(request)
    if changed:
        shell_changed = [item for item in changed if _is_page_shell_path(item)]
        if not shell_changed:
            return False
        # Any page-shell change outside explicitly owned paths is an ownership
        # violation and must still be verified rather than silently skipped.
        if owned:
            out_of_scope = _out_of_scope_shell_paths(changed, owned)
            if out_of_scope:
                return True
            owned_shell = [item for item in shell_changed if _path_matches_owned_scope(item, owned)]
            if shell_excluded:
                return any(_is_explicit_shell_or_entry(item) for item in owned_shell)
            return True
        if shell_excluded:
            return any(_is_explicit_shell_or_entry(item) for item in shell_changed)
        return True
    if shell_excluded:
        return False
    if request and _NON_INTERACTIVE_WORK_RE.search(request) and not _INTERACTIVE_UI_RE.search(request):
        return False
    return True


def _observer_error_from_results(verify_module, results: list[dict]) -> str:
    helper = getattr(verify_module, "observer_error_reason", None)
    if callable(helper):
        return str(helper(results) or "")
    for row in results:
        if row.get("verdict") == "fail" and row.get("basis") == "unverified":
            reason = str(row.get("reason") or "")
            if "observer failed:" in reason:
                return reason
    return ""


def _reported_unverified_from_results(verify_module, results: list[dict]) -> str:
    helper = getattr(verify_module, "reported_unverified_text", None)
    if callable(helper):
        return str(helper(results) or "")
    items = [
        row for row in results
        if row.get("verdict") == "fail" and row.get("basis") == "unverified"
    ]
    if not items:
        return ""
    lines = [
        f"- {row['id']}: {row.get('claim', '')} ({row.get('reason', 'unverified')})".strip()
        for row in items
    ]
    return (
        "Reported unverified items (not blocking):\n"
        + "\n".join(lines)
        + "\nDo not claim these items passed; state them plainly as unverified in your final report."
    )


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
        initial_request = str(payload.get("lastUserInput") or "")
        if not _should_verify_interactive_page(project, initial_request):
            return True, {}
        out_of_scope_shell = _out_of_scope_shell_paths(
            _changed_repo_paths(project), _explicit_owned_paths(initial_request)
        )
        if verify.find_dist(project) is None or not verify.can_observe():
            if out_of_scope_shell:
                notice = (
                    "Out-of-scope page-shell file(s) changed outside owned paths: "
                    + ", ".join(out_of_scope_shell)
                    + ". Verify or revert these changes and report them explicitly."
                )
                if not already_delivered(session_id(payload), notice, "verify-scope"):
                    return True, {"decision": "continue", "reason": notice}
            return False, {}
        state = load_state(state_path, "verify")
        digest = hashlib.sha256(initial_request.encode("utf-8")).hexdigest()
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
        request = str(state.get("request") or initial_request)
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
        non_blocking_report = False
        if not feedback:
            obs_err = _observer_error_from_results(verify, results)
            if obs_err:
                non_blocking_report = True
                if not already_delivered(session_id(payload), obs_err, "verify-crash"):
                    feedback = (
                        f"The independent check of the page could not verify ({obs_err}). "
                        "Nothing was independently verified: do not call the page verified, "
                        "and say so plainly in your final report."
                    )
            else:
                unverified_note = _reported_unverified_from_results(verify, results)
                if unverified_note:
                    non_blocking_report = True
                    if not already_delivered(session_id(payload), unverified_note, "verify-unverified"):
                        feedback = unverified_note
        if not verify.judge_configured():
            feedback = (feedback + "\n\n" if feedback else "") + NOT_JUDGED_NOTE if (
                feedback or not already_delivered(session_id(payload), NOT_JUDGED_NOTE, "not-judged")) else ""
        kept = [{k: r.get(k) for k in ("id", "claim", "verdict", "basis", "reason")} for r in results]
        next_rounds = VERIFY_MAX_ROUNDS + 1 if non_blocking_report else rounds + 1
        save_state(state_path, "verify", {"input": digest, "rounds": next_rounds, "request": request, "checklist": items,
                                          "fingerprint": fingerprint, "results": kept,
                                          "reported": bool(feedback and (last_check or non_blocking_report)),
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
