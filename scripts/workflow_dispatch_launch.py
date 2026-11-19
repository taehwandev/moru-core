"""Launch-time validation and inspect-only rendering for Codex dispatch."""

from __future__ import annotations

import json
import errno
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping

from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_run_registry import latest_run_id
from agent_ipc import emit_event, emit_heartbeat, emit_worker_failure, emit_worker_result
from agent_scheduler import claim_task, choose_capacity, enqueue_task, heartbeat_task, retry_task, resume_task, transition_task
from support.global_state import project_state_dir_target
from agent_worker_evidence import create_worker_reservation, worker_reservation_matches
from agent_worktree_identity import (
    new_worktree_path,
    resolve_base_ref,
    validate_worker_worktree_identity,
)
from agent_worktree_session import create_worker_worktree
from workflow_dispatch_handoff import (
    build_worker_result_packet,
    execution_policy,
    prepare_worker_output_dir,
    worker_output_paths,
)
from workflow_dispatch_retry import DEFAULT_MAX_RETRIES, WorkerOutcome, read_worker_outcome, recovery_message
from workflow_dispatch_process import owns_task, run_worker
from workflow_dispatch_completion import evaluate_result, read_result
from workflow_dispatch_verification import requires_verification

LEASE_RENEWAL_SECONDS = 600


def execute_dispatch_manifest(
    manifest: Mapping[str, object],
    *,
    runner: Callable[[list[str]], int | WorkerOutcome] | None,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
    codex_argv: Callable[..., list[str]],
    build_handoff_prompt: Callable[..., str],
) -> int:
    if manifest.get("execution_mode") == "native":
        raise ValueError("Native dispatch requires the runtime's spawn tool; --execute cannot launch it.")
    if manifest.get("execution_mode") == "inline":
        raise ValueError(
            "Inline dispatch is a decision only and cannot execute work in the parent process; "
            "omit --execute or require isolation."
        )
    if runner is not None and _is_worktree_isolated(manifest):
        # The injected runner returns before ``_bind_worker_working_dir`` and so
        # never creates the worktree; letting it proceed would silently run an
        # isolated worker with ``--cd`` pointed at the shared checkout. Fail closed
        # before claiming any scheduler task -- isolated manifests must launch the
        # real worker process (runner=None) that binds a real git worktree.
        raise ValueError(
            "injected-runner execution cannot honor worktree isolation; "
            "isolated manifests must launch the real worker process"
        )
    handoff = manifest.get("handoff_state")
    profile = manifest.get("work_profile")
    if not isinstance(handoff, Mapping) or not isinstance(profile, Mapping):
        raise ValueError("Dispatch manifest is missing handoff state or work profile")
    project = Path(str(manifest["project"])).resolve()
    worker_checkout = None
    if manifest.get("worker_owned_verification") is True:
        if not _is_worktree_isolated(manifest):
            raise ValueError("Required worker verification needs an isolated checkout")
        required, spec = requires_verification(None, required_verification=manifest.get("required_verification"))
        if not required or spec.get("invalid") or not spec.get("selectors"):
            raise ValueError("Worker-owned verification requires a valid named test selection")
        worker_checkout = _bind_worker_working_dir(manifest, project)
    prepared = prepare_launch_handoff(
        manifest,
        handoff,
        execution_capsule_state=execution_capsule_state,
        isolated_worker_evidence=isolated_worker_evidence,
        verification_checkout=worker_checkout[0] if worker_checkout else None,
        verification=spec if worker_checkout else None,
    )
    prompt = build_handoff_prompt(
        str(manifest["command"]),
        str(manifest.get("request", "")),
        str(manifest["work_kind"]),
        prepared,
        non_authoring=str(manifest.get("authoring_policy", "")).startswith("read-only"),
        continuation_scope=str(manifest.get("continuation_scope", "")),
    )
    output_paths = worker_output_paths(prepared)
    prepared["worker_output_paths"] = output_paths
    last_message_path = Path(output_paths["last_message_path"])
    stream_log_path = Path(output_paths["stream_log_path"])
    argv = codex_argv(
        Path(str(manifest["project"])),
        profile,
        str(manifest["sandbox_mode"]),
        prompt,
        output_last_message=last_message_path,
    )
    scheduler_task = _claim_scheduler_task(manifest, prepared, project)
    heartbeat_interval = float(manifest.get("heartbeat_interval_seconds") or 0)
    task_context = {
        "task": scheduler_task,
        "prepared": prepared,
        "working_dir": str(project),
        "required_verification": manifest.get("required_verification"),
        "authoring_policy": str(manifest.get("authoring_policy") or ""),
    }
    task_context["allow_findings"] = (manifest.get("work_kind") in {"analysis", "review"}
                                     or manifest.get("command") in {"analysis", "review", "code-review"})
    if runner:
        return _run_scheduled_worker(argv, runner, project, scheduler_task, heartbeat_interval_seconds=heartbeat_interval,
                                     task_context=task_context)
    try:
        working_dir, worktree_path = worker_checkout or _bind_worker_working_dir(manifest, project)
    except BaseException:
        # The scheduler task is already marked running; a worktree-creation
        # failure here must transition it to a terminal failed state rather than
        # leaving it stuck as running before the worker loop's own guard begins.
        transition_task(project, str(scheduler_task["task_id"]), "failed")
        raise
    task_context["working_dir"] = str(working_dir)
    if worktree_path:
        # Rebind ``--cd`` to the freshly created worktree so the real worker
        # process writes inside its isolated tree, never the shared checkout.
        # The ephemeral project-trust override is allowed only after that exact
        # path has passed the same-repository linked-worktree identity check.
        argv = codex_argv(
            project,
            profile,
            str(manifest["sandbox_mode"]),
            prompt,
            working_dir,
            trusted_worktree=working_dir,
            output_last_message=last_message_path,
        )


    try:
        return _run_scheduled_worker(
            argv,
            lambda command: _run_spooled_worker(command, prepared, task_context["task"], worktree_path, project=project),
            project,
            scheduler_task,
            heartbeat_interval_seconds=heartbeat_interval,
            task_context=task_context,
        )
    except OSError as error:
        raise RuntimeError("Unable to start the delegated Codex worker") from error


