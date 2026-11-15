"""Owner: owned worker process lifetime; allowed imports: stdlib/state reads.
Forbidden: retries, provider calls and scheduler writes. Caller: dispatch launch.
Tests: test_workflow_dispatch_process; verification: real-child cancellation.
"""
import os
import errno
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from agent_state_read import read_json_object, scheduler_path
from workflow_dispatch_execution import admit_execution


def owns_task(project, task):
    tasks = read_json_object(scheduler_path(project)).get("tasks", [])
    return isinstance(tasks, list) and any(
        isinstance(row, dict) and row.get("task_id") == task["task_id"]
        and row.get("state") == "running"
        and row.get("attempt") == task.get("attempt", 1) for row in tasks)


def _await_guardian(proc):
    deadline = time.monotonic() + 5
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired('worker guardian cleanup', 5)
        threading.Event().wait(.05)


def run_worker(command, *, env, stdout, project, task, execution_key=None, before_start=None):
    if not owns_task(project, task):
        return subprocess.CompletedProcess(command, 130)
    payload = json.dumps({'command': command, 'env': dict(env)}).encode() + b'\n'
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('worker_launch_payload_too_large')
    with admit_execution(project, task, execution_key) as (path, state, lock):
        if not shutil.which(command[0], path=env.get('PATH', os.defpath)):
            raise FileNotFoundError(errno.ENOENT, 'worker executable unavailable')
        if before_start:
            before_start()
        guardian = Path(__file__).with_name('workflow_dispatch_guardian.py')
        proc = subprocess.Popen([sys.executable, str(guardian), str(path)],
            stdin=subprocess.PIPE, stdout=stdout, stderr=subprocess.STDOUT,
            pass_fds=(lock,), close_fds=True, start_new_session=True)
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()  # Keep the only write end alive until exit/cancel.
            while proc.poll() is None:
                if not owns_task(project, task):
                    proc.stdin.close()
                    _await_guardian(proc)
                    return subprocess.CompletedProcess(command, 130)
                threading.Event().wait(.05)
            return subprocess.CompletedProcess(command, proc.returncode)
        finally:
            if not proc.stdin.closed:
                proc.stdin.close()
            _await_guardian(proc)  # EOF asks guardian to reap; never kill a stored PID.
