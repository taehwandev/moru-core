"""Run a bounded unittest selection and record observed tests evidence.

Owner: optional test execution/receipt integration. Imports: existing session,
ledger and input snapshot contracts. No shell, publishing or approval bypass.
Caller: agent-hook verify; verification: test_agent_verification_hook.
"""

from __future__ import annotations

import json
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from time import monotonic

from agent_gate_evidence import record_many_gate_evidence
from agent_gate_reuse import GateEvidenceReuse
from agent_hook_gate_records import _gate_progress, preflight_evidence_path, record_hook_gate
from agent_hook_runtime import finish_with_result
from agent_repair_ledger import (
    claim_verification_attempt, clear_verification_attempt,
    failure_signature, record_failure_checkpoints,
)
from agent_runtime_session import resolve_runtime_evidence, runtime_session


def verification_hook(args) -> int:
    """Execute only inside the current bound run; never infer success from prose."""
    try:
        path = preflight_evidence_path(args)
        session = runtime_session()
        bound = resolve_runtime_evidence(args.project, session) if session else None
        if not bound or Path(bound).resolve() != path.resolve():
            raise ValueError("verify requires this session's active registered run")
        preflight = json.loads(path.read_text(encoding="utf-8"))
        if (preflight.get("project") != str(args.project.resolve())
                or preflight.get("rules") != str(args.rules.resolve())
                or "tests" not in (preflight.get("route") or {}).get("gates", [])):
            raise ValueError("verify requires matching project/rules and a tests gate")
        command = unittest_command(args)
        return _verify_selection(args, path, preflight, command)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"FAIL verify: {error}", file=sys.stderr)
        return 1


def _verify_selection(args, path, preflight, command):
    check = " ".join(command)
    candidate = {"gate": "tests", "status": "SUCCESS", "source": "execution",
                 "evidence": "observed unittest process result",
                 "fields": {"check": check, "result": "pending"}}
    before = _snapshot(preflight, candidate)
    execution_id = uuid.uuid4().hex
    binding = {"schema_version": 1, "id": execution_id, "argv": command,
               "snapshot": before["reuse_snapshot"]}
    pending = {"check": check, "result": "incomplete",
               "execution_started": json.dumps(binding, ensure_ascii=False, separators=(",", ":"))}
    # A crash must leave scoped negative evidence. The ledger writer checks live ownership.
    record_hook_gate(args, "tests", "verification started; no completed result",
                     pending, "execution", "FAIL")
    identity = hashlib.sha256(json.dumps({
        "command": command, "timeout": args.verify_timeout,
        "inputs": {key: value for key, value in before["reuse_snapshot"].items() if key != "session"},
        "retry_reason": getattr(args, "retry_reason", "").strip(),
    }, sort_keys=True).encode()).hexdigest()
    attempt = claim_verification_attempt(evidence_path=path, preflight=preflight, identity=identity)
    if not attempt:
        result = "no_progress: two attempts without a verified pass for unchanged inputs; no process started"
        record_hook_gate(args, "tests", result, {**pending, "result": result}, "execution", "FAIL")
        return finish_with_result(
            "verify", False, [result], getattr(args, "output", None), {}, getattr(args, "repair_cycle", 0),
            verification_failure="no_progress",
        )
    started = monotonic()
    observed = {}
    code, count, passed = execute_unittest(command, args.project, args.verify_timeout, observed=observed)
    after = _snapshot(preflight, candidate)
    stable = before["reuse_snapshot"] == after["reuse_snapshot"]
    success = code == 0 and passed and count > 0 and stable
    result = (f"exit={code}; tests={count}; elapsed={monotonic() - started:.3f}s; "
              f"inputs_unchanged={stable}")
    after["fields"]["result"] = result
    after["fields"]["execution"] = json.dumps({
        **binding,
        "exit_code": code, "tests_run": count, "successful": passed,
        "inputs_unchanged": stable,
        "passed_ids": observed.get("passed_ids", []),
        "failed_ids": observed.get("failed_ids", []),
        "passed_selectors": observed.get("passed_selectors", []),
        "failed_selectors": observed.get("failed_selectors", []),
        "ids_complete": observed.get("ids_complete", False),
    }, ensure_ascii=False, separators=(",", ":"))
    after["status"] = "SUCCESS" if success else "FAIL"
    if not success:
        after.pop("reuse_snapshot", None)
    record_many_gate_evidence(evidence_path=path, preflight=preflight, records=[after])
    if success:
        clear_verification_attempt(evidence_path=path, preflight=preflight, identity=identity, attempt=attempt)
    else:
        # Keep real failure evidence available if a framework defect is found.
        # Elapsed time is left out so a recurring failure keeps its signature.
        signature = failure_signature([f"verify exit={code}; tests={count}; inputs_unchanged={stable}"])
        record_failure_checkpoints(evidence_path=path, preflight=preflight, checkpoints=["tests"],
                                   signature=signature, checkpoint_signatures={"tests": signature})
    progress, guidance = _verification_progress(args, path, preflight, success)
    return finish_with_result(
        "verify", success,
        [result, *guidance,
         f"Execution record: receipt_ref={preflight.get('agent_run_id', '')}; execution_id={execution_id}",
         f"Remaining route gates: {progress['remaining_gates']}"],
        getattr(args, "output", None), {"gate_evidence": after, "gate_progress": progress,
            "execution_reference": {"receipt_ref": preflight.get('agent_run_id', ''), 'execution_id': execution_id}},
        getattr(args, "repair_cycle", 0),
        verification_failure="" if success else "task_failure",
    )