def _run_spooled_worker(command, prepared, task, worktree_path, *, project):
    stream_log_path = Path(worker_output_paths(prepared)["stream_log_path"])
    prepare_worker_output_dir(prepared)
    with open(stream_log_path, "a", encoding="utf-8") as stream_log:
        offset = stream_log.buffer.tell()
        try:
            environment = worker_environment(prepared, task, worktree_path=worktree_path)
            proc = run_worker(command, env=environment, stdout=stream_log,
                              project=project, task=task,
                              execution_key=str(Path(worker_output_paths(prepared)["result_path"]).resolve()),
                              before_start=lambda: prepare_worker_output_dir(prepared, clear_stale=True))
        except OSError as error:
            outcome = WorkerOutcome(127, errno.errorcode.get(error.errno, "UNKNOWN"), replay_safe=True)
            build_worker_result_packet(prepared, returncode=127, recovery_action=recovery_message(outcome.action))
            raise
        except KeyboardInterrupt:
            build_worker_result_packet(prepared, returncode=130,
                                       recovery_action=recovery_message("honor_cancellation"))
            raise
    outcome = read_worker_outcome(proc.returncode, stream_log_path, offset)
    action = outcome.action
    if action == "retry_transient" and int(task.get("attempt", 1)) >= int(task.get("max_attempts", 1)):
        action = "retry_budget_exhausted"
    build_worker_result_packet(prepared, returncode=outcome.returncode,
                               recovery_action=recovery_message(action) if outcome.returncode else "")
    return outcome


def _is_worktree_isolated(manifest: Mapping[str, object]) -> bool:
    capability = manifest.get("capability_profile")
    if isinstance(capability, Mapping) and capability.get("working_dir_kind") == "worktree":
        return True
    return bool(manifest.get("isolation_required"))


def _bind_worker_working_dir(
    manifest: Mapping[str, object], project: Path
) -> tuple[Path, str]:
    """Create the isolated worktree fail-closed and return its bound working dir.

    Shared (non-isolated) workers keep the project checkout and an empty worktree
    marker. Isolated workers get a real ``git worktree add`` at the manifest's
    planned path; setup failure raises rather than falling back to the checkout.
    """

    if not _is_worktree_isolated(manifest):
        return project, ""
    worktree_path = str(manifest.get("worktree_path") or "") or str(
        new_worktree_path(project)
    )
    base_ref = resolve_base_ref(project)
    create_worker_worktree(project, base_ref, Path(worktree_path))
    verified = validate_worker_worktree_identity(project, Path(worktree_path))
    return verified, str(verified)


