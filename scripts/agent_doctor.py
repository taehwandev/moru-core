#!/usr/bin/env python3
"""Read-only diagnostics for Moru Core projects.

Owner: developer-experience project diagnostics; it never writes project files.
Allowed imports: standard library, support.global_state, support.stable_launcher,
support.project_type_detection, agent_observability, agent_project_memory,
agent_project_memory_consolidate, agent_work_cards.
Forbidden imports: mutating lifecycle hooks, shell execution of arbitrary user code.
Callers: stable launcher `doctor` alias; tests: test_agent_doctor.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from agent_observability import status_snapshot
from agent_project_memory import scan_records as project_memory_scan
from agent_project_memory_consolidate import findings as project_memory_findings
from agent_work_cards import list_cards
from support.global_state import global_state_dir, project_state_dir_target
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


def inspect_project_health(project: Path, *, rules: Path = ROOT) -> dict[str, Any]:
    """Collect a read-only diagnostic report for the project and user install."""
    resolved = project.expanduser().resolve()
    launcher_warning = stable_launcher_issue(rules)
    state_dir = project_state_dir_target(resolved)
    agents_file = resolved / "AGENTS.md"
    has_agents = agents_file.is_file()
    has_managed_block = False
    if has_agents:
        try:
            content = agents_file.read_text(encoding="utf-8")
            has_managed_block = MANAGED_BEGIN in content and MANAGED_END in content
        except OSError:
            has_managed_block = False

    stacks = detect_project_stacks(resolved)
    permissions = detect_project_permissions(resolved)
    snapshot = status_snapshot(resolved)
    open_cards = list_cards(resolved, include_settled=False)

    memory_stats = {"active_records": 0, "expired_or_due": 0, "unreadable": 0}
    try:
        records, unreadable = project_memory_scan(resolved)
        report = project_memory_findings(records, unreadable, today=date.today())
        memory_stats = {
            "active_records": len(records),
            "expired_or_due": len(report.get("expired", [])) + len(report.get("due_for_review", [])),
            "unreadable": unreadable,
        }
    except (OSError, ValueError):
        pass

    recommendations: list[str] = []
    if launcher_warning:
        recommendations.append(launcher_warning)
    if not has_agents:
        recommendations.append(
            f"No AGENTS.md; add the managed routing block from `{rules / 'templates' / 'repo-agents-routing.md'}`."
        )
    if memory_stats["expired_or_due"] > 0:
        recommendations.append(
            f"Project memory has {memory_stats['expired_or_due']} record(s) due for review; run "
            f"`{stable_launcher_path()} project-memory consolidate --project {resolved}`."
        )

    return {
        "status": "ok" if not launcher_warning else "attention",
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
            "active_runs": snapshot.get("active_runs", 0),
            "open_work_cards": len(open_cards),
            "project_memory": memory_stats,
        },
        "launchers": {
            "moru_launcher": str(stable_launcher_path()),
            "moru_root_pointer": str(stable_root_pointer_path()),
            "launcher_issue": launcher_warning,
        },
        "recommendations": recommendations,
    }


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
    report = inspect_project_health(args.project)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(_render_markdown_doctor(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
