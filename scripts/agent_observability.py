"""Read-only content-free status and run-efficiency trend API for Moru Core."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import statistics
from typing import Any, Iterable
import uuid

from agent_ipc import events_path
from agent_run_registry import registry_path
from agent_scheduler import scheduler_path
from agent_execution_capsule_state import read_json_object
from agent_state_lock import project_state_lock, state_lock
from agent_os_api import api_contract_manifest, runtime_adapter_catalog
from support.global_state import project_state_dir_target


API_VERSION = 2
DEFAULT_SPILL_DB = Path.home() / "Library" / "Application Support" / "Spill" / "token-metering" / "events.sqlite3"
DEFAULT_CODEX_DB = Path.home() / ".codex" / "state_5.sqlite"


def status_snapshot(project: Path) -> dict[str, Any]:
    project = project.resolve()
    captured_at = datetime.now(timezone.utc).isoformat()
    with project_state_lock(project):
        with state_lock(registry_path(project)):
            registry = read_json_object(registry_path(project))
        with state_lock(scheduler_path(project)):
            scheduler = read_json_object(scheduler_path(project))
        with state_lock(events_path(project)):
            events_payload = read_json_object(events_path(project))
    runs = registry.get("runs") if isinstance(registry.get("runs"), list) else []
    tasks = scheduler.get("tasks") if isinstance(scheduler.get("tasks"), list) else []
    events = events_payload.get("events") if isinstance(events_payload.get("events"), list) else []
    task_counts: dict[str, int] = {}
    for task in tasks:
        state = str(task.get("state") or "unknown")
        task_counts[state] = task_counts.get(state, 0) + 1
    event_counts: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "unknown")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    return {
        "api_version": API_VERSION, "snapshot_id": uuid.uuid4().hex, "captured_at": captured_at,
        "consistency": "project-state-lock", "api_contract": api_contract_manifest(),
        "runtime_adapters": runtime_adapter_catalog(),
        "active_runs": sum(run.get("state") in {"running", "paused"} for run in runs if isinstance(run, dict)),
        "task_counts": task_counts, "events": event_counts,
        "registry_present": registry_path(project).exists(), "scheduler_present": scheduler_path(project).exists(),
    }


def discover_governed_projects(workspace_root: Path | None = None) -> list[Path]:
    """Return local git repositories under ``workspace_root`` that contain ``.moru`` state."""
    root = (workspace_root or (Path.home() / "git")).expanduser().resolve()
    if not root.is_dir():
        return []
    return [
        c.resolve() for c in sorted(root.iterdir())
        if c.is_dir() and ((project_state_dir_target(c) / "runs").is_dir() or (project_state_dir_target(c) / "run-registry.json").is_file())
    ]


def efficiency_trend_snapshot(
    projects: Iterable[Path], *, spill_db: Path | None = None, codex_db: Path | None = None, month: str = ""
) -> dict[str, Any]:
    """Build a content-free cohort and rolling trend summary across Moru runs."""
    resolved_projects = [Path(project).expanduser().resolve() for project in projects]
    codex_threads = _load_codex_threads((codex_db or DEFAULT_CODEX_DB).expanduser())
    raw_runs = _collect_runs(resolved_projects)
    spill_ids = {run["spill_run_id"] for run in raw_runs if run["spill_run_id"]}
    spill_events = _load_spill_events((spill_db or DEFAULT_SPILL_DB).expanduser(), spill_ids)
    bound_runs = _bind_run_metrics(raw_runs, spill_events, codex_threads, month=month.strip())

    cohort_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    route_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    period_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    matched = [run for run in bound_runs if run["turns"] > 0]
    for run in matched:
        cohort_key = (run["runtime"], run["model"], run["reasoning_effort"], run["same_work_mode"])
        cohort_groups[cohort_key].append(run)
        route_groups[(run["route"], run["same_work_mode"])].append(run)
        period_groups[(run["period_bucket"], *cohort_key)].append(run)

    cohorts = [
        {"runtime": k[0], "model": k[1], "reasoning_effort": k[2], "same_work_mode": k[3], **_summarize_runs(v)}
        for k, v in sorted(cohort_groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    route_cohorts = [
        {"route": k[0], "same_work_mode": k[1], **_summarize_runs(v)}
        for k, v in sorted(route_groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    periods = [
        {"period": k[0], "runtime": k[1], "model": k[2], "reasoning_effort": k[3], "same_work_mode": k[4], **_summarize_runs(v)}
        for k, v in sorted(period_groups.items(), key=lambda item: (item[0][0], -len(item[1])))
    ]
    session_bound = [run for run in bound_runs if run["runtime"] and run["session_id"]]
    return {
        "schema_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
        "month_filter": month.strip() or "all", "project_count": len(resolved_projects),
        "total_runs": len(bound_runs), "session_bound_runs": len(session_bound),
        "spill_matched_runs": len(matched),
        "binding_coverage_ratio": round(len(matched) / len(session_bound), 4) if session_bound else 0.0,
        "fresh_runs": sum(1 for run in matched if run["same_work_mode"] == "fresh"),
        "continuation_runs": sum(1 for run in matched if run["same_work_mode"] == "continuation"),
        "cohorts": cohorts, "route_cohorts": route_cohorts, "period_trends": periods,
    }


def _collect_runs(projects: list[Path]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for project in projects:
        state_dir = project_state_dir_target(project)
        reg_runs = read_json_object(state_dir / "run-registry.json").get("runs")
        reg_by_id = {str(i.get("run_id")): i for i in (reg_runs if isinstance(reg_runs, list) else []) if isinstance(i, dict) and i.get("run_id")}
        runs_dir = state_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            preflight = read_json_object(run_dir / "preflight.json") if (run_dir / "preflight.json").is_file() else {}
            if not preflight:
                continue
            reg = reg_by_id.get(run_dir.name) or {}
            session = preflight.get("runtime_session") if isinstance(preflight.get("runtime_session"), dict) else {}
            runtime, session_id = str(session.get("runtime") or "").strip().lower(), str(session.get("session_id") or "").strip()
            if runtime == "agy":
                runtime = "antigravity"
            norm_start = _utc_iso(reg.get("started_at") or preflight.get("timestamp"))
            if not norm_start:
                continue
            work = preflight.get("work") if isinstance(preflight.get("work"), dict) else {}
            resume_gen = _safe_int(reg.get("resume_generation") or session.get("resume_generation"))
            is_cont = bool(str(work.get("previous_action") or "").strip()) or resume_gen > 0
            route_obj = preflight.get("route") if isinstance(preflight.get("route"), dict) else {}
            req_docs = route_obj.get("required_docs") if isinstance(route_obj.get("required_docs"), list) else []
            spill_id = ("run_" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24] if runtime in {"codex", "antigravity"} else session_id) if (runtime and session_id) else ""
            collected.append({
                "run_id": run_dir.name, "work_id": str(work.get("id") or run_dir.name),
                "runtime": runtime, "session_id": session_id, "spill_run_id": spill_id,
                "stamped_model": str(session.get("model") or "").strip(),
                "stamped_effort": str(session.get("reasoning_effort") or "").strip().lower(),
                "route": _extract_route_name(reg, preflight, route_obj), "state": str(reg.get("state") or "unknown"),
                "same_work_mode": "continuation" if is_cont else "fresh",
                "resume_generation": resume_gen, "required_docs_count": len(req_docs),
                "reused_gate_count": _count_reused_gates(run_dir / "gate-evidence.json"), "started_at": norm_start,
            })
    return collected


_ROUTE_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{1,32}$")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _utc_iso(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return text


def _extract_route_name(reg: dict[str, Any], preflight: dict[str, Any], route_obj: dict[str, Any]) -> str:
    for candidate in (reg.get("command"), route_obj.get("command"), route_obj.get("workflow_command")):
        if isinstance(candidate, str) and _ROUTE_TOKEN_RE.match(candidate.strip()):
            return candidate.strip()
    rc = preflight.get("route_command")
    argv = rc.get("command") if isinstance(rc, dict) else None
    if isinstance(argv, list) and len(argv) >= 4 and argv[2] == "route" and isinstance(argv[3], str) and _ROUTE_TOKEN_RE.match(argv[3].strip()):
        return argv[3].strip()
    return "unknown"


def _count_reused_gates(gate_evidence_path: Path) -> int:
    entries = read_json_object(gate_evidence_path).get("entries") if gate_evidence_path.is_file() else None
    if not isinstance(entries, list):
        return 0
    return sum(
        1 for e in entries if isinstance(e, dict) and (
            bool(e.get("reused")) or str(e.get("source") or "").strip().lower() in {"reuse", "reused"} or isinstance(e.get("reuse_provenance"), dict)
        )
    )


def _load_codex_threads(codex_db: Path) -> dict[str, tuple[str, str]]:
    if not codex_db.is_file():
        return {}
    try:
        with sqlite3.connect(f"file:{codex_db}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT id, COALESCE(model, ''), COALESCE(reasoning_effort, '') FROM threads").fetchall()
    except sqlite3.Error:
        return {}
    return {str(r[0]): (str(r[1]).strip(), str(r[2]).strip().lower() or "unknown") for r in rows if r and r[0]}


def _load_spill_events(spill_db: Path, spill_run_ids: set[str]) -> dict[str, list[tuple[str, str, float, int, int]]]:
    if not spill_db.is_file() or not spill_run_ids:
        return {}
    by_run: dict[str, list[tuple[str, str, float, int, int]]] = defaultdict(list)
    try:
        with sqlite3.connect(f"file:{spill_db}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT run_id, created_at, COALESCE(model, ''), "
                "(COALESCE(accounting_uncached_input_tokens, 0)*1.0 + COALESCE(accounting_cache_creation_input_tokens, 0)*1.25 + "
                "COALESCE(accounting_cache_read_input_tokens, 0)*0.1 + COALESCE(output_tokens, 0)*1.0), "
                "COALESCE(total_tokens, 0), COALESCE(accounting_reasoning_output_tokens, 0) "
                "FROM token_usage_events WHERE run_id IS NOT NULL"
            ).fetchall()
    except sqlite3.Error:
        return {}
    for run_id, created_at, model, weighted, total, reasoning in rows:
        if str(run_id or "") in spill_run_ids:
            norm_ts = _utc_iso(created_at)
            if norm_ts:
                by_run[str(run_id)].append((norm_ts, str(model or "").strip(), float(weighted or 0.0), int(total or 0), int(reasoning or 0)))
    for key in by_run:
        by_run[key].sort(key=lambda item: item[0])
    return by_run


def _bind_run_metrics(
    runs: list[dict[str, Any]], spill_events: dict[str, list[tuple[str, str, float, int, int]]],
    codex_threads: dict[str, tuple[str, str]], *, month: str
) -> list[dict[str, Any]]:
    by_session: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unbound: list[dict[str, Any]] = []
    for run in runs:
        (by_session[(run["runtime"], run["session_id"])] if run["runtime"] and run["session_id"] else unbound).append(run)
    bound: list[dict[str, Any]] = []
    for (runtime, session_id), session_runs in by_session.items():
        session_runs.sort(key=lambda item: item["started_at"])
        codex_model, codex_effort = codex_threads.get(session_id, ("", "unknown"))
        events = spill_events.get(session_runs[0]["spill_run_id"], [])
        for idx, run in enumerate(session_runs):
            start_ts = run["started_at"]
            if month and not start_ts.startswith(month):
                continue
            next_ts = session_runs[idx + 1]["started_at"] if idx + 1 < len(session_runs) else "9999-99-99"
            window = [ev for ev in events if start_ts <= ev[0] < next_ts]
            event_model = next((ev[1] for ev in reversed(window) if ev[1]), "")
            bound.append({
                **run, "model": run["stamped_model"] or codex_model or event_model or "unknown",
                "reasoning_effort": run["stamped_effort"] or (codex_effort if runtime == "codex" else "unknown") or "unknown",
                "period_bucket": _period_bucket(start_ts, single_month=bool(month)), "turns": len(window),
                "weighted_tokens": sum(ev[2] for ev in window), "raw_tokens": sum(ev[3] for ev in window), "reasoning_tokens": sum(ev[4] for ev in window),
            })
    for run in unbound:
        if not month or run["started_at"].startswith(month):
            bound.append({
                **run, "model": run["stamped_model"] or "unknown", "reasoning_effort": run["stamped_effort"] or "unknown",
                "period_bucket": _period_bucket(run["started_at"], single_month=bool(month)),
                "turns": 0, "weighted_tokens": 0.0, "raw_tokens": 0, "reasoning_tokens": 0,
            })
    return bound


def _period_bucket(timestamp: str, *, single_month: bool) -> str:
    ym = timestamp[:7] if len(timestamp) >= 7 else "unknown"
    return f"{ym}-W{min(4, ((int(timestamp[8:10]) - 1) // 7) + 1)}" if (single_month and len(timestamp) >= 10 and timestamp[8:10].isdigit()) else ym


def _percentile(sorted_values: list[float], ratio: float) -> float:
    return float(sorted_values[min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * ratio))))]) if sorted_values else 0.0


def _summarize_runs(items: list[dict[str, Any]]) -> dict[str, Any]:
    turns = sorted(float(item["turns"]) for item in items)
    weighted_m = sorted(float(item["weighted_tokens"]) / 1_000_000.0 for item in items)
    total_turns, total_reasoning = sum(int(item["turns"]) for item in items), sum(int(item["reasoning_tokens"]) for item in items)
    return {
        "run_count": len(items), "completed_runs": sum(1 for item in items if item["state"] == "completed"),
        "turns_p50": round(statistics.median(turns), 1) if turns else 0.0,
        "turns_p90": round(_percentile(turns, 0.9), 1) if turns else 0.0,
        "turns_mean": round(statistics.mean(turns), 1) if turns else 0.0,
        "weighted_tokens_m_p50": round(statistics.median(weighted_m), 3) if weighted_m else 0.0,
        "weighted_tokens_m_p90": round(_percentile(weighted_m, 0.9), 3) if weighted_m else 0.0,
        "weighted_tokens_m_mean": round(statistics.mean(weighted_m), 3) if weighted_m else 0.0,
        "avg_required_docs": round(statistics.mean(item["required_docs_count"] for item in items), 2) if items else 0.0,
        "avg_reused_gates": round(statistics.mean(item["reused_gate_count"] for item in items), 2) if items else 0.0,
        "reasoning_tokens_per_turn": round(total_reasoning / total_turns, 1) if total_turns else 0.0,
    }