def _claim_scheduler_task(
    manifest: Mapping[str, object], prepared: Mapping[str, object], project: Path
) -> dict[str, object]:
    parent_evidence = Path(str(prepared["preflight_evidence"])).resolve()
    run_id = latest_run_id(project, parent_evidence) or uuid.uuid4().hex
    independent_slices = int(manifest.get("independent_slices") or 1)
    max_retries = int(manifest.get("max_retries", DEFAULT_MAX_RETRIES) or 0)
    requested_workers = int(manifest.get("requested_workers") or 1)
    capacity = choose_capacity(independent_slices, requested_workers)
    task = enqueue_task(
        project,
        run_id,
        priority=int(manifest.get("priority") or 0),
        independent_slices=independent_slices,
        requested_workers=requested_workers,
        max_retries=max_retries,
        partial_result_id=str(manifest.get("partial_result_id") or "") or None,
    )
    task_id = str(task["task_id"])
    # Claim only this dispatch's task; nothing else will run a task left queued here.
    if claim_task(project, task_id, capacity=capacity) is None:
        transition_task(project, task_id, "cancelled", expected_state="queued")
        raise RuntimeError("scheduler capacity is exhausted; worker was not started")
    return task


def _run_scheduled_worker(
    argv: list[str],
    runner: Callable[[list[str]], int | WorkerOutcome],
    project: Path,
    task: Mapping[str, object],
    *,
    heartbeat_interval_seconds: float = 0,
    task_context: dict[str, object] | None = None,
) -> int:
    if heartbeat_interval_seconds < 0:
        raise ValueError("heartbeat_interval_seconds must be non-negative")
    current_task = dict(task)
    while True:
        task_id = str(current_task["task_id"])
        worker_id = f"worker-{task_id}"
        attempt = int(current_task.get("attempt") or 1)
        events_enabled = heartbeat_interval_seconds > 0
        if not owns_task(project, current_task):
            return _reject_worker_result(task_context)
        raw = _run_worker_attempt(argv, runner, project, current_task, heartbeat_interval_seconds)
        outcome = raw if isinstance(raw, WorkerOutcome) else WorkerOutcome(raw)
        if outcome.returncode == 0 and task_context and task_context.get("prepared"):
            packet = read_result(task_context["prepared"])
            accepted, assessment = evaluate_result(
                packet,
                allow_findings=task_context.get("allow_findings") is True,
                prepared=task_context.get("prepared"),
                required_verification=task_context.get("required_verification"),
                working_dir=task_context.get("working_dir"),
                authoring_policy=str(task_context.get("authoring_policy") or ""),
            )
            task_context["completion_assessment"] = assessment
            if not accepted:
                if assessment.get("verification_required") and not assessment.get("satisfied"):
                    print(f"Worker verification rejected: {assessment['reason']}", file=sys.stderr)
                    if missing := assessment.get("missing_selectors"):
                        print(f"Tests still needing a current pass: {', '.join(missing)}", file=sys.stderr)
                    if command := assessment.get("retry_command"):
                        print(f"Run from the owning worker's active verification session:\n  {command}",
                              file=sys.stderr)
                outcome = WorkerOutcome(1, "WORKER_RESULT_REJECTED")
        result = outcome.returncode
        # Events follow the guarded transition: an attempt that stale recovery
        # already moved reports nothing over its newer owner.
        if result == 0:
            completed = transition_task(project, task_id, "completed", expected_state="running", expected_attempt=attempt)
            if completed is None:
                return _reject_worker_result(task_context)
            if events_enabled and completed is not None:
                emit_worker_result(
                    project,
                    run_id=str(current_task["run_id"]),
                    task_id=task_id,
                    worker_id=worker_id,
                    result_id=f"result-{uuid.uuid4().hex}",
                    attempt=attempt,
                )
            return result
        retried = _retry_failed_worker(project, current_task, outcome, events_enabled)
        if retried is None:
            return result
        claimed = claim_task(
            project,
            task_id,
            expected_attempt=int(retried["attempt"]),
            capacity=choose_capacity(
                int(retried.get("independent_slices") or 1),
                int(retried.get("requested_workers") or 1),
            ),
        )
        if not claimed or claimed.get("task_id") != task_id:
            transition_task(
                project,
                task_id,
                "failed",
                expected_state="queued",
                expected_attempt=int(retried.get("attempt") or 1),
            )
            return result
        current_task = claimed
        if task_context is not None:
            task_context["task"] = current_task


