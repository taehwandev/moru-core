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

_GUARDIAN_BOOTSTRAP_ENV = {key: value for key, value in os.environ.items()
    if key in {'LC_ALL', 'LC_CTYPE', 'LANG', '__CF_USER_TEXT_ENCODING', 'HOME'}
    or key.startswith(('PYTHON', '_PYTHON'))}
_GUARDIAN_BOOTSTRAP_FLAGS = frozenset({'PYTHONUTF8', 'PYTHONCOERCECLOCALE',
    'PYTHONDONTWRITEBYTECODE', 'PYTHONNOUSERSITE'})


def _guardian_environment_profile(environment):
    """Only an established inherited bootstrap profile can omit Python."""
    if sys.getfilesystemencoding().lower() != 'utf-8':
        return False
    if any(name in sys.modules for name in ('sitecustomize', 'usercustomize')):
        return False
    for mapping in (os.environ, environment):
        if any(type(name) is str and name.startswith(('PYTHON', '_PYTHON'))
               and name not in _GUARDIAN_BOOTSTRAP_FLAGS and mapping[name]
               for name in mapping):
            return False
    names = {'LC_ALL', 'LC_CTYPE', 'LANG', '__CF_USER_TEXT_ENCODING',
             *_GUARDIAN_BOOTSTRAP_FLAGS}
    if environment.get('PYTHONNOUSERSITE') == '1':
        names.remove('PYTHONNOUSERSITE')
    elif environment.get('HOME') != _GUARDIAN_BOOTSTRAP_ENV.get('HOME'):
        return False
    if sys.platform == 'darwin' and not _GUARDIAN_BOOTSTRAP_ENV.get('__CF_USER_TEXT_ENCODING'):
        return False
    return all(environment.get(name) == _GUARDIAN_BOOTSTRAP_ENV.get(name) for name in names)


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


def _guardian_state_profile(state):
    if (type(state) is not dict
            or set(state) != {'run_id', 'task_id', 'attempt', 'execution_id', 'state'}
            or type(state['attempt']) is not int or not 0 < state['attempt'] < 2**63
            or state['state'] != 'admitted'):
        return False
    return all(type(state[name]) is str and state[name]
               for name in ('run_id', 'task_id', 'execution_id', 'state'))


def _guardian_command(guardian, path, command, environment, state):
    """Select once before spawn; stale or unsupported profiles keep Python."""
    legacy = [sys.executable, str(guardian), str(path)]
    if (not guardian.is_absolute() or not _guardian_state_profile(state) or type(command) not in (list, tuple)
            or type(environment) not in (dict, type(os.environ))
            or environment.get('MORU_LAUNCHER_BACKEND', 'auto') not in ('auto', 'rust')
            or not _guardian_environment_profile(environment)):
        return legacy
    try:
        words = [str(path), *command, *environment, *environment.values(),
                 *(state[name] for name in ('run_id', 'task_id', 'execution_id', 'state'))]
        for word in words:
            if type(word) is not str or '\0' in word:
                return legacy
            word.encode('utf-8')
        from support.native_launcher_install import artifact_plan
        plan = artifact_plan(guardian.parent.parent, guardian)
    except (OSError, ValueError, TypeError, UnicodeError):
        return legacy
    return ([str(plan['source']), str(guardian), '--dispatch-guardian', str(path)]
            if plan is not None else legacy)


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
        proc = subprocess.Popen(_guardian_command(guardian, path, command, env, state),
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
