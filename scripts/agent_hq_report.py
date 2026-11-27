"""Emit an atomic, bounded HQ finish report for HQ-originated runs.

Owner: Moru Core to Moru HQ finish-report bridge.
Allowed imports: standard library only.
Forbidden imports: lifecycle gates, workflow validators, provider runtimes.
Callers/tests: scripts/agent-finish-check.py, scripts/agent-preflight.py,
scripts/agent_work_continuity.py, scripts/agent_gate_reuse.py and the
`decision` CLI below; tests/test_agent_hq_report.py.
Verification: unit tests in tests/test_agent_hq_report.py.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 500
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_PRIMARY_SHRINK_FIELDS = ("evidence", "result", "decisionNeeded")
MAX_DECISION_OPTIONS = 3
MAX_OPTION_CHARS = 60
_FALLBACK_SHRINK_FIELDS = ("operatorLabel", "taskId", "projectId")


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _is_safe_run_id(run_id: str) -> bool:
    return bool(run_id and ".." not in run_id and _SAFE_RUN_ID_RE.fullmatch(run_id))


def hq_run_id_from_env(environ: Mapping[str, str] | None = None) -> str:
    """The HQ task id the dispatcher bound to this process, or ''."""
    value = _one_line((os.environ if environ is None else environ).get("MORU_HQ_RUN_ID"))
    return value if _is_safe_run_id(value) else ""


def _resolve_hq_run_id(preflight: Mapping[str, Any], environ: Mapping[str, str]) -> str | None:
    hq_run_id = _one_line(environ.get("MORU_HQ_RUN_ID")) or _one_line(preflight.get("hq_run_id"))
    if hq_run_id:
        return hq_run_id if _is_safe_run_id(hq_run_id) else None
    if _one_line(preflight.get("origin")).lower() == "hq":
        fallback = _one_line(preflight.get("agent_run_id"))
        return fallback if _is_safe_run_id(fallback) else None
    return None


def _build_result_text(preflight: Mapping[str, Any], environ: Mapping[str, str]) -> str:
    explicit = _one_line(environ.get("MORU_HQ_RESULT")) or _one_line(preflight.get("hq_result"))
    if explicit:
        return explicit
    intake = preflight.get("request_intake")
    if isinstance(intake, Mapping):
        summary = _one_line(intake.get("target_summary"))
        if summary:
            return summary
    route = preflight.get("route")
    if isinstance(route, Mapping):
        command = _one_line(route.get("command"))
        if command:
            return f"finish passed ({command})"
    return "finish passed"


def _build_evidence_text(passed_gates: list[str], environ: Mapping[str, str]) -> str:
    explicit = _one_line(environ.get("MORU_HQ_EVIDENCE"))
    if explicit:
        return explicit
    gates = [_one_line(gate) for gate in passed_gates if _one_line(gate)]
    return ", ".join(dict.fromkeys(gates)) if gates else "all required gates passed"


def _encode_compact(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _bound_payload(payload: dict[str, Any], max_bytes: int = MAX_REPORT_BYTES) -> bytes:
    encoded = _encode_compact(payload)
    while len(encoded) > max_bytes:
        field = max(
            _PRIMARY_SHRINK_FIELDS,
            key=lambda key: len(str(payload.get(key) or "")),
        )
        if not payload.get(field):
            field = max(
                _FALLBACK_SHRINK_FIELDS,
                key=lambda key: len(str(payload.get(key) or "")),
            )
            if not payload.get(field):
                break
        current = str(payload[field])
        overflow = len(encoded) - max_bytes
        drop = max(1, overflow // 3) if overflow > 6 else 1
        target_len = max(0, len(current) - drop)
        if target_len >= 4:
            payload[field] = current[: target_len - 3].rstrip() + "..."
        else:
            payload[field] = current[:target_len]
        encoded = _encode_compact(payload)
    return encoded


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    for candidate in (path.parent.parent.parent, path.parent.parent, path.parent, path):
        if candidate.is_symlink():
            raise OSError(f"Symbolic link detected in HQ report path: {candidate}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    temp_owned = False
    try:
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temp_owned = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, path)
    except BaseException:
        try:
            if temp_owned and temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise


def emit_hq_finish_report(
    *,
    project: Path,
    preflight: dict[str, Any],
    passed_gates: list[str],
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Write `<project>/.moru/hq/reports/<runId>.json` for HQ-originated runs."""

    environ = os.environ if env is None else env
    run_id = _resolve_hq_run_id(preflight, environ)
    if run_id is None:
        return None
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "runId": run_id,
        "projectId": (
            _one_line(environ.get("MORU_HQ_PROJECT_ID"))
            or _one_line(preflight.get("hq_project_id"))
            or _one_line(preflight.get("project_id"))
            or project.resolve().name
        ),
        "taskId": (
            _one_line(environ.get("MORU_HQ_TASK_ID"))
            or _one_line(preflight.get("hq_task_id"))
            or _one_line(preflight.get("task_id"))
            or _one_line(preflight.get("agent_run_id"))
            or run_id
        ),
        "operatorLabel": (
            _one_line(environ.get("MORU_HQ_OPERATOR_LABEL"))
            or _one_line(preflight.get("hq_operator_label"))
            or _one_line(preflight.get("operator_label"))
            or "moru-core"
        ),
        "status": "finished",
        "result": _build_result_text(preflight, environ),
        "evidence": _build_evidence_text(passed_gates, environ),
        "decisionNeeded": (
            _one_line(environ.get("MORU_HQ_DECISION_NEEDED"))
            or _one_line(preflight.get("hq_decision_needed"))
        ),
        "finishedAt": int(time.time() * 1000),
    }
    encoded = _bound_payload(payload, MAX_REPORT_BYTES)
    reports_dir = project / ".moru" / "hq" / "reports"
    target = reports_dir / f"{run_id}.json"
    if target.parent != reports_dir or target.name != f"{run_id}.json":
        return None
    _atomic_write_bytes(target, encoded)
    return target


