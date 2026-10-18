"""Run a bounded unittest selection and record observed tests evidence.

Owner: optional test execution/receipt integration. Imports: existing session,
ledger and input snapshot contracts. No shell, publishing or approval bypass.
Caller: agent-hook verify; verification: test_agent_verification_hook.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from time import monotonic

from agent_gate_evidence import record_many_gate_evidence
from agent_gate_reuse import GateEvidenceReuse
from agent_hook_gate_records import _gate_progress, preflight_evidence_path, record_hook_gate
from agent_hook_runtime import finish_with_result
from agent_repair_ledger import failure_signature, record_failure_checkpoints
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
        check = " ".join(command)
        # Clear an older pass before execution, including interruption/timeout.
        # The normal ledger writer enforces live ownership before any test runs.
        record_hook_gate(args, "tests", "verification started; no completed result",
                         {"check": check, "result": "incomplete"}, "execution", "FAIL")
        candidate = {"gate": "tests", "status": "SUCCESS", "source": "execution",
                     "evidence": "observed unittest process result",
                     "fields": {"check": check, "result": "pending"}}
        before = _snapshot(preflight, candidate)
        started = monotonic()
        code, count, passed = execute_unittest(command, args.project, args.verify_timeout)
        after = _snapshot(preflight, candidate)
        stable = before["reuse_snapshot"] == after["reuse_snapshot"]
        success = code == 0 and passed and count > 0 and stable
        result = (f"exit={code}; tests={count}; elapsed={monotonic() - started:.3f}s; "
                  f"inputs_unchanged={stable}")
        after["fields"]["result"] = result
        after["status"] = "SUCCESS" if success else "FAIL"
        if not success:
            after.pop("reuse_snapshot", None)
        record_many_gate_evidence(evidence_path=path, preflight=preflight, records=[after])
        if not success:
            # The failure output points at repair-verify, which only accepts a
            # recorded failed checkpoint; without this the printed recovery
            # path ended in `checkpoint_not_failed`.
            # Elapsed time is left out so a recurring failure keeps its signature.
            signature = failure_signature([f"verify exit={code}; tests={count}; inputs_unchanged={stable}"])
            record_failure_checkpoints(evidence_path=path, preflight=preflight, checkpoints=["tests"],
                                       signature=signature, checkpoint_signatures={"tests": signature})
        progress = _gate_progress(args)
        return finish_with_result(
            "verify", success,
            [result, "Tests gate recorded for this selection; do not repeat gate-batch. Final review still applies.",
             f"Remaining route gates: {progress['remaining_gates']}"],
            getattr(args, "output", None), {"gate_evidence": after, "gate_progress": progress},
            getattr(args, "repair_cycle", 0),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"FAIL verify: {error}", file=sys.stderr)
        return 1


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
    if not pattern or any(char in pattern for char in ("/", "\\", "\n")) or not pattern.endswith(".py"):
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
                     process_admission=None) -> tuple[int, int, bool]:
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
            result = json.loads(receipt.read_text(encoding="utf-8"))
            count = result["tests_run"]
            passed = result["successful"]
            if type(count) is not int or count < 0 or type(passed) is not bool:
                raise ValueError("invalid unittest result")
        except (OSError, ValueError, KeyError, TypeError):
            count, passed = 0, False
        return code, count, passed


def _execute_admitted(command, project, timeout, environment, output, process_admission):
    deadline = monotonic() + timeout
    environment = {**(os.environ if environment is None else environment), "MORU_UNITTEST_ADMISSION": "1"}
    # Only the trusted runtime starts before admission. Isolated/no-site mode
    # prevents .pth, sitecustomize and PYTHONPATH code from running in this phase.
    runner = Path(__file__).resolve().with_name("agent_unittest_result.py")
    bootstrap = [sys.executable, "-I", "-S", str(runner), *command]
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
