"""One bounded continuation for declared executable work in an admitted v2 run.

Owner: premature-stop policy; allowed imports: existing binding/permission/state/graph readers.
Forbidden: transcript or prompt inference, executing work, new authority or retries.
Callers/tests: Codex and Claude Stop adapters; test_agent_stop_continuation.
Verification: partial delivery continues once with delta surface guidance; user stops and global waits win.
"""

from __future__ import annotations

from pathlib import Path

from agent_execution_capsule_state import read_json_object
from agent_mailbox_task_binding import stop_ready
from agent_run_registry import ACTIVE_RUN_STATES, registered_run
from agent_runtime_session import resolve_runtime_evidence, same_runtime_session
from agent_work_completion import bound_work_packet, scope_unreconciled
from workflow_effect_policy import route_minimum_effect


def _surface_graph_note(project: Path, preflight: dict, work: dict) -> str:
    """Route delta surface and verification docs for active remaining_work and changed_scope."""
    try:
        from workflow_common import ROOT, unique
        from workflow_doc_graph import expand_doc_matches, graph_required_docs
        from workflow_doc_surfaces import (
            RULES_FILE,
            extract_request_surface_paths,
            infer_surface_docs,
            normalize_path,
        )

        route = preflight.get("route")
        if not isinstance(route, dict) or not isinstance(work, dict):
            return ""
        raw_rules = str(preflight.get("rules") or preflight.get("moru_root") or "").strip()
        candidate_root = Path(raw_rules) if raw_rules else ROOT
        if candidate_root.is_symlink():
            return ""
        rules_root = candidate_root.resolve()
        rules_file = rules_root / RULES_FILE
        if rules_file.is_symlink() or not rules_file.is_file():
            rules_root = ROOT
            if (rules_root / RULES_FILE).is_symlink() or not (rules_root / RULES_FILE).is_file():
                return ""

        actions: list[str] = []
        paths: list[str] = []
        remaining = work.get("remaining_work")
        for item in remaining if isinstance(remaining, list) else []:
            if isinstance(item, dict) and isinstance(item.get("action"), str):
                actions.append(item["action"])
                paths.extend(extract_request_surface_paths(item["action"]))
        changed = work.get("changed_scope")
        for item in changed if isinstance(changed, list) else []:
            if isinstance(item, dict):
                target = item.get("to") if item.get("role") == "renamed" else item.get("path")
                if isinstance(target, str):
                    paths.append(target)
        req_obj = work.get("requirements")
        reqs = req_obj.get("items") if isinstance(req_obj, dict) else None
        for item in reqs if isinstance(reqs, list) else []:
            if isinstance(item, dict):
                if isinstance(item.get("outcome"), str):
                    actions.append(item["outcome"])
                artifacts = item.get("artifacts")
                if isinstance(artifacts, list):
                    paths.extend(p for p in artifacts if isinstance(p, str))

        if not actions and not paths:
            return ""
        seeds, _ = infer_surface_docs(
            command=str(route.get("command") or ""),
            platform=route.get("platform") if isinstance(route.get("platform"), str) else None,
            request_text="; ".join(actions),
            surface_paths=paths,
            root=rules_root,
            project_root=project,
        )
        raw_req_docs = route.get("required_docs")
        already_required = {
            normalize_path(doc)
            for doc in (raw_req_docs if isinstance(raw_req_docs, list) else [])
            if isinstance(doc, str) and normalize_path(doc)
        }
        new_seeds = [doc for doc in seeds if normalize_path(doc) not in already_required]
        if not new_seeds:
            return ""
        promoted = graph_required_docs(expand_doc_matches(rules_root, new_seeds, max_depth=1))
        delta = [
            normalize_path(doc)
            for doc in unique([*new_seeds, *promoted])
            if normalize_path(doc) and normalize_path(doc) not in already_required
        ][:3]
        if not delta:
            return ""
        return " Active graph surface guidance for remaining work: " + ", ".join(delta) + "."
    except (AttributeError, ImportError, OSError, ValueError, RuntimeError, TypeError, KeyError):
        return ""


def continuation_reason(payload: dict, runtime: str, project: Path, evidence: Path | None = None) -> str | None:
    """Recorded work is the signal; absence of recorded activity proves nothing."""
    try:
        identity = {"runtime": runtime, "session_id": str(payload.get("session_id") or "")}
        evidence = evidence or resolve_runtime_evidence(project, identity)
        if evidence is None:
            return None
        preflight = read_json_object(evidence)
        route = preflight.get("route") or {}
        envelope = (route.get("request_classification") or {}).get("intent_envelope") or {}
        run = registered_run(project, evidence)
        if (not run or run.get("state") not in ACTIVE_RUN_STATES
                or not same_runtime_session(preflight.get("runtime_session"), identity,
                                            resume_generation=int(run.get("resume_generation") or 0))
                or preflight.get("execution_mode", {}).get("read_only")
                or route_minimum_effect(route.get("command", "")) == "read"
                or not envelope.get("schema_valid") or not envelope.get("envelope_present")
                or envelope.get("failures") or envelope.get("effective_effect") not in
                {"local_write", "git_write", "external_write", "destructive"}):
            return None
        packet = bound_work_packet(project, evidence)
        if (not packet or packet.get("phase") not in {"scoped", "acting", "verifying", "reviewing"}
                or not ((packet.get("work") or {}).get("remaining_work") or scope_unreconciled(preflight, packet))
                or not stop_ready(payload, identity, project, independent_work=True)):
            return None
        from agent_completion_checks import progress_note
        work = packet.get("work") or {}
        note = progress_note(project, evidence, work, identity) + _surface_graph_note(project, preflight, work)
        return (
            "This existing user-approved task has remaining work or has not reconciled its "
            "full requested scope. Reconcile the bounded scope first, then continue remaining "
            "independent work in the same run, within its approved scope; a completed subset "
            "or passed route checks do not complete the full request. This reminder grants no "
            "new authority. Keep permission and safety checks. If a user decision, permission, "
            "stop, or unresolved operation prevents progress, record that blocker and end the "
            "turn honestly. Update remaining_work from observed results before finish. "
            "This automatic continuation is limited to one per turn." + note
        )
    except (AttributeError, OSError, ValueError, RuntimeError, TypeError, KeyError):
        return None  # Untrusted/missing state never traps a session or supplies authority.