def _reject_worker_result(task_context):
    if task_context and task_context.get("prepared"):
        build_worker_result_packet(task_context["prepared"], returncode=130,
            recovery_action="The attempt lost execution ownership; inspect its existing result without replaying it.")
    return 130


def _run_worker_attempt(argv, runner, project, current_task, heartbeat_interval_seconds):
    task_id = str(current_task["task_id"])
    worker_id = f"worker-{task_id}"
    attempt = int(current_task.get("attempt") or 1)
    events_enabled = heartbeat_interval_seconds > 0
    stop_heartbeat = threading.Event()
    # The worker has no timeout because comparisons may legitimately run
    # long, so the lease tracks this process instead: it is renewed while
    # the worker runs, even without opt-in heartbeat events, and expires
    # for stale recovery only once this process is gone.
    lease_interval = heartbeat_interval_seconds if events_enabled else LEASE_RENEWAL_SECONDS
    if events_enabled:
        heartbeat_task(project, task_id, expected_attempt=attempt)
        emit_heartbeat(
            project,
            run_id=str(current_task["run_id"]),
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
        )

    def heartbeat_loop() -> None:
        while not stop_heartbeat.wait(lease_interval):
            if heartbeat_task(project, task_id, expected_attempt=attempt) is None:
                return
            if events_enabled:
                emit_heartbeat(
                    project,
                    run_id=str(current_task["run_id"]),
                    task_id=task_id,
                    worker_id=worker_id,
                    attempt=attempt,
                )

    heartbeat_thread = threading.Thread(target=heartbeat_loop, name=f"agent-heartbeat-{task_id}", daemon=True)
    heartbeat_thread.start()
    try:
        return runner(argv)
    except BaseException as error:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=max(1.0, heartbeat_interval_seconds))
        state = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
        owned = transition_task(project, task_id, state, expected_state="running", expected_attempt=attempt)
        if events_enabled and owned is not None:
            emit_event(
                project, "worker.cancelled" if state == "cancelled" else "worker.failure", state=state,
                run_id=str(current_task["run_id"]),
                task_id=task_id,
                worker_id=worker_id,
                attempt=attempt,
            )
        raise
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=max(1.0, heartbeat_interval_seconds))


def _retry_failed_worker(project, task, outcome, events_enabled):
    task_id, attempt = str(task["task_id"]), int(task.get("attempt") or 1)
    action = outcome.action
    retry = action == "retry_transient" and attempt < int(task.get("max_attempts") or 1)
    shown = "retry_budget_exhausted" if action == "retry_transient" and not retry else action
    print(f"Worker recovery: {shown}; attempt={attempt}; retry={'yes' if retry else 'no'}", file=sys.stderr)
    if retry:
        if heartbeat_task(project, task_id, expected_attempt=attempt) is None:
            return None
        try:
            time.sleep(outcome.delay(attempt))
        except BaseException:
            transition_task(project, task_id, "cancelled", expected_state="running", expected_attempt=attempt)
            raise
    state = "cancelled" if action == "honor_cancellation" else "failed"
    if transition_task(project, task_id, state, expected_state="running", expected_attempt=attempt) is None:
        return None
    if events_enabled and state != "cancelled":
        emit_worker_failure(project, run_id=str(task["run_id"]), task_id=task_id,
                            worker_id=f"worker-{task_id}", attempt=attempt)
    if not retry:
        return None
    requeue = resume_task if task.get("partial_result_id") else retry_task
    return requeue(project, task_id, expected_attempt=attempt)


