"""Relocated offline review export without Python or provider access."""
import hashlib
import json
import subprocess
import sys


def check_behavior_review(native, entry, base, project, env):
    path = base / '검토 record.json'
    data = {'phase': 'finished', 'runtime_path': 'private runtime', 'runtime_digest': 'private digest',
            'status': 'ok', 'response': 'private response',
            'events': [{'event_type': 'review.record_initialized'},
                       {'event_type': 'review.finished', 'status': 'ok'}]}
    expected = {'schema_version': 1, 'runs': [{'provider': 'agy', 'case_id': 'case-1',
                'events': [{'kind': 'durable_record_written'}, {'kind': 'final', 'status': 'ok'}]}]}
    digits = str(getattr(sys, 'get_int_max_str_digits', lambda: 0)())
    def invoke(profile=digits):
        return subprocess.run([str(native), str(entry), '--behavior-review-export', str(path),
            'agy', 'case-1', profile], cwd=project, env={**env, 'MORU_HOOK_SOFT_FAIL': '1'},
            capture_output=True, stdin=subprocess.DEVNULL, timeout=8)
    path.write_text(json.dumps(data), encoding='utf-8')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    done = invoke()
    assert (done.returncode, done.stdout, done.stderr) == (0, (json.dumps(expected)+'\n').encode(), b''), done
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    data['events'][0]['content'] = 'private content'
    path.write_text(json.dumps(data), encoding='utf-8')
    done = invoke()
    assert done.returncode == 1 and not done.stdout and b'private' not in done.stderr, done
    done = invoke(str(int(digits) + 1))
    assert (done.returncode, done.stdout, done.stderr) == (78, b'', b''), done
    path.write_bytes(json.dumps(data).encode('utf-16'))
    done = invoke()
    assert (done.returncode, done.stdout, done.stderr) == (78, b'', b''), done
    return 4
