"""Relocated guardian/gate protocol checks with no Python or compiler on PATH."""
import json
from pathlib import Path
import subprocess


def check_dispatch_guardian(native, entry, base, project, env):
    guardian = Path(env['MORU_HOME']) / 'scripts/workflow_dispatch_guardian.py'
    directory = base / 'guardian consumer 한글'
    directory.mkdir()
    initial = {'run_id': 'synthetic', 'task_id': 'task', 'attempt': 1,
               'execution_id': 'e' * 32, 'state': 'admitted'}
    requested = {'GUARDIAN_Z': 'z', 'GUARDIAN_A': 'a', 'PATH': ''}

    def invoke(name, command, code, expected, *, eof=False):
        receipt = directory / (name + '.json')
        receipt.write_text(json.dumps(initial))
        proc = subprocess.Popen([str(native), str(guardian), '--dispatch-guardian', str(receipt)],
            cwd=project, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)
        try:
            proc.stdin.write(json.dumps({'command': command, 'env': requested}).encode() + b'\n')
            proc.stdin.flush()
            if eof:
                proc.stdin.close()
            actual = proc.wait(timeout=5), proc.stdout.read(), proc.stderr.read()
            assert actual == (code, expected, b''), actual[:1]
            assert receipt.read_bytes() == json.dumps({**initial,
                'state': 'interrupted' if eof else 'finished', 'returncode': code}).encode()
            assert receipt.stat().st_mode & 0o777 == 0o600
            assert not list(directory.glob('.execution-*'))
        finally:
            if not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            proc.stdout.close()
            proc.stderr.close()

    invoke('ordered-env', ['/usr/bin/env'], 0, b'GUARDIAN_Z=z\nGUARDIAN_A=a\nPATH=\n')
    invoke('nonzero', ['/bin/sh', '-c', 'exit 7'], 7, b'')
    invoke('missing-exec', [str(directory / 'missing-program')], 127, b'')
    marker = directory / 'unexpected'
    invoke('eof', ['/bin/sh', '-c', 'printf bad > "$1"', 'owned', str(marker)], 130, b'', eof=True)
    assert not marker.exists()

    proc = subprocess.Popen([str(native), str(guardian), '--dispatch-exec-gate'],
        cwd=project, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(json.dumps(['/bin/sh', '-c', 'printf %s "$$"']).encode() + b'\n', timeout=5)
        assert (proc.returncode, out, err) == (0, str(proc.pid).encode(), b'')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
    for raw, code in ((b'{\n', 125), (b'{', 130)):
        done = subprocess.run([str(native), str(guardian), '--dispatch-exec-gate'],
            input=raw, cwd=project, env={**env, 'MORU_HOOK_SOFT_FAIL': '1'}, capture_output=True, timeout=5)
        assert (done.returncode, done.stdout, done.stderr) == (code, b'', b'')
    return 7
