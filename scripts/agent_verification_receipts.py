"""Read-only execution facts from a registered verification run.

Owner: ExecutionReceipts; allowed imports: stdlib, canonical registry/ledger and
input-snapshot readers; forbidden: test/provider execution, writes, settlement.
Callers/tests: dispatch completion, review packets and next advice;
test_agent_verification_receipts exercises actual verification and bad bindings.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agent_gate_evidence import (gate_evidence_path_for_preflight,
    merge_gate_evidence_from_ledger, read_gate_evidence_ledger)
from agent_gate_reuse import GateEvidenceReuse
from agent_registry_read import active_run_bindings
from agent_route_state import route_fingerprint
from agent_state_read import evidence_binding_key
from support.global_state import project_state_dir_target


_ID = re.compile(r'^[0-9a-f]{32}$')


class _ReceiptError(ValueError):
    pass


def _bounded(path, limit):
    if path.is_symlink() or path.absolute() != path.resolve():
        raise _ReceiptError('noncanonical_verification_path')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise _ReceiptError('oversized_verification_evidence')
    return data


def _bound(project, rules, path):
    state = project_state_dir_target(project).resolve()
    if not path.resolve().is_relative_to(state):
        raise _ReceiptError('foreign_verification_path')
    run = active_run_bindings(project, frozenset({'running', 'completed'})).get(
        evidence_binding_key(project, path))
    if not run:
        raise _ReceiptError('unregistered_verification_run')
    raw = _bounded(path, 1024 * 1024)
    preflight = json.loads(raw)
    if not isinstance(preflight, dict) or not isinstance(preflight.get('rules'), str):
        raise _ReceiptError('invalid_verification_binding')
    rules = Path(preflight['rules']).resolve() if rules is None else rules
    if (not isinstance(preflight, dict) or preflight.get('agent_run_id') != run.get('run_id')
            or preflight.get('project') != str(project) or preflight.get('rules') != str(rules)):
        raise _ReceiptError('foreign_preflight_binding')
    route, session = preflight.get('route') or {}, preflight.get('runtime_session') or {}
    if (not isinstance(route, dict) or not set(route.get('gates', [])) & {'tests', 'review hook'}
            or run.get('route_fingerprint') != route_fingerprint(route)
            or not isinstance(session, dict) or not session.get('runtime') or not session.get('session_id')
            or session.get('resume_generation', 0) != run.get('resume_generation', 0)):
        raise _ReceiptError('invalid_verification_binding')
    ledger_path = gate_evidence_path_for_preflight(path)
    ledger_raw = _bounded(ledger_path, 8 * 1024 * 1024)
    _, diagnostics = merge_gate_evidence_from_ledger(route=route, evidence_path=path)
    if diagnostics.get('warnings'):
        raise _ReceiptError('invalid_gate_ledger_binding')
    ledger = read_gate_evidence_ledger(ledger_path)
    if (ledger_raw != _bounded(ledger_path, 8 * 1024 * 1024)
            or raw != _bounded(path, 1024 * 1024)):
        raise _ReceiptError('verification_changed_during_read')
    return preflight, [r for r in ledger.get('entries', []) if isinstance(r, dict)]


def _ids(value):
    if (not isinstance(value, list) or len(value) > 1024
            or any(not isinstance(v, str) or len(v.encode('utf-8')) > 512 for v in value)
            or sum(len(v.encode('utf-8')) for v in value) > 65536):
        raise _ReceiptError('invalid_executed_test_ids')
    return value


def _fact(row, preflight, reuse, *, live):
    fields = row.get('fields') or {}
    raw = fields.get('execution', '') if isinstance(fields, dict) else ''
    if row.get('source') != 'execution' or not isinstance(raw, str) or len(raw.encode()) > 262144:
        raise _ReceiptError('missing_execution_observation')
    data = json.loads(raw)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or not isinstance(data.get('id'), str) or not _ID.fullmatch(data['id'])
            or type(data.get('exit_code')) is not int or type(data.get('tests_run')) is not int
            or data['tests_run'] <= 0 or type(data.get('successful')) is not bool
            or data.get('inputs_unchanged') is not True):
        raise _ReceiptError('incomplete_execution_observation')
    argv, snapshot = data.get('argv'), data.get('snapshot')
    if (not isinstance(argv, list) or len(argv) != 6 or not all(isinstance(s, str) for s in argv)
            or argv[1] != '-B' or not isinstance(snapshot, dict)
            or snapshot.get('schema_version') not in (1, 2) or not isinstance(snapshot.get('states'), dict)
            or snapshot.get('project') != preflight['project'] or snapshot.get('rules') != preflight['rules']
            or snapshot.get('session') != preflight.get('runtime_session')):
        raise _ReceiptError('foreign_execution_binding')
    runners = {Path(__file__).with_name('agent_unittest_result.py').resolve(),
               Path(preflight['rules']) / 'scripts' / 'agent_unittest_result.py'}
    project = Path(preflight['project'])
    if (Path(argv[2]).resolve() not in runners or Path(argv[3]).resolve() != project
            or not Path(argv[4]).resolve().is_relative_to(project)):
        raise _ReceiptError('foreign_execution_target')
    if live:
        candidate = {'gate': 'tests', 'status': 'SUCCESS'}
        if snapshot.get('schema_version') == 2:
            candidate['input_paths'] = snapshot.get('input_paths')
        current = reuse.prepare([candidate])[0].get('reuse_snapshot')
        if current != snapshot:
            raise _ReceiptError('stale_verification_snapshot')
    successful = data['successful'] and data['exit_code'] == 0
    if (row.get('status') != ('SUCCESS' if successful else 'FAIL')
            or not successful and data['exit_code'] == 0):
        raise _ReceiptError('inconsistent_execution_outcome')
    pattern = argv[5]
    selectors = json.loads(pattern[len('@selectors:'):]) if pattern.startswith('@selectors:') else []
    if not isinstance(selectors, list) or not all(isinstance(s, str) for s in selectors):
        raise _ReceiptError('malformed_verification_selectors')
    passed, failed = _ids(data.get('passed_ids')), _ids(data.get('failed_ids'))
    passed_labels = data.get('passed_selectors', [])
    failed_labels = data.get('failed_selectors', [])
    for labels in (passed_labels, failed_labels):
        if not isinstance(labels, list) or len(labels) > 64 or any(label not in selectors for label in labels):
            raise _ReceiptError('invalid_observed_selectors')
    if successful and not passed and not passed_labels:
        raise _ReceiptError('missing_executed_test_ids')
    return {'id': data['id'], 'successful': successful, 'exit_code': data['exit_code'],
            'tests_run': data['tests_run'], 'passed_ids': passed, 'failed_ids': failed,
            'passed_selectors': passed_labels, 'failed_selectors': failed_labels,
            'selectors': selectors, 'pattern': pattern, 'test_directory': argv[4],
            'inputs_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}


def _covers(ids, selectors):
    return all(any(test_id == sel or test_id.startswith(sel + '.')
                   or test_id.endswith('_FailedTest.' + sel) for test_id in ids)
               for sel in selectors)


def _row_id(row):
    try:
        fields = row.get('fields')
        raw = fields.get('execution', '') if isinstance(fields, dict) else ''
        data = json.loads(raw) if isinstance(raw, str) and len(raw.encode()) <= 262144 else {}
        return data.get('id', '') if isinstance(data, dict) else ''
    except (ValueError, TypeError):
        return ''


def _review_fact(reader, evidence, file_path):
    from agent_review_attestation import ReviewAttestation
    preflight, rows, _ = reader._load(evidence)
    reviews = [r for r in rows if r.get('gate') == 'review hook']
    if not reviews or reviews[-1].get('status') != 'SUCCESS':
        raise _ReceiptError('missing_source_review')
    record = json.loads(_bounded(ReviewAttestation.path(Path(evidence)), 4 * 1024 * 1024))
    # A source review only closes a finding on a file it explicitly covered.
    if (not str(record.get('review_scope', '')).startswith('pathspec:')
            or file_path not in record.get('review_paths', [])):
        raise _ReceiptError('missing_review_file_coverage')
    failures = ReviewAttestation.failures(project=reader.project, rules=Path(preflight['rules']),
        evidence_path=Path(evidence), route=preflight['route'],
        ledger_fields=reviews[-1].get('fields') or {}, ledger_source=reviews[-1].get('source', ''),
        attestation=record)
    if failures:
        raise _ReceiptError('stale_or_invalid_source_review')
    return {'ok': True, 'kind': 'source_review', 'id': record['attestation_id']}


class ExecutionReceipts:
    def __init__(self, project, rules=None):
        self.project = Path(project).resolve()
        self.rules = Path(rules).resolve() if rules is not None else None
        self.cache = {}

    def _load(self, evidence):
        path = Path(evidence).absolute()
        if path not in self.cache:
            preflight, rows = _bound(self.project, self.rules, path)
            self.cache[path] = preflight, rows, GateEvidenceReuse(preflight)
        return self.cache[path]

    def inspect(self, evidence, *, selectors=(), execution_id='', historical_failure=False,
                test_directory=None):
        try:
            preflight, rows, reuse = self._load(evidence)
            rows = [r for r in rows if r.get('gate') == 'tests']
            selected = [r for r in rows if _row_id(r) == execution_id] if execution_id else rows[-1:]
            if not selected:
                raise _ReceiptError('missing_execution_observation')
            if execution_id and len(selected) != 1:
                raise _ReceiptError('ambiguous_execution_observation')
            row = selected[-1]
            fact = _fact(row, preflight, reuse, live=not historical_failure)
            if fact['successful'] == historical_failure:
                raise _ReceiptError('verification_not_passing' if not historical_failure else 'before_fail_did_not_fail')
            prefix = 'failed' if historical_failure else 'passed'
            ids = fact[prefix + '_ids'] + fact[prefix + '_selectors']
            if fact['selectors'] and any(not any(req == chosen or req.startswith(chosen + '.')
                    for chosen in fact['selectors']) for req in selectors):
                raise _ReceiptError('missing_required_selector')
            if not _covers(ids, selectors):
                raise _ReceiptError('missing_required_selector')
            if test_directory is not None and Path(fact['test_directory']).resolve() != (self.project / test_directory).resolve():
                raise _ReceiptError('mismatched_test_directory')
            later = rows[rows.index(row) + 1:]
            for later_row in () if historical_failure else later:
                subsequent = _fact(later_row, preflight, reuse, live=True)
                if not subsequent['successful'] and (not selectors or
                        any(_covers(subsequent['failed_ids'] + subsequent['failed_selectors'], [sel])
                            for sel in selectors)):
                    raise _ReceiptError('later_matching_verification_failed')
            return {'ok': True, 'reason': 'observed_verification_verified', **fact}
        except _ReceiptError as error:
            return {'ok': False, 'reason': str(error)}
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
            return {'ok': False, 'reason': 'invalid_execution_evidence'}

    def history(self, evidence, *, live=True):
        try:
            preflight, rows, reuse = self._load(evidence)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return []
        facts = []
        for row in rows:
            if row.get('gate') != 'tests':
                continue
            try:
                facts.append(_fact(row, preflight, reuse, live=live))
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                continue
        return facts

    def review(self, evidence, file_path):
        try:
            return _review_fact(self, evidence, file_path)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
            return {'ok': False, 'reason': 'invalid_source_review'}
