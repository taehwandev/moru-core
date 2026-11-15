"""Owner: durable worker execution admission (no PID signaling or execution).
Allowed imports: stdlib and scheduler path; forbidden: providers and retries.
Callers/tests: dispatch process, guardian, test_workflow_dispatch_execution.
Verification: locked, atomic content-free receipts fence uncertain replay.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from agent_state_read import scheduler_path

_FIELDS = {'run_id', 'task_id', 'attempt', 'execution_id', 'state', 'returncode'}


def save_receipt(path, state):
    if set(state) - _FIELDS or path.is_symlink():
        raise ValueError('invalid_execution_receipt')
    fd, name = tempfile.mkstemp(prefix='.execution-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def admit_execution(project, task, key=None):
    identity = {k: task[k] for k in ('run_id', 'task_id', 'attempt')}
    key = key or json.dumps([identity['run_id'], identity['task_id']])
    directory = scheduler_path(project).parent / 'worker-executions'
    if directory.is_symlink():
        raise ValueError('invalid_execution_directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(key.encode()).hexdigest() + '.json')
    lock = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('worker_execution_in_progress') from error
        if path.is_symlink():
            raise ValueError('invalid_execution_receipt')
        if path.exists():
            with path.open('rb') as stream:
                raw = stream.read(8193)
            prior = json.loads(raw) if len(raw) <= 8192 else None
            if (not isinstance(prior, dict) or set(prior) - _FIELDS
                    or not isinstance(prior.get('execution_id'), str) or not prior['execution_id']
                    or prior.get('run_id') != identity['run_id']
                    or prior.get('task_id') != identity['task_id']
                    or type(prior.get('attempt')) is not int
                    or prior['attempt'] + 1 != identity['attempt']
                    or prior.get('state') != 'finished'
                    or type(prior.get('returncode')) is not int or prior['returncode'] == 0):
                raise ValueError('worker_execution_needs_inspection')
        state = {**identity, 'execution_id': uuid.uuid4().hex, 'state': 'admitted'}
        save_receipt(path, state)
        yield path, state, lock
    finally:
        # The guardian inherits this description. Do not LOCK_UN while it lives.
        os.close(lock)