def emit_hq_decision_report(
    *,
    project: Path,
    question: str,
    evidence: str,
    options: list[str],
    result: str = "",
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Write a `decision_needed` report when a worker stops on a contradiction.

    The worker stops instead of building on a guessed premise; the operator
    answers once. Returns None outside an HQ-dispatched process.
    """

    environ = os.environ if env is None else env
    run_id = hq_run_id_from_env(environ)
    question = _one_line(question)
    if not run_id or not question:
        return None
    choices = [_one_line(option)[:MAX_OPTION_CHARS] for option in options if _one_line(option)]
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "runId": run_id,
        "projectId": _one_line(environ.get("MORU_HQ_PROJECT_ID")) or project.resolve().name,
        "taskId": _one_line(environ.get("MORU_HQ_TASK_ID")) or run_id,
        "operatorLabel": _one_line(environ.get("MORU_HQ_OPERATOR_LABEL")) or "moru-core",
        "status": "decision_needed",
        "result": _one_line(result) or "stopped before building on a contradiction",
        "evidence": _one_line(evidence) or "contradiction found",
        "decisionNeeded": question,
        "decisionOptions": choices[:MAX_DECISION_OPTIONS],
        "finishedAt": int(time.time() * 1000),
    }
    encoded = _bound_payload(payload, MAX_REPORT_BYTES)
    while len(encoded) > MAX_REPORT_BYTES and payload["decisionOptions"]:
        payload["decisionOptions"].pop()
        encoded = _bound_payload(payload, MAX_REPORT_BYTES)
    if len(encoded) > MAX_REPORT_BYTES:
        return None
    reports_dir = project / ".moru" / "hq" / "reports"
    target = reports_dir / f"{run_id}.json"
    _atomic_write_bytes(target, encoded)
    return target


def emit_hq_report_for_finish(
    project: Path,
    preflight: dict[str, Any],
    gate_signals: list[dict[str, str]],
) -> Path | None:
    """Emit the HQ finish report from finish gate signals without failing finish."""

    passed_gates = list(dict.fromkeys(
        signal["gate"]
        for signal in gate_signals
        if signal.get("signal") == "SUCCESS" and signal.get("gate")
    ))
    try:
        report_path = emit_hq_finish_report(
            project=project,
            preflight=preflight,
            passed_gates=passed_gates,
        )
    except OSError as error:
        print(f"HQ finish report skipped: {error}", file=sys.stderr)
        return None
    if report_path is not None:
        print(f"HQ finish report: {report_path}")
    return report_path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Report an HQ decision the worker cannot make.")
    sub = parser.add_subparsers(dest="action", required=True)
    decision = sub.add_parser("decision", help="stop on a contradiction and ask the operator once")
    decision.add_argument("--project", required=True, type=Path)
    decision.add_argument("--question", required=True)
    decision.add_argument("--evidence", default="")
    decision.add_argument("--result", default="")
    decision.add_argument("--option", action="append", default=[])
    args = parser.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print("decision report refused: --project is not a directory", file=sys.stderr)
        return 2
    try:
        path = emit_hq_decision_report(project=project, question=args.question, evidence=args.evidence,
                                       options=args.option, result=args.result)
    except OSError as error:
        print(f"decision report failed: {error}", file=sys.stderr)
        return 1
    if path is None:
        print("not an HQ-dispatched run (MORU_HQ_RUN_ID unset or invalid) or empty question; "
              "record the blocker in the Moru checkpoint and ask the user instead", file=sys.stderr)
        return 2
    print(f"HQ decision report: {path}")
    print("Now checkpoint the Moru run with this blocker and end the turn; do not continue building.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
