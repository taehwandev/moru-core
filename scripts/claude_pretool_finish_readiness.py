"""Refuse premature finish calls before they mutate the run's checkpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from agent_finish_retrospective_default import RETROSPECTIVE_GATE, retrospective_left_to_finish
from agent_gate_evidence import merge_gate_evidence_from_ledger
from agent_run_registry import registered_run
from claude_bash_readonly import _launcher_hook_tokens


# Finish derives these itself; requiring their ledger entries here would deadlock closure.
_FINISH_OWNED_GATES = frozenset({"finish", "commit readiness", "request intake"})


def finish_readiness_denial(
    tokens: list[str],
    cwd: Path,
    session_id: str,
    evidence_reader: Callable[[Path, str], Path | None],
) -> str:
    command = _launcher_hook_tokens(tokens)
    # The executable shebang form includes the interpreter in its normalized argv.
    if len(command) > 2 and Path(command[1]).name == "agent-hook.py":
        command = command[1:]
    if len(command) < 2 or command[1] != "finish" or {"--help", "-h"} & set(command):
        return ""

    project = cwd
    evidence_path = None
    for index, token in enumerate(command[2:], start=2):
        name, separator, inline = token.partition("=")
        if name not in {"--project", "--evidence"}:
            continue
        value = inline if separator else command[index + 1] if index + 1 < len(command) else ""
        if not value or value.startswith("--"):
            return ""  # argparse owns invalid invocations; do not guess their target.
        path = Path(value).expanduser()
        path = path if path.is_absolute() else cwd / path
        if name == "--project":
            project = path.resolve()
        else:
            evidence_path = path.resolve()
    evidence_path = evidence_path or evidence_reader(project, session_id)
    if evidence_path is None:
        return ""  # Entry/session validation still belongs to the hook.

    try:
        preflight = json.loads(evidence_path.read_text(encoding="utf-8"))
        run_id = str(preflight.get("agent_run_id") or "").strip()
        run = registered_run(project, evidence_path, run_id=run_id) if run_id else None
        # Finish validates transfer receipts and diagnoses superseded runs before gates.
        if isinstance(run, dict) and (
            isinstance(run.get("cancellation"), dict)
            or (run.get("state") == "cancelled" and run.get("superseded_by"))
        ):
            return ""
        route = preflight["route"]
        gates = route["gates"]
        if not isinstance(gates, list) or not all(isinstance(gate, str) for gate in gates):
            raise ValueError("invalid route gates")
        evidence, diagnostics = merge_gate_evidence_from_ledger(route=route, evidence_path=evidence_path)
        remaining = [gate for gate in gates if gate not in _FINISH_OWNED_GATES and not evidence.get(gate)]
        # Finish records the default retrospective only when the agent recorded none.
        if RETROSPECTIVE_GATE in remaining and retrospective_left_to_finish(evidence, diagnostics):
            remaining.remove(RETROSPECTIVE_GATE)
        if diagnostics["warnings"]:
            raise ValueError("unreadable gate ledger")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return (
            "Moru lifecycle: finish prerequisites cannot be read. Inspect the bound run with "
            "gate-batch --template and correct its evidence before finish."
        )
    if remaining:
        return (
            f"Moru lifecycle: finish must wait for successful gate evidence: {remaining}. "
            "A failed gate-record command supplies no evidence. Correct that command and inspect "
            "its successful Remaining route gates result before finish; no finish was executed."
        )
    return ""
