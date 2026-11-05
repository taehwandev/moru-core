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


def _safe_doc(rules_root: Path, raw_doc: str, normalize_path) -> str:
    """Return normalized doc path only when it is a regular non-symlink file inside rules_root."""
    import stat

    doc = normalize_path(raw_doc)
    if not doc or ".." in Path(raw_doc).parts:
        return ""
    candidate = rules_root / doc
    try:
        for part in (candidate, *candidate.parents):
            if part == rules_root:
                break
            if part.is_symlink():
                return ""
        if not stat.S_ISREG(candidate.lstat().st_mode) or not candidate.resolve().is_relative_to(rules_root):
            return ""
    except OSError:
        return ""
    return doc


def _surface_graph_note(project: Path, preflight: dict, work: dict) -> str:
    """Route delta surface and verification docs for active remaining_work and changed_scope."""
    try:
        from workflow_common import ROOT, unique
        from workflow_doc_graph_refs import PROMOTING_RELATIONS, VERIFICATION_RELATION, frontmatter_relation_raw_refs
        from workflow_doc_surfaces import (
            RULES_FILE,
            extract_request_surface_paths,
            infer_surface_docs,
            normalize_path,
            required_surface_docs,
        )

        route = preflight.get("route")
        if not isinstance(route, dict) or not isinstance(work, dict):
            return ""
        raw_rules = str(preflight.get("rules") or preflight.get("moru_root") or "").strip()
        candidate_root = (Path(raw_rules).expanduser().absolute() if raw_rules else ROOT)
        if any(
            part.is_symlink() and part.as_posix() not in {"/var", "/tmp", "/etc"}
            for part in (candidate_root, *candidate_root.parents)
        ):
            return ""
        rules_root = candidate_root.resolve()
        if not _safe_doc(rules_root, RULES_FILE, normalize_path):
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
        _, matches = infer_surface_docs(
            command=str(route.get("command") or ""),
            platform=route.get("platform") if isinstance(route.get("platform"), str) else None,
            request_text="; ".join(actions),
            surface_paths=paths,
            root=rules_root,
            project_root=project,
        )
        safe_seeds = unique(
            safe
            for doc in required_surface_docs(matches)
            if (safe := _safe_doc(rules_root, doc, normalize_path))
        )
        if not safe_seeds:
            return ""
        raw_req_docs = route.get("required_docs")
        already_required = {
            normalize_path(doc)
            for doc in (raw_req_docs if isinstance(raw_req_docs, list) else [])
            if isinstance(doc, str) and normalize_path(doc)
        }
        delta_seeds = [doc for doc in safe_seeds if doc not in already_required]
        ordered_seeds = [*delta_seeds, *(doc for doc in safe_seeds if doc in already_required)]
        allowed_relations = (*PROMOTING_RELATIONS, VERIFICATION_RELATION)
        promoted: list[str] = []
        for seed in ordered_seeds:
            text = (rules_root / seed).read_text(encoding="utf-8", errors="ignore")
            for relation, raw_target in frontmatter_relation_raw_refs(text):
                if not relation.startswith(allowed_relations):
                    continue
                for rel in (raw_target, f"{Path(seed).parent.as_posix()}/{raw_target}"):
                    if safe_target := _safe_doc(rules_root, rel, normalize_path):
                        promoted.append(safe_target)
                        break
        delta_promoted = unique(
            doc for doc in promoted if doc not in already_required and doc not in delta_seeds
        )
        delta = (
            [*delta_seeds[:2], delta_promoted[0]]
            if delta_promoted and len(delta_seeds) >= 3
            else unique([*delta_seeds, *delta_promoted])[:3]
        )
        if not delta:
            return ""
        return " Active graph surface guidance for remaining work: " + ", ".join(delta) + "."
    except Exception:
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
