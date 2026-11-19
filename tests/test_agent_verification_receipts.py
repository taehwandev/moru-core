"""Real verification receipts, provenance, skipped targets and finding closure."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import agent_verification_hook as verify
from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_run_registry import register_run
from agent_verification_receipts import ExecutionReceipts


class ReceiptFixture:
    def __init__(self, root, gates=None):
        self.project = Path(root).resolve()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        (self.project / '.gitignore').write_text('.moru/\n__pycache__/\n')
        (self.project / 'tests').mkdir()
        self.write_test()
        subprocess.run(['git', '-C', str(self.project), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.project), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        path = self.project / '.moru' / 'runs' / ('a' * 32) / 'preflight.json'
        self.bind(path, self.project, gates=gates)

    def bind(self, path, rules, *, gates=None):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.session = {'runtime': 'codex', 'session_id': 'receipt-fixture'}
        route = {'command': 'task', 'gates': gates or ['tests']}
        run = register_run(self.project, self.path, route, {'request': 'verify fixture'})
        self.preflight = {'project': str(self.project), 'rules': str(rules),
            'runtime_session': self.session, 'agent_run_id': run['run_id'], 'route': route}
        self.path.write_text(json.dumps(self.preflight))
        self.args = SimpleNamespace(project=self.project, rules=rules, evidence=self.path,
            test_directory='tests', test_pattern='test_*.py', test_selector=[], verify_timeout=10)

    def write_test(self, body='self.assertTrue(True)'):
        (self.project / 'tests' / 'test_sample.py').write_text(
            'import unittest\nfrom pathlib import Path\nclass Case(unittest.TestCase):\n'
            '    def test_ok(self):\n        ' + body + '\n'
            '    @unittest.skip("fixture")\n    def test_skip(self):\n        pass\n')

    def run(self, selectors=()):
        self.args.test_selector = list(selectors)
        with patch.object(verify, 'runtime_session', return_value=self.session), \
                patch.object(verify, 'resolve_runtime_evidence', return_value=self.path), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return verify.verification_hook(self.args)

    def ledger(self):
        return json.loads(gate_evidence_path_for_preflight(self.path).read_text())

    def execution(self):
        return json.loads(self.ledger()['entries'][-1]['fields']['execution'])

    def ref(self, selector='test_sample.Case.test_ok'):
        return {'receipt_ref': 'a' * 32, 'execution_id': self.execution()['id'], 'selector': selector}


class ExecutionReceiptTests(unittest.TestCase):
    def fixture(self, **kwargs):
        temp = tempfile.TemporaryDirectory(prefix="moru proof '")
        self.addCleanup(temp.cleanup)
        return ReceiptFixture(temp.name, **kwargs)

    def test_actual_receipt_keeps_argument_boundaries_and_execution_identity(self):
        f = self.fixture()
        self.assertEqual(0, f.run(['test_sample.Case.test_ok']))
        result = ExecutionReceipts(f.project, f.project).inspect(
            f.path, selectors=['test_sample.Case.test_ok'])
        self.assertTrue(result['ok'], result)
        self.assertEqual(f.execution()['id'], result['id'])
        self.assertEqual(['test_sample.Case.test_ok'], result['passed_ids'])
        self.assertEqual(1, result['tests_run'])

    def test_a_skipped_target_is_not_proven_by_another_passing_target(self):
        f = self.fixture()
        self.assertEqual(0, f.run(['test_sample']))
        result = ExecutionReceipts(f.project, f.project).inspect(
            f.path, selectors=['test_sample.Case.test_skip'])
        self.assertFalse(result['ok'])
        self.assertEqual('missing_required_selector', result['reason'])

    def test_unexecuted_method_is_not_proven_by_discovery(self):
        f = self.fixture()
        self.assertEqual(0, f.run())
        result = ExecutionReceipts(f.project, f.project).inspect(
            f.path, selectors=['test_sample.Case.test_missing'])
        self.assertFalse(result['ok'])

    def test_selected_method_cannot_satisfy_required_module(self):
        f = self.fixture()
        self.assertEqual(0, f.run(['test_sample.Case.test_ok']))
        result = ExecutionReceipts(f.project).inspect(f.path, selectors=['test_sample'])
        self.assertFalse(result['ok'])
        self.assertEqual('missing_required_selector', result['reason'])

    def test_detailed_id_limit_does_not_lose_a_later_selected_module(self):
        f = self.fixture()
        (f.project / 'tests' / 'test_many.py').write_text(
            'import unittest\nclass Case(unittest.TestCase):\n    pass\n'
            'for n in range(1050):\n'
            '    setattr(Case, "test_%04d" % n, lambda self: None)\n')
        self.assertEqual(0, f.run(['test_many', 'test_sample']))
        result = ExecutionReceipts(f.project).inspect(f.path, selectors=['test_many', 'test_sample'])
        self.assertTrue(result['ok'], result)
        self.assertEqual(1052, result['tests_run'])
        self.assertEqual(1024, len(result['passed_ids']))
        self.assertFalse(f.execution()['ids_complete'])
        self.assertEqual(['test_many', 'test_sample'], result['passed_selectors'])
        skipped = ExecutionReceipts(f.project).inspect(f.path, selectors=['test_sample.Case.test_skip'])
        self.assertFalse(skipped['ok'])

    def test_source_changes_and_foreign_snapshot_sessions_reject_real_receipt(self):
        f = self.fixture()
        self.assertEqual(0, f.run())
        (f.project / 'subject.py').write_text('changed = True\n')
        result = ExecutionReceipts(f.project, f.project).inspect(f.path)
        self.assertFalse(result['ok'])
        self.assertEqual('stale_verification_snapshot', result['reason'])
        (f.project / 'subject.py').unlink()
        ledger = f.ledger()
        data = json.loads(ledger['entries'][-1]['fields']['execution'])
        data['snapshot']['session'] = {'runtime': 'codex', 'session_id': 'foreign'}
        ledger['entries'][-1]['fields']['execution'] = json.dumps(data)
        gate_evidence_path_for_preflight(f.path).write_text(json.dumps(ledger))
        self.assertFalse(ExecutionReceipts(f.project, f.project).inspect(f.path)['ok'])

    def test_real_before_failure_and_after_pass_resolve_only_linked_finding(self):
        from agent_review_packet import ReviewPacket
        f = self.fixture()
        subject = f.project / 'subject.py'
        subject.write_text('bad')
        subprocess.run(['git', '-C', str(f.project), 'add', 'subject.py'], check=True)
        f.write_test("self.assertEqual(Path('subject.py').read_text(), 'good')")
        original = hashlib.sha256(subject.read_bytes()).hexdigest()
        self.assertEqual(1, f.run(['test_sample.Case.test_ok']))
        before = f.ref()
        subject.write_text('good')
        self.assertEqual(0, f.run(['test_sample.Case.test_ok']))
        raw = {'id': 'R-1', 'file': 'subject.py', 'severity': 'high', 'claim': 'bad state',
            'state': 'fixed', 'reproducible': True, 'original_sha256': original,
            'verification': {'before_fail': before, 'after_pass': f.ref()}}
        packet = ReviewPacket.build(f.project, ['subject.py'], findings=[raw])
        self.assertEqual('resolved', packet['findings'][0]['state'], packet['findings'])
        self.assertEqual([], packet['re_review']['unresolved_ids'])
        subject.write_text('changed since the check')
        stale = ReviewPacket.build(f.project, ['subject.py'], findings=[raw])
        self.assertEqual('reopened', stale['findings'][0]['state'])

    def test_unregistered_prose_and_symlink_cannot_be_observed_execution(self):
        f = self.fixture()
        self.assertEqual(0, f.run())
        alias = f.path.with_name('alias.json')
        alias.symlink_to(f.path)
        self.assertFalse(ExecutionReceipts(f.project, f.project).inspect(alias)['ok'])
        registry = f.project / '.moru' / 'run-registry.json'
        registry.write_text(json.dumps({'schema_version': 1, 'runs': []}))
        result = ExecutionReceipts(f.project, f.project).inspect(f.path)
        self.assertFalse(result['ok'])
        self.assertEqual('unregistered_verification_run', result['reason'])

    def test_65_targets_advance_after_actual_first_batch_without_false_completion(self):
        from agent_next_action import inspect_next_action
        from test_agent_review_attestation import load_finish_check_module
        f = self.fixture(gates=['tests', 'review hook'])
        finish = load_finish_check_module()

        def gates():
            failures = []
            recorded, _ = finish._validated_gate_evidence(route=f.preflight['route'],
                project=f.project, rules=f.project, evidence_path=f.path, failures=failures)
            return recorded, failures

        selectors = ['test_target_%02d' % n for n in range(65)]
        for name in selectors:
            (f.project / 'tests' / (name + '.py')).write_text(
                'import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
        other = f.project / 'checks'
        other.mkdir()
        (other / (selectors[-1] + '.py')).write_bytes(
            (f.project / 'tests' / (selectors[-1] + '.py')).read_bytes())
        self.assertEqual(0, f.run(selectors[:64]))
        next_action = inspect_next_action(f.project, evidence=f.path)
        self.assertEqual('verify', next_action['next_step'])
        self.assertEqual(selectors[64:], next_action['verification']['next_verify_batch'])
        recorded, failures = gates()
        self.assertNotIn('tests', recorded)
        self.assertTrue(any('1 pending targets' in failure and selectors[-1] in failure
                            for failure in failures), failures)
        self.assertEqual(0, f.run([selectors[-1] + '.Case.test_ok']))
        self.assertNotIn('tests', gates()[0])
        f.args.test_directory = 'checks'
        self.assertEqual(0, f.run(selectors[64:]))
        self.assertNotIn('tests', gates()[0])
        f.args.test_directory = 'tests'
        self.assertEqual(0, f.run(selectors[64:]))
        complete = inspect_next_action(f.project, evidence=f.path)
        self.assertEqual('review', complete['next_step'])
        self.assertEqual([], complete['verification']['next_verify_batch'])
        self.assertIn('tests', gates()[0])

    def test_source_review_requires_scoped_canonical_attestation_validation(self):
        from agent_review_attestation import ReviewAttestation
        from agent_gate_evidence import record_gate_evidence
        from agent_review_packet import ReviewPacket
        f = self.fixture(gates=['tests', 'review hook'])
        self.assertEqual(0, f.run())
        ledger = f.ledger()
        ledger['entries'].append({'gate': 'review hook', 'status': 'SUCCESS', 'source': 'hook',
                                  'fields': {}, 'evidence': 'fixture'})
        gate_evidence_path_for_preflight(f.path).write_text(json.dumps(ledger))
        ReviewAttestation.path(f.path).write_text(json.dumps({'review_scope': 'pathspec',
            'review_paths': ['tests/test_sample.py'], 'attestation_id': 'd' * 64}))
        # A caller-written artifact cannot bypass the canonical validator.
        self.assertFalse(ExecutionReceipts(f.project).review(f.path, 'tests/test_sample.py')['ok'])
        attestation = ReviewAttestation.record(project=f.project, rules=f.project,
            evidence_path=f.path, preflight=f.preflight,
            review_scope='pathspec: tests/test_sample.py', review_paths=['tests/test_sample.py'],
            changed_path_count=0, checks={'review_outcome': 'pass',
                'workflow_validate': {'returncode': 0}, 'diff_check': {'returncode': 0},
                'vibeguard': {'returncode': 0, 'overall': 'Ready'}})
        record_gate_evidence(evidence_path=f.path, preflight=f.preflight,
            gate='review hook', evidence='fixture review', status='SUCCESS', source='review',
            fields=ReviewAttestation.ledger_fields(attestation))
        reader = ExecutionReceipts(f.project)
        self.assertFalse(reader.review(f.path, 'other.py')['ok'])
        self.assertTrue(reader.review(f.path, 'tests/test_sample.py')['ok'])
        raw = {'id': 'style-1', 'file': 'tests/test_sample.py', 'severity': 'low',
            'claim': 'style checked', 'state': 'resolved',
            'verification': {'kind': 'source_review', 'receipt_ref': 'a' * 32}}
        packet = ReviewPacket.build(f.project, ['tests/test_sample.py'], findings=[raw])
        self.assertEqual('resolved', packet['findings'][0]['state'], packet['findings'])
        f.write_test('self.assertTrue(False)')
        self.assertFalse(ExecutionReceipts(f.project).review(f.path, 'tests/test_sample.py')['ok'])


if __name__ == '__main__':
    unittest.main()
