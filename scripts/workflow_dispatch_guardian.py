"""Owner: ephemeral lifeline guardian and gated child exec.
Allowed imports: stdlib, execution receipts; forbidden: providers, scheduler writes,
retries or signaling cached PIDs. Caller: dispatch process; tests: real process
cancellation and crash scenarios in test_workflow_dispatch_process.
"""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

from workflow_dispatch_execution import save_receipt

LIMIT = 2 * 1024 * 1024


def _parent_closed():
    return bool(select.select([0], [], [], 0)[0]) and not os.read(0, 1)


def _stop(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # This live child group has already exited.
    try:
        proc.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        pass  # Escalate only this guardian's own group below.
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # No remaining group members.
        proc.wait()


def _gate():
    raw = sys.stdin.buffer.readline(LIMIT + 1)
    if not raw.endswith(b'\n') or len(raw) > LIMIT:
        return 130  # EOF before durable go means no command executes.
    command = json.loads(raw)
    fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(fd, 0)
    os.close(fd)
    try:
        os.execvpe(command[0], command, os.environ)
    except OSError:
        return 127  # Never echo a command, environment or exception payload.


def _guard(path):
    raw = sys.stdin.buffer.readline(LIMIT + 1)
    if not raw.endswith(b'\n') or len(raw) > LIMIT:
        return 130
    request = json.loads(raw)
    state = json.loads(path.read_text())
    if _parent_closed():
        save_receipt(path, {**state, 'state': 'interrupted', 'returncode': 130})
        return 130
    proc = subprocess.Popen([sys.executable, __file__, '--exec-gate'],
        stdin=subprocess.PIPE, env=request['env'], start_new_session=True, close_fds=True)
    stopped = False
    try:
        save_receipt(path, {**state, 'state': 'running'})
        if _parent_closed():
            stopped = True
        else:
            proc.stdin.write(json.dumps(request['command']).encode() + b'\n')
            proc.stdin.close()
            while proc.poll() is None:
                if select.select([0], [], [], .1)[0] and not os.read(0, 1):
                    stopped = True
                    break
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        _stop(proc)  # Includes surviving descendants after a normal leader exit.
    code = 130 if stopped else (proc.returncode if proc.returncode >= 0 else 128 - proc.returncode)
    save_receipt(path, {**state, 'state': 'interrupted' if stopped else 'finished', 'returncode': code})
    return code


if __name__ == '__main__':
    try:
        result = _gate() if sys.argv[1] == '--exec-gate' else _guard(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError):
        result = 125  # Receipt stays uncertain; never replay after guardian failure.
    sys.exit(result)
