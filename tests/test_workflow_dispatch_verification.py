"""Required worker checks use real registered execution facts, never CLI claims."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_gate_evidence import gate_evidence_path_for_preflight
from agent_state_read import read_json_object, scheduler_path
from agent_scheduler import claim_task, enqueue_task
from agent_worker_evidence import isolated_worker_evidence, claim_worker_reservation
from agent_worktree_identity import new_worktree_path
from workflow_dispatch_completion import evaluate_result
from workflow_dispatch_handoff import build_handoff_prompt, build_worker_result_packet, worker_output_paths
from workflow_dispatch_launch import execute_dispatch_manifest, _run_scheduled_worker, _run_spooled_worker
from workflow_dispatch_verification import (CALLER_REPORT, OBSERVED_VERIFICATION,
    PROCESS_COMPLETION, assess_completion_verification, classify_worker_checks)
from test_agent_verification_receipts import ReceiptFixture


class DispatchVerificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.f = ReceiptFixture(temp.name)
        self.project, self.preflight_path = self.f.project, self.f.path
        self.prepared = {'rules': str(self.project), 'preflight_evidence': str(self.f.path),
            'execution_capsule': {'reusable': True}, 'required_verification': True,
            'route_manifest': {'command': 'task', 'gates': ['tests']}}

    def packet(self, **raw):
        return build_worker_result_packet(self.prepared, returncode=0,
                                         raw_output=json.dumps({'status': 'ok', **raw}))

    def test_cli_exit_and_spoofed_provenance_are_distinct_from_execution(self):
        process = self.packet()
        self.assertEqual(PROCESS_COMPLETION, classify_worker_checks(process))
        report = self.packet(checks=[{'cmd': 'pytest', 'exit_code': 0, 'outcome': 'pass',
                                    'provenance': OBSERVED_VERIFICATION}])
        self.assertEqual(CALLER_REPORT, report['checks'][0]['provenance'])
        self.assertFalse(evaluate_result(report, prepared=self.prepared, working_dir=self.project)[0])

    def test_real_matching_verification_completes_scheduled_worker_without_replay(self):
        self.assertEqual(0, self.f.run(['test_sample.Case.test_ok']))
        packet = self.packet()
        ok, invalid = evaluate_result(packet, prepared=self.prepared, working_dir=self.project,
            required_verification={'selectors': ['test_missing']})
        self.assertFalse(ok)
        self.assertEqual('missing_required_selector', invalid['reason'])
        task = claim_task(self.project, enqueue_task(self.project, 'run', max_retries=1)['task_id'])
        message = worker_output_paths(self.prepared)['last_message_path']
        command = [sys.executable, '-c',
            'import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.argv[2])',
            message, json.dumps({'status': 'ok', 'summary': 'done'})]
        context = {'task': task, 'prepared': self.prepared, 'working_dir': str(self.project),
                   'required_verification': {'selectors': ['test_sample.Case.test_ok']}}
        result = _run_scheduled_worker(command,
            lambda argv: _run_spooled_worker(argv, self.prepared, task, '', project=self.project),
            self.project, task, task_context=context)
        self.assertEqual(0, result)
        self.assertEqual(OBSERVED_VERIFICATION, context['completion_assessment']['classification'])
        state = read_json_object(scheduler_path(self.project))['tasks'][-1]
        self.assertEqual('completed', state['state'])
        self.assertEqual(1, state['attempt'])

    def test_registered_but_unobserved_or_stale_records_cannot_satisfy_requirement(self):
        self.assertEqual(0, self.f.run())
        ledger = self.f.ledger()
        ledger['entries'][-1]['fields'].pop('execution')
        gate_evidence_path_for_preflight(self.f.path).write_text(json.dumps(ledger))
        self.assertFalse(assess_completion_verification(self.packet(), prepared=self.prepared,
                                                       working_dir=self.project)['satisfied'])
        self.assertEqual(0, self.f.run())
        (self.project / 'changed.py').write_text('changed = True')
        self.assertFalse(assess_completion_verification(self.packet(), prepared=self.prepared,
                                                       working_dir=self.project)['satisfied'])

    def test_isolated_dispatch_requires_fresh_evidence_from_issued_worker_path(self):
        selector = 'test_sample.Case.test_ok'
        self.assertEqual(0, self.f.run([selector]))
        original = self.preflight_path.read_bytes()
        for scenario, expected in [('pass', 0), ('missing', 1), ('stale', 1)]:
            with self.subTest(scenario=scenario):
                child = new_worktree_path(self.project)
                parent_slot = self.project / '.moru' / 'workers' / scenario / 'preflight.json'
                manifest = {
                    'project': str(self.project), 'command': 'task', 'work_kind': 'implementation',
                    'work_profile': {}, 'sandbox_mode': 'workspace-write', 'execution_mode': 'child',
                    'isolation_required': True, 'worktree_path': str(child),
                    'handoff_state': {**self.prepared, 'worker_preflight_evidence': str(parent_slot),
                                      'required_docs': [], 'gates': ['tests'],
                                      'gate_ledger': 'parent ledger', 'verification_plan': 'required'},
                    'required_verification': {'selectors': [selector]},
                    'worker_owned_verification': True,
                }

                def argv(*args, output_last_message, **kwargs):
                    self.assertIn(selector, args[3])
                    return [str(output_last_message)]

                def process(command, *, env, **kwargs):
                    self.assertEqual(str(child), env['MORU_WORKER_WORKTREE'])
                    evidence = Path(env['MORU_WORKER_EVIDENCE'])
                    self.assertTrue(evidence.is_relative_to(child))
                    self.assertTrue(claim_worker_reservation(
                        evidence.parent, env['MORU_WORKER_RESERVATION_TOKEN']))
                    worker = ReceiptFixture.__new__(ReceiptFixture)
                    worker.project = child
                    worker.bind(evidence, self.project)
                    if scenario != 'missing':
                        self.assertEqual(0, worker.run([selector]))
                    if scenario == 'stale':
                        worker.write_test('self.assertTrue(False)')
                    Path(command[0]).write_text('{"status":"ok"}')
                    return subprocess.CompletedProcess(command, 0)

                with patch('workflow_dispatch_launch.run_worker', side_effect=process):
                    self.assertEqual(expected, execute_dispatch_manifest(
                        manifest, runner=None, execution_capsule_state=lambda *a, **k: self.fail(
                            "worker-owned verification must not reuse the parent capsule"),
                        isolated_worker_evidence=isolated_worker_evidence, codex_argv=argv,
                        build_handoff_prompt=build_handoff_prompt))
                self.assertEqual(original, self.preflight_path.read_bytes())

    def test_skip_only_and_foreign_target_cannot_satisfy_requirement(self):
        self.assertEqual(1, self.f.run(['test_sample.Case.test_skip']))
        self.assertFalse(evaluate_result(self.packet(), prepared=self.prepared, working_dir=self.project)[0])
        self.assertEqual(0, self.f.run(['test_sample.Case.test_ok']))
        foreign = self.project / 'foreign'
        foreign.mkdir()
        self.assertFalse(evaluate_result(self.packet(), prepared=self.prepared, working_dir=foreign)[0])

    def test_parent_tests_gate_does_not_silently_require_worker_ledger_writes(self):
        legacy = {key: value for key, value in self.prepared.items() if key != 'required_verification'}
        accepted, assessment = evaluate_result(self.packet(), prepared=legacy, working_dir=self.project)
        self.assertTrue(accepted)
        self.assertFalse(assessment['verification_required'])
        self.assertEqual(PROCESS_COMPLETION, assessment['classification'])
        findings = self.packet(status='findings', findings=['inspect this'])
        self.assertTrue(evaluate_result(findings, prepared=legacy, working_dir=self.project,
                                        allow_findings=True)[0])

    def test_malformed_requirement_cannot_disable_verification(self):
        for required in ('true', 0, {'required': 'true'}, {'selectors': False},
                         {'selectors': ['missing-method']}, {'unknown': True}):
            with self.subTest(required=required):
                accepted, assessment = evaluate_result(self.packet(), prepared=self.prepared,
                    working_dir=self.project, required_verification=required)
                self.assertFalse(accepted)
                self.assertEqual('invalid_required_verification', assessment['reason'])

    def test_duplicate_findings_return_inspection_packet_and_preserve_details(self):
        packet = self.packet(findings=[{'id': 'duplicate', 'claim': 'a'},
                                     {'id': 'duplicate', 'claim': 'b'}])
        self.assertEqual('needs_inspection', packet['status'])
        self.assertTrue(packet['blockers'])
        self.assertTrue(Path(packet['artifacts']['details_path']).is_file())


if __name__ == '__main__':
    unittest.main()
