#!/usr/bin/env python3
"""Read-only diagnostics for Moru Core projects.

Owner: developer-experience project diagnostics; it never writes project files.
Allowed imports: standard library, support.global_state, support.stable_launcher,
support.project_type_detection, support.native_probe_transport, support.native_cards,
agent_observability, agent_project_memory,
agent_project_memory_consolidate, agent_work_cards.
Forbidden imports: mutating lifecycle hooks, shell execution of arbitrary user code.
Callers: stable launcher `doctor` alias; tests: test_agent_doctor.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from agent_observability import status_snapshot
from agent_project_memory import RECALLABLE_STATUSES, scan_records as project_memory_scan
from agent_project_memory import store_dir as project_memory_store
from agent_project_memory_consolidate import findings as project_memory_findings
from agent_work_cards import list_cards
from support.global_state import global_state_dir, project_state_dir_target
from support.native_cards import NativeCards
from support.native_probe_transport import NativeProbe
from support.project_type_detection import detect_project_permissions
from support.stable_launcher import (
    stable_launcher_issue,
    stable_launcher_path,
    stable_root_pointer_path,
)

ROOT = Path(__file__).resolve().parents[1]
MANAGED_BEGIN = "<!-- BEGIN MANAGED MORU CORE ROUTING -->"
MANAGED_END = "<!-- END MANAGED MORU CORE ROUTING -->"


def detect_project_stacks(project: Path) -> list[str]:
    """Return short stack labels detected in the target repository."""
    stacks: list[str] = []
    if (project / "Package.swift").exists() or any(project.glob("*.xcodeproj")) or any(project.glob("*.xcworkspace")):
        stacks.append("swift")
    if (project / "package.json").exists():
        stacks.append("node")
    if (
        (project / "build.gradle.kts").exists()
        or (project / "build.gradle").exists()
        or (project / "settings.gradle.kts").exists()
    ):
        stacks.append("gradle")
    if (project / "Cargo.toml").exists():
        stacks.append("rust")
    if (project / "go.mod").exists():
        stacks.append("go")
    if (
        (project / "pyproject.toml").exists()
        or (project / "setup.py").exists()
        or (project / "requirements.txt").exists()
        or any(project.glob("*.py"))
        or (project / "scripts").is_dir()
    ):
        stacks.append("python")
    return stacks


def _inspect_project_files(project: Path) -> tuple[list[str], bool, bool]:
    native = NativeProbe.request("--completion-probe", "doctor-project", {"project": str(project)})
    if native is not None and set(native) == {"stacks", "instructions"}:
        stacks = native["stacks"]
        instructions = native["instructions"]
        if (
            isinstance(stacks, list) and all(isinstance(stack, str) for stack in stacks)
            and isinstance(instructions, dict)
            and set(instructions) == {"agents_md_present", "managed_routing_block"}
            and all(type(value) is bool for value in instructions.values())
        ):
            return stacks, instructions["agents_md_present"], instructions["managed_routing_block"]

    agents_file = project / "AGENTS.md"
    has_agents = agents_file.is_file()
    has_managed_block = False
    if has_agents:
        try:
            content = agents_file.read_text(encoding="utf-8")
            has_managed_block = MANAGED_BEGIN in content and MANAGED_END in content
        except OSError:
            has_managed_block = False

    return detect_project_stacks(project), has_agents, has_managed_block


def inspect_project_health(project: Path, *, rules: Path = ROOT) -> dict[str, Any]:
    """Collect a read-only diagnostic report for the project and user install."""
    report, _ = _project_health_report(project, rules)
    return report


def _project_health_report(
    project: Path, rules: Path, *, output_format: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    resolved = project.expanduser().resolve()
    launcher_warning = stable_launcher_issue(rules, native_check=True)
    state_dir = project_state_dir_target(resolved)
    stacks, has_agents, has_managed_block = _inspect_project_files(resolved)
    permissions = detect_project_permissions(resolved, native_node_scan=True)
    active_runs = _active_run_count(resolved)
    open_cards = NativeCards.count_open(resolved)
    if open_cards is None:
        open_cards = len(list_cards(resolved, include_settled=False))
    memory_stats = _project_memory_stats(resolved)

    facts = {
        "project": str(resolved),
        "rules": str(rules.resolve()),
        "stacks": stacks,
        "detected_permission_count": len(permissions),
        "instructions": {
            "agents_md_present": has_agents,
            "managed_routing_block": has_managed_block,
        },
        "state": {
            "active_state_dir": str(state_dir),
            "active_runs": active_runs,
            "open_work_cards": open_cards,
            "project_memory": memory_stats,
        },
        "launchers": {
            "moru_launcher": str(stable_launcher_path()),
            "moru_root_pointer": str(stable_root_pointer_path()),
            "launcher_issue": launcher_warning,
        },
    }
    template = str(rules / "templates" / "repo-agents-routing.md")
    native = NativeProbe.request("--completion-probe", "doctor-report", {
        "facts": facts, "routing_template": template, "format": output_format,
    })
    if native is not None and set(native) == {"report", "rendered"}:
        report, rendered = native["report"], native["rendered"]
        if isinstance(report, dict) and (isinstance(rendered, str) if output_format else rendered is None):
            return report, rendered
    report = _assemble_report_python(facts, template)
    if output_format == "json":
        return report, json.dumps(report, ensure_ascii=False, sort_keys=True)
    return report, _render_markdown_doctor(report) if output_format == "markdown" else None


def _active_run_count(project: Path) -> int:
    native = NativeProbe.request("--completion-probe", "doctor-active-runs", {"project": str(project)})
    if native is not None and set(native) == {"active_runs"}:
        count = native["active_runs"]
        if type(count) is int and count >= 0:
            return count
    return status_snapshot(project).get("active_runs", 0)


def _project_memory_stats(project: Path) -> dict[str, int]:
    empty = {"active_records": 0, "expired_or_due": 0, "unreadable": 0}
    try:
        if NativeProbe.available():
            directory = project_memory_store(project)
            today = date.today()
            native = NativeProbe.request("--completion-probe", "doctor-memory", {
                "path": str(directory), "today": today.isoformat(),
                "unicode": unicodedata.unidata_version, "statuses": sorted(RECALLABLE_STATUSES),
            })
            if (
                native is not None and set(native) == set(empty)
                and all(type(count) is int and count >= 0 for count in native.values())
                and date.today() == today
            ):
                return native
        records, unreadable = project_memory_scan(project)
        report = project_memory_findings(records, unreadable, today=date.today())
        return {
            "active_records": len(records),
            "expired_or_due": len(report.get("expired", [])) + len(report.get("due_for_review", [])),
            "unreadable": unreadable,
        }
    except (OSError, ValueError):
        return empty


def _assemble_report_python(facts: dict[str, Any], template: str) -> dict[str, Any]:
    warning = facts["launchers"]["launcher_issue"]
    due = facts["state"]["project_memory"]["expired_or_due"]
    recommendations: list[str] = []
    if warning:
        recommendations.append(warning)
    if not facts["instructions"]["agents_md_present"]:
        recommendations.append(f"No AGENTS.md; add the managed routing block from `{template}`.")
    if due > 0:
        recommendations.append(
            f"Project memory has {due} record(s) due for review; run "
            f"`{facts['launchers']['moru_launcher']} project-memory consolidate --project {facts['project']}`."
        )
    return {"status": "attention" if warning else "ok", **facts, "recommendations": recommendations}


def _render_markdown_doctor(report: dict[str, Any]) -> str:
    lines = [
        f"Moru Doctor ({report['status'].upper()}): {report['project']}",
        f"- detected stacks: {', '.join(report['stacks']) if report['stacks'] else 'none'} "
        f"(permissions: {report['detected_permission_count']})",
        f"- AGENTS.md: {'present' if report['instructions']['agents_md_present'] else 'missing'} "
        f"(managed block: {'yes' if report['instructions']['managed_routing_block'] else 'no'})",
        f"- state root: {report['state']['active_state_dir']}",
        f"- active runs: {report['state']['active_runs']}, "
        f"open work cards: {report['state']['open_work_cards']}, "
        f"project memory: {report['state']['project_memory']['active_records']} active "
        f"({report['state']['project_memory']['expired_or_due']} due)",
    ]
    if report["recommendations"]:
        lines.append("- recommendations:")
        for item in report["recommendations"]:
            lines.append(f"  * {item}")
    else:
        lines.append("- recommendations: none (healthy)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose a Moru Core project without changing it.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    _, rendered = _project_health_report(args.project, ROOT, output_format=args.format)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