def prepare_launch_handoff(
    manifest: Mapping[str, object],
    handoff: Mapping[str, object],
    *,
    execution_capsule_state: Callable[..., dict[str, object]],
    isolated_worker_evidence: Callable[..., Path],
    verification_checkout: Path | None = None,
    verification: dict[str, object] | None = None,
) -> dict[str, object]:
    prepared = dict(handoff)
    project = Path(str(manifest["project"])).resolve()
    rules = Path(str(prepared["rules"])).resolve()
    parent_evidence = Path(str(prepared["preflight_evidence"])).resolve()
    route = prepared.get("route_manifest")
    if not isinstance(route, Mapping):
        raise ValueError("Dispatch manifest is missing the parent route manifest")
    if verification_checkout is not None:
        slot = Path(str(prepared["worker_preflight_evidence"])).parent.name
        requested = project_state_dir_target(verification_checkout) / "workers" / slot / "preflight.json"
        worker_evidence = isolated_worker_evidence(
            verification_checkout, parent_evidence, requested, reserve=True
        )
        prepared.update(
            execution_capsule={"reusable": False, "invalidation_reasons": ["worker-owned verification"]},
            worker_preflight_evidence=str(worker_evidence),
            worker_gate_ledger=str(gate_evidence_path_for_preflight(worker_evidence)),
            worker_evidence_reserved=True,
            worker_reservation_token=create_worker_reservation(worker_evidence.parent),
            required_verification=verification,
            worker_owned_verification=True,
        )
        return prepared
    prepared["execution_capsule"] = execution_capsule_state(
        project,
        rules,
        parent_evidence,
        route,
        parent_context_reusable=prepared.get("parent_context_reusable") is True,
    )
    capsule = prepared["execution_capsule"]
    if isinstance(capsule, Mapping) and capsule.get("reusable"):
        return prepared
    worker_evidence = Path(str(prepared["worker_preflight_evidence"])).resolve()
    token = prepared.get("worker_reservation_token")
    if prepared.get("worker_evidence_reserved"):
        if not token or not worker_reservation_matches(worker_evidence.parent, str(token)):
            raise ValueError("Fallback worker reservation token does not match the reserved evidence path.")
    else:
        worker_evidence = isolated_worker_evidence(
            project, parent_evidence, worker_evidence, reserve=True
        )
        token = create_worker_reservation(worker_evidence.parent)
    prepared["worker_preflight_evidence"] = str(worker_evidence)
    prepared["worker_gate_ledger"] = str(gate_evidence_path_for_preflight(worker_evidence))
    prepared["worker_evidence_reserved"] = True
    prepared["worker_reservation_token"] = token
    return prepared


def worker_environment(
    handoff: Mapping[str, object],
    task: Mapping[str, object] | None = None,
    *,
    worktree_path: str = "",
) -> dict[str, str]:
    environment = dict(os.environ)
    if worktree_path:
        environment["MORU_WORKER_WORKTREE"] = worktree_path
    capsule = handoff.get("execution_capsule")
    if isinstance(capsule, Mapping) and capsule.get("reusable"):
        environment["MORU_PARENT_EVIDENCE_READONLY"] = "1"
        environment["MORU_CAPABILITY_ENFORCEMENT"] = "parent-evidence-readonly"
        return environment
    environment["MORU_WORKER_EVIDENCE"] = str(handoff["worker_preflight_evidence"])
    environment["MORU_WORKER_RESERVATION_TOKEN"] = str(
        handoff["worker_reservation_token"]
    )
    environment["MORU_CAPABILITY_ENFORCEMENT"] = "worker-evidence-and-state"
    if task and task.get("task_id"):
        environment["MORU_TASK_ID"] = str(task["task_id"])
    if task and task.get("partial_result_id"):
        environment["MORU_RESUME_RESULT_ID"] = str(task["partial_result_id"])
    return environment


def print_dispatch_manifest(manifest: Mapping[str, object], output_format: str) -> None:
    if output_format == "json":
        output = dict(manifest)
        output["codex_exec_argv"] = []
        output["codex_exec_command"] = ""
        output["execution_policy"] = execution_policy(str(manifest.get("execution_mode")))
        print(json.dumps(output, indent=2, sort_keys=True))
        return
    profile = manifest["work_profile"]
    assert isinstance(profile, Mapping)
    capsule = manifest["handoff_state"]["execution_capsule"]
    assert isinstance(capsule, Mapping)
    print("# Moru Core Codex Handoff\n")
    print(f"- Work kind: `{profile['work_kind']}`")
    print(f"- Codex model: `{profile['codex_model']}`")
    print(f"- Reasoning effort: `{profile['reasoning_effort']}`")
    print(f"- Authoring policy: `{manifest['authoring_policy']}`")
    print(f"- Execution mode: `{manifest['execution_mode']}`")
    print(f"- Execution capsule reusable: `{str(bool(capsule['reusable'])).lower()}`")
    print(f"- Selection: {manifest['selection_reason']}\n")
    if manifest.get("native_worker"):
        print("## Native Worker Arguments")
        print(json.dumps(manifest["native_worker"], ensure_ascii=False, indent=2))
    print("## Execution Boundary")
    print(execution_policy(str(manifest.get("execution_mode"))))
