"""Owner: bounded worker completion policy and native compatibility adapter.
Allowed imports: stdlib, workflow_dispatch_verification; forbidden: scheduler mutations, providers and retries.
Caller: dispatch launch; tests: test_workflow_dispatch_completion (native parity).
"""
import json
import os
from pathlib import Path
import subprocess

from workflow_dispatch_verification import assess_completion_verification


def evaluate_result(
    packet,
    *,
    allow_findings=False,
    prepared=None,
    required_verification=None,
    working_dir=None,
    authoring_policy="",
):
    request = {'returncode': 0, 'allow_findings': allow_findings, 'packet': packet}
    native = os.environ.get('MORU_WORKER_COMPLETION_NATIVE')
    if native:
        try:
            result = subprocess.run([native, 'offline-worker', '--worker-completion-probe'],
                input=json.dumps(request, ensure_ascii=False, allow_nan=False).encode(),
                capture_output=True, timeout=5)
            packet_ok = (result.returncode == 0 and not result.stderr
                         and result.stdout == b'true\n')
        except (OSError, ValueError, subprocess.TimeoutExpired):
            packet_ok = False  # An explicitly selected candidate never falls back silently.
    else:
        packet_ok = _reference(request)

    assessment = assess_completion_verification(
        packet if isinstance(packet, dict) else None,
        prepared=prepared,
        required_verification=required_verification,
        allow_findings=allow_findings,
        working_dir=working_dir,
        authoring_policy=authoring_policy,
    )
    if not packet_ok:
        return False, {**assessment, "accepted": False, "reason": "worker_packet_rejected"}
    accepted = bool(assessment["satisfied"])
    return accepted, {**assessment, "accepted": accepted}


def accepts_result(
    packet,
    *,
    allow_findings=False,
    prepared=None,
    required_verification=None,
    working_dir=None,
    authoring_policy="",
):
    accepted, _assessment = evaluate_result(
        packet,
        allow_findings=allow_findings,
        prepared=prepared,
        required_verification=required_verification,
        working_dir=working_dir,
        authoring_policy=authoring_policy,
    )
    return accepted


def _reference(request):
    packet = request.get('packet')
    if request.get('returncode') != 0 or not isinstance(packet, dict):
        return False
    try:
        if len(json.dumps(packet, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')).encode()) > 4096:
            return False
    except (ValueError, TypeError):
        return False
    if packet.get('schema_version') != 'worker_result_v1':
        return False
    if any(not isinstance(packet.get(k), str) for k in ('summary', 'next_action')):
        return False
    if any(not isinstance(packet.get(k), list) for k in ('blockers', 'changed_paths', 'findings', 'checks')):
        return False
    if packet['blockers'] or any(not isinstance(p, str) for p in packet['changed_paths']):
        return False
    if (not isinstance(packet.get('artifacts'), dict)
            or any(not isinstance(p, str) for p in packet['artifacts'].values())
            or any(not isinstance(f, dict) for f in packet['findings'])):
        return False
    if not packet['checks'] or any(not isinstance(c, dict) or type(c.get('exit_code')) is not int
                                  or not -(2**63) <= c['exit_code'] < 2**63
                                  or not isinstance(c.get('outcome'), str) for c in packet['checks']):
        return False
    if packet.get('status') == 'findings':
        return request.get('allow_findings') is True
    return (packet.get('status') == 'ok'
            and all(c['exit_code'] == 0 and c['outcome'] == 'pass' for c in packet['checks']))


def read_result(prepared):
    from workflow_dispatch_handoff import worker_output_paths
    path = Path(worker_output_paths(prepared)['result_path'])
    try:
        if path.is_symlink():
            return None
        with path.open('rb') as stream:
            raw = stream.read(4097)
        return json.loads(raw, object_pairs_hook=_unique_fields) if len(raw) <= 4096 else None
    except (OSError, ValueError):
        return None


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_worker_result_field')
        result[key] = value
    return result