def _verification_progress(args, path, preflight, success):
    progress = _gate_progress(args)
    if not success:
        return progress, ["This selection did not pass."]
    from agent_next_action import pending_observed_batch
    from agent_next_verification import build_verify_command
    from support.stable_launcher import stable_launcher_path

    try:
        count, batch = pending_observed_batch(args.project, args.rules, path)
    except (OSError, ValueError, RuntimeError):
        return {"remaining_gates": None, "ledger_complete": False}, [
            "This selection passed. Check the next action to confirm remaining verification."]
    if not count:
        return progress, ["Pass recorded for this selection. Final review still applies."]
    remaining = set(progress["remaining_gates"] or []) | {"tests"}
    if progress["remaining_gates"] is not None:
        progress["remaining_gates"] = [gate for gate in preflight["route"]["gates"] if gate in remaining]
    progress.update(ledger_complete=False, pending_test_targets=count)
    command = build_verify_command(str(stable_launcher_path()), args.project, args.rules, path, batch)
    progress["next_verify_command"] = command
    return progress, [f"This selection passed. {count} test targets remain.",
                      f"Next verification batch: {command}"]


def _snapshot(preflight, candidate):
    record = GateEvidenceReuse(preflight).prepare([candidate])[0]
    if not record.get("reuse_snapshot"):
        raise ValueError("verification input snapshot unavailable")
    return record


def unittest_command(args) -> list[str]:
    directory = (args.project / args.test_directory).resolve()
    if not directory.is_relative_to(args.project.resolve()) or not directory.is_dir():
        raise ValueError("test directory must exist inside the project")
    pattern = args.test_pattern
    selectors = getattr(args, 'test_selector', [])
    if selectors:
        from agent_unittest_selection import UnittestSelection
        if pattern != 'test_*.py':
            raise ValueError('named selectors cannot be combined with a discovery pattern')
        pattern = UnittestSelection.encode(directory, selectors)
    if not selectors and (not pattern or any(char in pattern for char in ("/", "\\", "\n")) or not pattern.endswith(".py")):
        raise ValueError("test pattern must be a Python filename glob")
    if args.verify_timeout <= 0:
        raise ValueError("verify timeout must be positive")
    runner = Path(__file__).with_name("agent_unittest_result.py")
    project_python = args.project / ".venv" / "bin" / "python"
    if project_python.parent.parent.exists():
        if not project_python.is_file() or not os.access(project_python, os.X_OK):
            raise ValueError("project .venv Python is unavailable; use the project test runner")
        python = str(project_python)
    else:
        python = sys.executable
    return [python, "-B", str(runner), str(args.project.resolve()), str(directory), pattern]


