"""Stable finding context and resolution backed by canonical local observations.

Owner: ReviewFindings; allowed imports: stdlib and read-only ExecutionReceipts;
forbidden: source/test execution, writes, providers and whole-task gate mutation.
Callers/tests: ReviewPacket, worker normalization; test_agent_review_findings
and test_agent_verification_receipts cover false claims and real executions.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

MAX_FINDINGS = 50
_CLOSED = frozenset({'closed', 'resolved', 'fixed', 'wontfix', 'false_positive'})
_LOW = frozenset({'low', 'info', 'nit', 'style'})
_SHA = re.compile(r'^[0-9a-f]{64}$')
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$')


def utf8_truncate(value, max_bytes):
    return value.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')


def _sha(value):
    return value.lower() if isinstance(value, str) and _SHA.fullmatch(value.lower()) else None


def _finding_id(item, file, line, severity, claim):
    value = item.get('id', item.get('finding_id'))
    if isinstance(value, str) and _ID.fullmatch(value):
        return value
    body = [file, item.get('symbol') or line, severity, claim]
    return 'f-' + hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest()[:12]


def _reference(value):
    if not isinstance(value, Mapping):
        return {}
    ref = {key: utf8_truncate(str(value[key]), limit) for key, limit in (
        ('kind', 32), ('outcome', 32), ('file', 160), ('finding_id', 64),
        ('selector', 240), ('receipt_ref', 160), ('execution_id', 64)) if value.get(key)}
    for key in ('exit_code', 'tests_run', 'executed'):
        if type(value.get(key)) is int:
            ref[key] = value[key]
    if _sha(value.get('source_sha256')):
        ref['source_sha256'] = _sha(value['source_sha256'])
    return ref


def _verification(value):
    if not isinstance(value, Mapping):
        return {}
    result = _reference(value)
    for key in ('before_fail', 'after_pass'):
        if key in value:
            result[key] = _reference(value[key])
    return result


def _matches_reference(ref, fact, entry, *, before=False):
    if not fact or fact.get('ok') is not True:
        return 'unobserved_verification'
    if ref.get('execution_id', fact.get('id')) != fact.get('id'):
        return 'mismatched_execution_id'
    if ref.get('finding_id', entry['id']) != entry['id']:
        return 'mismatched_finding_id'
    if ref.get('file', entry['file']) != entry['file']:
        return 'mismatched_verification_file'
    binding = entry['source_binding']
    expected = binding.get('original_sha256' if before else 'current_sha256')
    if ref.get('source_sha256', expected) != expected:
        return 'stale_verification_source'
    if before:
        if fact.get('successful') is not False or ref.get('outcome') == 'pass' or ref.get('exit_code') == 0:
            return 'before_fail_did_not_fail'
    else:
        if fact.get('successful') is not True and fact.get('kind') != 'source_review':
            return 'unobserved_verification'
        if ref.get('outcome', 'pass') != 'pass' or ref.get('exit_code', 0) != 0:
            return 'verification_not_passing'
        if any(ref.get(key, 1) <= 0 for key in ('tests_run', 'executed')):
            return 'skip_only_or_zero_executed'
    return None


def _resolution(entry, observed):
    claimed = entry['claimed_state']
    binding = entry['source_binding']
    if claimed not in _CLOSED:
        return ('reopened' if claimed == 'reopened' else
                'stale' if binding['status'] in ('changed', 'missing_source') else 'open'), None
    if not binding.get('current_sha256') or binding['status'] in ('missing_source', 'unverified_file'):
        return 'reopened', 'missing_source_binding'
    verification = entry.get('verification') or {}
    before = verification.get('before_fail')
    if before is not None:
        reason = _matches_reference(before, observed.get('before_fail'), entry, before=True)
        if reason:
            return 'reopened', reason
    ref = verification.get('after_pass', verification)
    reason = _matches_reference(ref, observed.get('after_pass'), entry)
    if reason:
        return 'reopened', reason
    if ref.get('kind') == 'source_review' and (entry.get('reproducible') or
            entry['severity'] not in _LOW and claimed not in ('false_positive', 'wontfix')):
        return 'reopened', 'test_verification_required'
    return 'resolved', None


def _normalize(item, snapshots, observed, claim_bytes, compact):
    file = utf8_truncate(str(item.get('file') or '').strip(), 160)
    line = item.get('line', 0) if type(item.get('line')) is int else 0
    severity = utf8_truncate(str(item.get('severity') or 'info').lower(), 32)
    full_claim = str(item.get('claim') or '')
    fid = _finding_id(item, file, line, severity, full_claim)
    raw_binding, snap = item.get('source_binding') or {}, snapshots.get(file) or {}
    raw_binding = raw_binding if isinstance(raw_binding, Mapping) else {}
    current = _sha(snap.get('sha256'))
    original = _sha(raw_binding.get('original_sha256') or item.get('original_sha256') or item.get('source_sha256')) or current
    status = ('unverified_file' if not snap or snap.get('status') == 'unverified_file' else
              'missing_source' if snap.get('status') in ('missing', 'deleted') or not current else
              'changed' if original != current else 'unchanged')
    binding = {'status': status}
    if original:
        binding['original_sha256'] = original
    if current:
        binding['current_sha256'] = current
    claimed = utf8_truncate(str(item.get('claimed_state') or item.get('resolution') or
        item.get('state') or item.get('status') or 'open').lower(), 32)
    entry = {'id': fid, 'file': file, 'line': max(0, line), 'severity': severity,
             'claim': utf8_truncate(full_claim, claim_bytes), 'claimed_state': claimed,
             'source_binding': binding}
    if item.get('reproducible') is True or item.get('requires_verification') is True:
        entry['reproducible'] = True
    if item.get('symbol'):
        entry['symbol'] = utf8_truncate(str(item['symbol']), 120)
    verification = _verification(item.get('verification'))
    if verification:
        entry['verification'] = verification
    facts = observed.get(fid) or {}
    state, reason = _resolution(entry, facts)
    entry['state'] = state
    if reason:
        entry['reopen_reason'] = reason
    if state == 'resolved':
        after = facts['after_pass']
        entry['resolution_evidence'] = {key: after[key] for key in
            ('id', 'kind', 'tests_run', 'inputs_sha256') if key in after}
    if compact and claimed == state:
        entry.pop('claimed_state')
    return entry


def normalize_findings(raw_findings, *, claim_bytes=240, max_findings=MAX_FINDINGS,
                       source_snapshots=None, compact=False, observations=None):
    """Normalize claims; only the caller's separately observed facts can close them."""
    if not isinstance(raw_findings, (list, tuple)):
        return []
    result, seen = [], set()
    for raw in raw_findings[:max_findings]:
        item = raw if isinstance(raw, Mapping) else {'claim': str(raw), 'severity': 'info'}
        entry = _normalize(item, source_snapshots or {}, observations or {}, claim_bytes, compact)
        if entry['id'] in seen:
            raise ValueError('duplicate finding identity')
        seen.add(entry['id'])
        result.append(entry)
    return result


