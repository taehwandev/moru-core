#!/usr/bin/env python3
"""Adapt Antigravity lifecycle hooks to Moru's shared gates.

Antigravity runs a hook command with a camelCase JSON payload on stdin and reads
a JSON verdict from stdout. Moru's gates speak Claude Code's payload, so this
module only translates; every policy decision stays in the gate it calls.

Events:
- ``pre-invocation``: deliver the advisory workflow route and the request's task
  guidance once per user input, plus any unread ``required_docs`` for an active
  run (and again after a compaction ``CHECKPOINT``), as system messages.
- ``pre-tool``: run the shared pre-mutation gate for run_command/write_file/
  edit_file. A deny or ask becomes advisory context unless MORU_AGY_GATE=strict.
- ``stop``: run the shared Stop gate; its block becomes ``continue`` once. For a session routed
  through the web 3D skill it then runs the independent page verifier and sends failures back
  for a fix (at most twice); when the verifier cannot run it reminds once to mark unobserved
  properties as unverified.

Every failure allows: a gate that traps a session is worse than one that misses.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agy_hook_state import already_delivered, continuations_for, count_continuation, has_delivered, session_id, workspace
from agy_hook_verify import unverified_reminder, verify_in_session
import agy_required_docs_hook

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = "antigravity"
EDIT_TOOLS = {"write_file": "Write", "edit_file": "Edit"}
UNCHANGED_NOTE = "unchanged since this session already received it"
TIMEOUT_SECONDS = 25


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

        return verify.can_observe()
    except Exception:  # noqa: BLE001 - a missing check just means no notice
        return False


_AUTOLOADED_OR_FOREIGN_INSTRUCTIONS = frozenset({"AGENTS.md", "GEMINI.md", "CLAUDE.md", "CODEX.md"})
_OPEN_INSTRUCTIONS_STEP = "- Open the selected project's runtime instruction files before project work."


def _compaction_count(payload: dict) -> int:
    transcript = Path(str(payload.get("transcriptPath") or ""))
    if not transcript.is_file():
        return 0
    try:
        from agent_required_doc_delivery import is_compaction

        with transcript.open(encoding="utf-8", errors="replace") as handle:
            return sum(
                1 for line in handle
                if '"CHECKPOINT"' in line and is_compaction(parse_json(line))
            )
    except Exception:  # noqa: BLE001 - transcript inspection is best-effort
        return 0


def _resolved_dir(raw: str) -> Path | None:
    try:
        return Path(raw).expanduser().resolve() if raw else None
    except (OSError, RuntimeError):
        return None


def _trim_autoloaded_workspace_entry(entry: str, payload: dict) -> str:
    """Drop redundant instruction-read prompts when AGY already auto-loaded the workspace AGENTS.md."""

    lines = entry.splitlines()
    selected = next((line[9:].strip() for line in lines if line.startswith("project: ")), "")
    selected_dir = _resolved_dir(selected)
    workspaces = {d for item in (payload.get("workspacePaths") or []) if (d := _resolved_dir(str(item)))}
    if selected_dir is None or selected_dir not in workspaces or not (selected_dir / "AGENTS.md").is_file():
        return entry
    kept: list[str] = []
    index, saw_instructions, remaining = 0, False, []
    while index < len(lines):
        if lines[index] == "instruction_files:":
            saw_instructions = True
            index += 1
            while index < len(lines) and lines[index].startswith("- "):
                if lines[index][2:].strip() not in _AUTOLOADED_OR_FOREIGN_INSTRUCTIONS:
                    remaining.append(lines[index])
                index += 1
            if remaining:
                kept.extend(["instruction_files:", *remaining])
            continue
        if saw_instructions and not remaining and lines[index] == _OPEN_INSTRUCTIONS_STEP:
            index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept)


def _prompt_guidance_steps(payload: dict) -> list[dict]:
    sid = session_id(payload)
    cwd = workspace(payload)
    prompt = str(payload.get("lastUserInput") or "")
    input_key = f"{cwd}\0{_compaction_count(payload)}\0{prompt}"
    # Antigravity fires PreInvocation before every model step in a turn, not only
    # once on UserPromptSubmit. Short-circuit before spawning subprocesses once
    # this exact (workspace, compaction-epoch, user-input) was already processed.
    if sid and prompt.strip() and has_delivered(sid, input_key, "input"):
        return []
    claude = {"session_id": sid, "cwd": cwd, "prompt": prompt, "hook_event_name": "UserPromptSubmit"}
    route = run_script("workflow.py", ["route", "triage", "--advisory", "--hook-stdin"], claude, cwd,
                       {"SPILL_AI_TOOL": RUNTIME}).strip()
    if not route:
        return []
    unchanged = UNCHANGED_NOTE in route
    if unchanged and not prompt.strip():
        return []
    entry = run_script("agent-entry.py", ["--runtime", RUNTIME, "--cwd", cwd, "--no-default-search-roots",
                                          "--request", prompt], "", cwd).strip()
    if entry:
        entry = _trim_autoloaded_workspace_entry(entry, payload)
    if sid and prompt.strip():
        already_delivered(sid, input_key, "input")
    base = "" if unchanged else route
    text = base if not entry else f"{base}\n\n## Project entry\n{entry}".strip()
    if not text:
        return []
    if "web-3d-interaction" in entry and independent_check_available():
        text += "\n\n" + INDEPENDENT_CHECK_NOTICE
    if already_delivered(sid, text):
        return []
    return [{"systemMessage": {"systemMessage": text}}]


def _required_docs_steps(payload: dict) -> list[dict]:
    try:
        answer = agy_required_docs_hook.respond(payload)
    except Exception:  # noqa: BLE001 - required-doc delivery must never break route delivery
        return []
    steps = answer.get("injectSteps") if isinstance(answer, dict) else None
    return steps if isinstance(steps, list) else []


def pre_invocation(payload: dict) -> dict:
    try:
        guidance = _prompt_guidance_steps(payload)
    except Exception:  # noqa: BLE001 - fail open so required-doc delivery still runs
        guidance = []
    steps = [*guidance, *_required_docs_steps(payload)]
    return {"injectSteps": steps} if steps else {}


def partial_read_note(args: dict, conversation: str) -> str:
    """Tell the agent once when it asks for only part of a skill document.

    A skill is guidance to be read to its end; a model that picks a round line
    range silently skips whatever follows it. Only the request and the file's
    line count are compared, never the file's meaning.
    """

    path = Path(str(args.get("Path") or args.get("AbsolutePath") or ""))
    if path.name != "SKILL.md":
        return ""
    try:
        total = len(path.read_text(encoding="utf-8").splitlines())
        first, last = int(args.get("StartLine") or 1), int(args.get("EndLine") or total)
    except (OSError, ValueError):
        return ""
    if first <= 1 and last >= total:
        return ""
    note = (f"{path.name} in {path.parent.name} has {total} lines and you asked for {first}-{last}. A skill is "
            f"guidance to read to its end: read lines {last + 1}-{total} (or the whole file) before relying on it.")
    return "" if already_delivered(conversation, note, "partial-read") else note


def pre_tool(payload: dict) -> dict:
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    name = str(call.get("name") or "")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    if name == "read_file":
        note = partial_read_note(args, session_id(payload))
        return {"decision": "allow", "reason": note} if note else {"decision": "allow"}
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
