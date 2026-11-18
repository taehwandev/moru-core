"""Dispatch callers observe packet verdicts, with parity across native/fallback."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_scheduler import claim_task, enqueue_task
from agent_state_read import read_json_object, scheduler_path
from workflow_dispatch_completion import accepts_result, read_result
from workflow_dispatch_handoff import build_worker_result_packet, worker_output_paths
from workflow_dispatch_launch import _run_scheduled_worker, _run_spooled_worker

NATIVE = os.environ.get('MORU_WORKER_COMPLETION_NATIVE')


class WorkerCompletionTests(unittest.TestCase):
    def test_real_zero_exit_obeys_packet_verdict_and_never_retries(self):
        for status, allowed, accepted in [('ok', False, True), ('blocked', False, False),
                ('needs_inspection', False, False), ('findings', False, False),
                ('findings', True, True), ('unknown', True, False), ('', False, False)]:
            with self.subTest(status=status, allowed=allowed), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp)
                prepared = {'preflight_evidence': str(project / 'preflight.json'),
                            'execution_capsule': {'reusable': True}}
                task = enqueue_task(project, 'run', max_retries=2)
                task = claim_task(project, task['task_id'])
                message = worker_output_paths(prepared)['last_message_path']
                program = 'import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.argv[2])'
                command = [sys.executable, '-c', program, message,
                           json.dumps({'status':status, 'summary':'verdict'})]
                context = {'task':task, 'prepared':prepared, 'allow_findings':allowed}
                result = _run_scheduled_worker(command,
                    lambda argv: _run_spooled_worker(argv, prepared, task, '', project=project),
                    project, task, task_context=context)
                stored = read_json_object(scheduler_path(project))['tasks'][-1]
                self.assertEqual(accepted, result == 0)
                self.assertEqual('completed' if accepted else 'failed', stored['state'])
                self.assertEqual(1, stored['attempt'])

    def test_missing_corrupt_and_symlink_packets_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = {'preflight_evidence': str(Path(tmp) / 'preflight.json')}
            self.assertIsNone(read_result(prepared))
            packet = build_worker_result_packet(prepared, returncode=0, raw_output='{"status":"ok"}')
            path = Path(worker_output_paths(prepared)['result_path'])
            path.write_text('{')
            self.assertIsNone(read_result(prepared))
            path.write_text('{"status":"blocked","status":"ok"}')
            self.assertIsNone(read_result(prepared))
            path.unlink()
            target = Path(tmp) / 'target'
            target.write_text(json.dumps(packet))
            path.symlink_to(target)
            self.assertIsNone(read_result(prepared))

    def test_native_selection_failure_cannot_silently_use_reference(self):
        with patch.dict(os.environ, {'MORU_WORKER_COMPLETION_NATIVE':'/missing/native'}):
            self.assertFalse(accepts_result({'status':'ok'}))

    def test_normalized_packet_boundaries_and_native_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = {'preflight_evidence': str(Path(tmp) / 'preflight.json')}
            original = build_worker_result_packet(prepared, returncode=0, raw_output='{"status":"ok"}')
        cases = [(original, False, True), (None, False, False), ({'status':'ok'}, False, False)]
        for field, value in [('schema_version','future'), ('status','blocked'),
                ('status','needs_inspection'), ('blockers',['unresolved']), ('summary',None),
                ('checks',[]), ('checks',[{'exit_code':1,'outcome':'fail'}]),
                ('checks',[{'exit_code':True,'outcome':'pass'}]), ('changed_paths',[3]),
                ('checks',[{'exit_code':2**80,'outcome':'pass'}]), ('findings',[3]),
                ('artifacts',[]), ('artifacts',{'log_path':3}), ('summary','x'*4097)]:
            packet = copy.deepcopy(original)
            packet[field] = value
            cases.append((packet, False, False))
        findings = {**original, 'status':'findings'}
        cases.extend([(findings, False, False), (findings, True, True),
                      ({**findings,'blockers':['unresolved']}, True, False)])
        for packet, allowed, expected in cases:
            with self.subTest(packet=packet, allowed=allowed):
                with patch.dict(os.environ, {'MORU_WORKER_COMPLETION_NATIVE':''}):
                    self.assertEqual(expected, accepts_result(packet, allow_findings=allowed))
                if NATIVE:
                    with patch.dict(os.environ, {'MORU_WORKER_COMPLETION_NATIVE':NATIVE}):
                        self.assertEqual(expected, accepts_result(packet, allow_findings=allowed))

    def test_required_tests_gate_fails_closed_without_observed_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            prepared = {
                'rules': str(project),
                'preflight_evidence': str(project / 'preflight.json'),
                'execution_capsule': {'reusable': True},
                'route_manifest': {'command': 'small-change', 'gates': ['tests']},
                'required_verification': True,
            }
            task = claim_task(project, enqueue_task(project, 'run', max_retries=2)['task_id'])
            message = worker_output_paths(prepared)['last_message_path']
            program = 'import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.argv[2])'
            command = [
                sys.executable, '-c', program, message,
                json.dumps({'status': 'ok', 'summary': 'done', 'checks': [{'cmd': 'pytest', 'exit_code': 0, 'outcome': 'pass'}]}),
            ]
            context = {'task': task, 'prepared': prepared, 'working_dir': str(project)}
            result = _run_scheduled_worker(
                command,
                lambda argv: _run_spooled_worker(argv, prepared, task, '', project=project),
                project,
                task,
                task_context=context,
            )
            stored = read_json_object(scheduler_path(project))['tasks'][-1]
            self.assertEqual(1, result)
            self.assertEqual('failed', stored['state'])
            self.assertEqual('caller_report', context['completion_assessment']['classification'])


if __name__ == '__main__':
    unittest.main()
