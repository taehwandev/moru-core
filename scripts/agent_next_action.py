#!/usr/bin/env python3
"""Read-only next-action advisor and target test discovery for active Moru Core runs.

Owner: developer-experience next-step guidance and changed-file test discovery.
Allowed imports: standard library, agent_finish_gate_learning_validators,
agent_gate_evidence, agent_gate_record_template, agent_next_verification,
agent_review_hook, agent_route_state, agent_runtime_session,
agent_skill_catalog, agent_start_guidance, support.bounded_git, support.stable_launcher.
Forbidden imports: mutating lifecycle writers or test execution side effects.
Callers: stable launcher `next` alias; tests: test_agent_next_action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_next_verification import (
    apply_active_verify_advice,
    discover_verification_targets,
    reconcile_verify_batches,
    shell_quote,
)
from agent_runtime_session import resolve_runtime_evidence, runtime_session
from support.bounded_git import run_git
from support.stable_launcher import stable_launcher_path

ROOT = Path(__file__).resolve().parents[1]


def discover_changed_paths(project: Path) -> list[str]:
    """Return repository-relative changed or untracked paths from git status."""
    result = run_git(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for raw_line in result.stdout.splitlines():
        if len(raw_line) < 4:
            continue
        candidate = raw_line[3:].strip()
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1].strip()
        candidate = candidate.strip('"')
        if candidate and not candidate.startswith(".moru/"):
            paths.append(candidate)
    return sorted(dict.fromkeys(paths))


def suggest_verification_targets(project: Path, changed_paths: list[str] | None = None) -> dict[str, Any]:
    """Map changed files to the nearest unit test selectors and fast verification commands."""
    resolved = project.expanduser().resolve()
    paths = changed_paths if changed_paths is not None else discover_changed_paths(resolved)
    return discover_verification_targets(resolved, paths)


def _find_active_preflight(project: Path, explicit_evidence: Path | None = None) -> Path | None:
    if explicit_evidence is not None and explicit_evidence.is_file():
        return explicit_evidence.resolve()
    session = runtime_session()
    if session:
        resolved = resolve_runtime_evidence(project, session)
        if resolved is not None and resolved.is_file():
            return resolved
    return None


def _build_gate_batch_command(
    launcher: str,
    project: Path,
    evidence_path: Path,
    gates: list[str],
    loaded_skills: list[str],
) -> str:
    from agent_finish_gate_learning_validators import CAUSAL_RETROSPECTIVE_FIELDS
    from agent_gate_evidence import FIELD_REQUIREMENTS, gate_field_enums
    from agent_gate_record_template import _placeholder

    records: list[dict[str, Any]] = []
    for gate in gates:
        causal = CAUSAL_RETROSPECTIVE_FIELDS if gate == "retrospective check" else ()
        names = list(dict.fromkeys([*FIELD_REQUIREMENTS.get(gate, ()), *causal]))
        enums = gate_field_enums(gate)
        fields = {name: _placeholder(gate, name, enums) for name in names}
        if gate == "retrospective check" and loaded_skills:
            # Name the loaded skills only; the outcome must come from the agent's own check.
            fields["skills_checked"] = ", ".join(loaded_skills)
        records.append({"gate": gate, "status": "<SUCCESS or FAIL>", "fields": fields})
    serialized = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{shell_quote(launcher)} gate-batch --project {shell_quote(str(project))} "
        f"--evidence {shell_quote(str(evidence_path))} "
        f"--gate-record '{serialized}'"
    )


def _no_active_advice(launcher, resolved, verification):
    return {
        "status": "no_active_run", "project": str(resolved), "next_step": "start",
        "copyable_command": (
            f"{shell_quote(launcher)} start --project {shell_quote(str(resolved))} "
            f"--rules {shell_quote(str(ROOT))} --command <route> "
            '--request "<USER_REQUEST>" --intent <safe_slug> '
            '--target-summary "<bounded target>"'),
        "verification": verification,
    }


def inspect_next_action(project: Path, *, evidence: Path | None = None) -> dict[str, Any]:
    """Compute the exact next lifecycle step and copyable command for a project."""
    resolved = project.expanduser().resolve()
    launcher = str(stable_launcher_path())
    preflight_path = _find_active_preflight(resolved, evidence)
    verification = suggest_verification_targets(resolved)

    if preflight_path is None:
        return _no_active_advice(launcher, resolved, verification)

    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {
            "status": "unreadable_preflight",
            "project": str(resolved),
            "evidence": str(preflight_path),
            "error": str(error),
        }

    # Active-run contracts are not needed for help, no-run or unreadable input.
    from agent_gate_evidence import merge_gate_evidence_from_ledger
    from agent_gate_record_template import remaining_gate_template_lines
    from agent_review_hook import required_review_evidence_flags
    from agent_route_state import required_docs_for_route
    from agent_skill_catalog import skill_ids_from_doc_paths
    from agent_start_guidance import review_shape_line

    route = preflight.get("route") or {}
    gates = [g for g in (route.get("gates") or []) if isinstance(g, str)]
    recorded, _diagnostics = merge_gate_evidence_from_ledger(route=route, evidence_path=preflight_path)
    remaining = [gate for gate in gates if not recorded.get(gate)]
    loaded_skills = sorted(skill_ids_from_doc_paths(required_docs_for_route(route) or []))
    rules_root = str(preflight.get("rules") or ROOT)
    reconciled = reconcile_verify_batches(verification, project=resolved, rules=rules_root,
                                         evidence_path=preflight_path)
    if reconciled and not verification['observed_selection_complete'] and 'tests' in gates:
        remaining = [gate for gate in gates if gate == 'tests' or gate not in recorded]
    verify_cmd = (
        apply_active_verify_advice(
            verification,
            launcher=launcher,
            project=resolved,
            rules=rules_root,
            evidence_path=preflight_path,
        )
        if "tests" in remaining
        else None
    )

    if not remaining:
        next_step = "finish"
        copyable = (
            f"{shell_quote(launcher)} finish --project {shell_quote(str(resolved))} "
            f"--evidence {shell_quote(str(preflight_path))}"
        )
    elif "review hook" in remaining:
        idx = remaining.index("review hook")
        pre_review = [g for g in remaining[:idx] if g not in ("review hook", "commit readiness")]
        other_pre = [g for g in pre_review if not (verify_cmd and g == "tests")]
        if verify_cmd and "tests" in pre_review and not other_pre:
            next_step = "verify"
            copyable = verify_cmd
        elif other_pre:
            next_step = "record_pre_review_gates"
            copyable = _build_gate_batch_command(launcher, resolved, preflight_path, other_pre, loaded_skills)
        else:
            next_step = "review"
            flags = required_review_evidence_flags(gates)
            flag_str = " ".join(f'{flag} "<observed evidence>"' for flag in flags)
            copyable = (
                f"{shell_quote(launcher)} review --project {shell_quote(str(resolved))} "
                f"--evidence {shell_quote(str(preflight_path))} "
                f"--review-outcome <pass|findings> {flag_str}"
            )
    else:
        manual_remaining = [g for g in remaining if g not in ("review hook", "commit readiness")]
        if verify_cmd and "tests" in manual_remaining:
            next_step = "verify"
            copyable = verify_cmd
        elif manual_remaining:
            next_step = "record_closeout_gates"
            copyable = _build_gate_batch_command(launcher, resolved, preflight_path, manual_remaining, loaded_skills)
        else:
            next_step = "finish"
            copyable = (
                f"{shell_quote(launcher)} finish --project {shell_quote(str(resolved))} "
                f"--evidence {shell_quote(str(preflight_path))}"
            )

    template_lines = remaining_gate_template_lines(remaining, loaded_skills)
    if verification.get("batch_status"):
        template_lines = [*template_lines, f"Bounded verification batch: {verification['batch_status']}"]

    return {
        "status": "active_run",
        "project": str(resolved),
        "run_id": str(preflight.get("agent_run_id") or preflight_path.parent.name),
        "work_id": str((preflight.get("work") or {}).get("id") or ""),
        "command": str(route.get("command") or ""),
        "evidence": str(preflight_path),
        "remaining_gates": remaining,
        "loaded_skills": loaded_skills,
        "next_step": next_step,
        "copyable_command": copyable,
        "template_lines": template_lines,
        "review_shape": review_shape_line(required_review_evidence_flags(gates)) if "review hook" in gates else "",
        "verification": verification,
    }


def render_next_markdown(info: dict[str, Any]) -> str:
    if info.get("status") != "active_run":
        lines = [
            f"SUCCESS next ({info.get('status')})",
            f"- project: {info.get('project')}",
            f"- next step: {info.get('next_step', 'start')}",
            f"- copyable command: {info.get('copyable_command', '')}",
        ]
    else:
        lines = [
            "SUCCESS next",
            f"- run id: {info['run_id']} (route: {info['command']})",
            f"- evidence: {info['evidence']}",
            f"- remaining gates: {info['remaining_gates']}",
            f"- next step: {info['next_step']}",
            f"- copyable command: {info['copyable_command']}",
        ]
        for line in info.get("template_lines", [])[1:]:
            lines.append(f"- {line}")
    ver = info.get("verification") or {}
    if ver.get("suggested_commands"):
        lines.append("- suggested fast verification for changed files:")
        for cmd in ver["suggested_commands"]:
            lines.append(f"  * {cmd}")
    if ver.get("remaining_test_selectors"):
        rem = ver["remaining_test_selectors"]
        lines.append(
            f"- remaining test selectors beyond 64-selector batch ({len(rem)}): "
            + ", ".join(rem)
        )
    if ver.get("omissions"):
        lines.append("- verification omissions:")
        for item in ver["omissions"]:
            target = item.get("path") or f"{item.get('count', '')} items"
            lines.append(f"  * [{item.get('kind')}] {target}: {item.get('reason')}")
    if ver.get("coverage_note"):
        lines.append(f"- verification scope note: {ver['coverage_note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the exact next lifecycle step and copyable command.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--evidence", type=Path, help="Explicit preflight.json path.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    info = inspect_next_action(args.project, evidence=args.evidence)
    if args.format == "json":
        print(json.dumps(info, ensure_ascii=False, sort_keys=True))
    else:
        print(render_next_markdown(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