def execute_unittest(command: list[str], project: Path, timeout: float,
                     extra_env: dict[str, str] | None = None,
                     process_admission=None, observed: dict | None = None) -> tuple[int, int, bool]:
    # Spool output rather than retaining an unbounded child log in memory or
    # the ledger. Print a bounded tail for diagnosis; persist only result facts.
    if process_admission is not None and os.name != "posix":
        raise ValueError("guarded unittest execution requires POSIX process groups")
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryFile() as output:
        receipt = Path(temporary) / "result.json"
        try:
            environment = None if extra_env is None else {**os.environ, **extra_env}
            if process_admission is not None:
                code = _execute_admitted([*command, str(receipt)], project, timeout,
                                         environment, output, process_admission)
            else:
                process = subprocess.run([*command, str(receipt)], cwd=project, stdout=output, stderr=output,
                                         timeout=timeout, check=False, env=environment)
                code = process.returncode
        except subprocess.TimeoutExpired:
            code = 124
        output.seek(0, 2)
        output.seek(max(0, output.tell() - 16384))
        tail = output.read().decode("utf-8", errors="replace")
        print(tail, end="" if tail.endswith("\n") else "\n")
        try:
            if receipt.is_symlink():
                raise ValueError("invalid unittest receipt path")
            with receipt.open('rb') as stream:
                payload = stream.read(262145)
            if len(payload) > 262144:
                raise ValueError("oversized unittest receipt")
            result = json.loads(payload)
            count = result["tests_run"]
            passed = result["successful"]
            if type(count) is not int or count < 0 or type(passed) is not bool:
                raise ValueError("invalid unittest result")
            if observed is not None:
                for key in ('passed_ids', 'failed_ids'):
                    values = result.get(key, [])
                    observed[key] = values if (isinstance(values, list) and len(values) <= 1024
                        and all(isinstance(value, str) and len(value.encode('utf-8')) <= 512 for value in values)
                        and sum(len(value.encode('utf-8')) for value in values) <= 65536) else []
                observed['ids_complete'] = result.get('ids_complete') is True
                pattern = command[-1]
                allowed = json.loads(pattern[len('@selectors:'):]) if pattern.startswith('@selectors:') else []
                for key in ('passed_selectors', 'failed_selectors'):
                    labels = result.get(key, [])
                    observed[key] = labels if (isinstance(labels, list) and len(labels) <= 64
                        and all(isinstance(label, str) and label in allowed for label in labels)) else []
        except (OSError, ValueError, KeyError, TypeError):
            count, passed = 0, False
        return code, count, passed


def _execute_admitted(command, project, timeout, environment, output, process_admission):
    from support.native_unittest_admission import admission_bootstrap

    deadline = monotonic() + timeout
    environment = {**(os.environ if environment is None else environment), "MORU_UNITTEST_ADMISSION": "1"}
    # Exact native bytes or isolated/no-site trusted Python starts before admission;
    # neither loads selected-interpreter startup hooks or project code in this phase.
    runner = Path(__file__).resolve().with_name("agent_unittest_result.py")
    bootstrap = admission_bootstrap(command, runner, environment)
    process = subprocess.Popen(bootstrap, cwd=project, stdout=output, stderr=output,
                               stdin=subprocess.PIPE, start_new_session=True, env=environment)
    try:
        process_admission(process.pid)
        if deadline <= monotonic():
            raise subprocess.TimeoutExpired(command, timeout)
        process.stdin.write(b"\x01")
        process.stdin.flush()
        process.stdin.close()
        return process.wait(timeout=max(0, deadline - monotonic()))
    except BaseException:
        # Only this Popen owns the newly created session/group. No name lookup
        # or caller-supplied PID can broaden the cleanup target.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    finally:
        if not process.stdin.closed:
            process.stdin.close()
