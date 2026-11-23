"""Select the executing tool before reading its session ID.

Owner: runtime identity selection. Allowed imports: OS metadata and run owner.
Forbidden imports: registry, lifecycle writers and tool adapters.
Callers/tests: session, preflight and Spill. Verification: test_nested_runtime_start.
"""
from __future__ import annotations

import os
from typing import Mapping

import agent_run_owner


STRICT_SESSION_ENV_VARS = (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"))
SESSION_ENV_VARS = (*STRICT_SESSION_ENV_VARS, ("antigravity", "ANTIGRAVITY_CONVERSATION_ID"))


def detect_runtime(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return the tool and only its own ID. Child tool shells inherit parent IDs.

    Prefer the nearest recognizable runtime for conflicting signals. If ancestry
    is hidden, a launcher can declare the child with MORU_AI_TOOL. Native child
    IDs take precedence over the Claude ID commonly exported to child shells.
    A marker-only AGY process can span separate hooks without a conversation ID:
    its PID plus birth time identifies that invocation without borrowing a parent ID.
    """
    values = os.environ if env is None else env
    ids = {name: values.get(key, "").strip() for name, key in SESSION_ENV_VARS}
    explicit = values.get("MORU_AI_TOOL", "").strip().lower()
    if explicit == "agy":
        explicit = "antigravity"
    agy_marker = any(values.get(key, "").strip() for key in
                     ("ANTIGRAVITY_AGENT", "ANTIGRAVITY_CLI_ALIAS", "ANTIGRAVITY_TRAJECTORY_ID"))
    codex_marker = any(values.get(key, "").strip() for key in ("CODEX_SANDBOX", "CODEX_CI"))
    # A supplied env is an offline description, independent of this process tree.
    if env is None:
        ancestor, process_id = agent_run_owner.runtime_ancestor()
        if ancestor and (ids.get(ancestor) or ancestor == "antigravity"):
            return ancestor, ids[ancestor] or process_id
    if explicit in (*ids, "openai", "gemini"):
        return explicit, ids.get(explicit, "")
    if ids["antigravity"]:
        return "antigravity", ids["antigravity"]
    if ids["codex"]:
        return "codex", ids["codex"]
    if agy_marker and not codex_marker:
        return "antigravity", ""
    if ids["claude"]:
        return "claude", ids["claude"]
    if codex_marker:
        return "codex", ""
    if values.get("GEMINI_CLI", "").strip():
        return "gemini", ""
    for key in ("SPILL_TOKEN_USAGE_AI_TOOL", "SPILL_AI_TOOL"):
        label = values.get(key, "").strip().lower()
        if label in (*ids, "agy", "gemini", "openai"):
            return ("antigravity" if label == "agy" else label), ""
    return "", ""