def build_re_review_summary(findings, *, provenance, changed_repo_paths=None):
    counts = {key: 0 for key in ('open', 'reopened', 'stale', 'resolved')}
    unresolved, reopened, stale, paths = [], [], [], []
    for entry in findings:
        state, fid = entry['state'], entry['id']
        counts[state] += 1
        if state != 'resolved':
            unresolved.append(fid)
            if state == 'reopened':
                reopened.append(fid)
            binding = entry.get('source_binding') or {}
            if binding.get('status') in ('changed', 'missing_source') or state == 'stale':
                stale.append(fid)
            if entry['file'] and (entry['file'] in (changed_repo_paths or set()) or
                    binding.get('status') in ('changed', 'missing_source')):
                paths.append(entry['file'])
    return {'provenance': provenance, 'total': len(findings), 'counts': counts,
            'unresolved_ids': unresolved, 'reopened_ids': reopened,
            'stale_ids': stale, 'changed_paths': list(dict.fromkeys(paths))}


def _observe(reader, project, entry, ref, *, before=False):
    from support.global_state import project_state_dir_target
    run_id = ref.get('receipt_ref', '')
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        return {'ok': False}
    path = project_state_dir_target(project).resolve() / 'runs' / run_id / 'preflight.json'
    if ref.get('kind') == 'source_review' and not before:
        return reader.review(path, entry['file'])
    execution_id, selector = ref.get('execution_id', ''), ref.get('selector', '')
    if not re.fullmatch(r'[0-9a-f]{32}', execution_id) or not selector:
        return {'ok': False}
    return reader.inspect(path, execution_id=execution_id, selectors=[selector],
                          historical_failure=before)


def collect_packet_findings(project, raw, read_source, *, claim_bytes=300, max_findings=50,
                            changed_repo_paths=None):
    """Read guarded source and registered observations without executing a check."""
    from pathlib import Path
    from agent_verification_receipts import ExecutionReceipts
    snapshots = {}
    for item in raw[:max_findings]:
        file = item.get('file') if isinstance(item, Mapping) else ''
        if isinstance(file, str) and file and file not in snapshots:
            snapshots[file] = read_source(file)
    first = normalize_findings(raw, claim_bytes=claim_bytes, max_findings=max_findings,
                               source_snapshots=snapshots)
    reader, observations = ExecutionReceipts(project), {}
    for entry in first:
        if entry['claimed_state'] not in _CLOSED:
            continue
        verification = entry.get('verification') or {}
        after = verification.get('after_pass', verification)
        observation = {'after_pass': _observe(reader, Path(project), entry, after)}
        if 'before_fail' in verification:
            observation['before_fail'] = _observe(reader, Path(project), entry, verification['before_fail'], before=True)
        observations[entry['id']] = observation
    normalized = normalize_findings(raw, claim_bytes=claim_bytes, max_findings=max_findings,
                                   source_snapshots=snapshots, observations=observations)
    summary = build_re_review_summary(normalized, provenance='registered_observations_and_caller_claims',
                                     changed_repo_paths=changed_repo_paths)
    return normalized, summary
