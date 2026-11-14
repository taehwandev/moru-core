#!/usr/bin/env python3
"""agy PreInvocation hook: hand the model its run's unread required docs.

Owner: delivery of required docs on Antigravity (agy), which has no file-edit
gate to carry them. Allowed imports: the standard library, agent_required_doc_delivery
and agent_runtime_session. Forbidden: blocking the turn, writing outside the run's
delivery marker. Callers/tests: `agy_hook_adapter.pre_invocation` (via the durable
`moru` hook in `~/.gemini/config/hooks.json`, installed by `support.agy_setup`);
`tests/test_agy_required_docs_hook.py`.
Verification: that test module; contract captured from agy 1.x on 2026-11-05
(stdin `conversationId`, `workspacePaths`, `transcriptPath`; stdout
`injectSteps[].systemMessage.systemMessage`, unknown fields make agy reject the hook).

agy runs this before every model call, so the docs arrive right after `start`
binds a run to the conversation, and again after a compaction: agy records one
as a `CHECKPOINT` step, which `agent_required_doc_delivery.is_compaction` knows.
A doc counts as read when a `read_file` call took the whole file since the last
compaction. agy keeps tool output in separate files, so this credits the call,
not its result; a failed read is therefore still credited. Any failure answers
`{}` so the turn is never blocked.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

READ_TOOLS = {"read_file", "view_file"}


def read_in_context(transcript: Path, rules: Path, texts: dict[str, str]) -> set[str]:
    """Docs a whole-file read call named since the last compaction."""

    if not texts or not transcript.is_file():
        return set()
    from agent_required_doc_delivery import is_compaction

    wanted = {_resolved(str(rules / doc)): doc for doc in texts}
    covered: set[str] = set()
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"tool_calls"' not in line and '"CHECKPOINT"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if is_compaction(row):
                covered.clear()
                continue
            for call in (row.get("tool_calls") or []) if isinstance(row, dict) else []:
                args = call.get("args") if isinstance(call, dict) else None
                if call.get("name") in READ_TOOLS and isinstance(args, dict) and set(args) == {"Path"}:
                    doc = wanted.get(_resolved(_unquoted(args["Path"])))
                    if doc and not _changed_since(rules / doc, row.get("created_at")):
                        covered.add(doc)
    return covered


def _unquoted(value: object) -> str:
    """The compact transcript stores each argument JSON-encoded: `"\\"/a/b\\""`."""

    text = str(value)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            decoded = json.loads(text)
        except ValueError:
            return text
        return decoded if isinstance(decoded, str) else text
    return text


def _resolved(path: str) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(path)


def _changed_since(path: Path, stamp: object) -> bool:
    """Whether the doc was written after the step that read it (a stale read proves nothing)."""

    try:
        read_at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
        return path.stat().st_mtime > read_at
    except (OSError, ValueError):
        return False


def respond(payload: dict, evidence_for=None) -> dict:
    """The hook's stdout object for one PreInvocation payload."""

    try:
        from agent_required_doc_delivery import delivery_text

        conversation = str(payload.get("conversationId") or "")
        workspaces = [str(path) for path in payload.get("workspacePaths") or []]
        if not conversation or not workspaces:
            return {}
        if evidence_for is None:
            import agent_runtime_session

            identity = {"runtime": "antigravity", "session_id": conversation}
            evidence_for = lambda project: agent_runtime_session.resolve_runtime_evidence(project, identity)  # noqa: E731
        text = ""
        for workspace in workspaces:
            edit = {"tool_name": "Edit", "cwd": workspace,
                    "transcript_path": str(payload.get("transcriptPath") or ""),
                    "tool_input": {"file_path": workspace}}
            text = delivery_text(edit, evidence_for, read_in_context)
            if text:
                break
    except Exception:  # noqa: BLE001 - delivery is advisory and must never block a turn
        return {}
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]} if text else {}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    sys.stdout.write(json.dumps(respond(payload if isinstance(payload, dict) else {})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
