"""Durable execution admission protects replay and preserves existing output."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_scheduler import claim_task, enqueue_task, transition_task
from workflow_dispatch_execution import admit_execution, save_receipt
from workflow_dispatch_process import run_worker
from workflow_dispatch_launch import _run_spooled_worker
from workflow_dispatch_handoff import worker_output_paths


class ExecutionAdmissionTests(unittest.TestCase):
    def task(self, project):
        task = enqueue_task(project, 'run', max_retries=1)
        return claim_task(project, task['task_id'])

    def test_finished_attempt_cannot_execute_twice_and_receipt_is_content_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            marker = root / 'calls'
            command = [sys.executable, '-c',
                'import sys; from pathlib import Path; p=Path(sys.argv[1]); p.write_text("once")', str(marker)]
            result = run_worker(command, env={**os.environ, 'PRIVATE_TEST_VALUE':'private-sentinel'},
                                stdout=subprocess.DEVNULL, project=root, task=task)
            self.assertEqual(0, result.returncode)
            with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                run_worker(command, env=os.environ, stdout=subprocess.DEVNULL, project=root, task=task)
            self.assertEqual('once', marker.read_text())
            receipts = list(root.rglob('worker-executions/*.json'))
            self.assertEqual(1, len(receipts))
            raw = receipts[0].read_text()
            self.assertNotIn('private-sentinel', raw)
            self.assertNotIn(str(marker), raw)
            self.assertEqual('finished', json.loads(raw)['state'])

    def test_uncertain_receipt_blocks_later_attempt_without_signaling_unrelated_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(10)'])
            try:
                with admit_execution(root, task) as (path, state, _):
                    save_receipt(path, {**state, 'state':'running'})
                with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                    with admit_execution(root, {**task, 'attempt':2}):
                        self.fail('uncertain work was admitted')
                self.assertIsNone(sentinel.poll())
                self.assertEqual('running', json.loads(path.read_text())['state'])
                path.write_text(json.dumps({**state, 'state':'running', 'pid':sentinel.pid}))
                with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                    with admit_execution(root, task):
                        self.fail('unbound PID record was admitted')
                self.assertIsNone(sentinel.poll())
            finally:
                sentinel.terminate()
                sentinel.wait(timeout=3)

    def test_shared_dispatch_key_fences_new_task_without_clearing_existing_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared = {'preflight_evidence':str(root / 'preflight.json'),
                        'execution_capsule': {'reusable': True}}
            paths = worker_output_paths(prepared)
            task = self.task(root)
            command = [sys.executable, '-c',
                'import sys;from pathlib import Path;Path(sys.argv[1]).write_text("{\\"status\\":\\"ok\\"}")',
                paths['last_message_path']]
            self.assertEqual(0, _run_spooled_worker(command, prepared, task, '', project=root).returncode)
            original = Path(paths['result_path']).read_bytes()
            transition_task(root, task['task_id'], 'completed')
            second = self.task(root)
            with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                _run_spooled_worker(command, prepared, second, '', project=root)
            self.assertEqual(original, Path(paths['result_path']).read_bytes())
            self.assertTrue(Path(paths['last_message_path']).is_file())
            with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                _run_spooled_worker(['/missing/worker'], prepared, second, '', project=root)
            self.assertEqual(original, Path(paths['result_path']).read_bytes())

    def test_lock_prevents_concurrent_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            with admit_execution(root, task):
                with self.assertRaisesRegex(ValueError, 'in_progress'):
                    with admit_execution(root, task):
                        self.fail('duplicate execution admitted')

    def test_only_known_failed_predecessor_can_admit_next_attempt(self):
        for phase, code, allowed in [('admitted',None,False), ('running',None,False),
                ('interrupted',130,False), ('finished',0,False), ('finished',1,True)]:
            with self.subTest(phase=phase, code=code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                task = self.task(root)
                with admit_execution(root, task) as (path, state, _):
                    save_receipt(path, {**state, 'state':phase, 'returncode':code})
                if allowed:
                    with admit_execution(root, {**task,'attempt':2}) as (_, newer, _):
                        self.assertEqual(2, newer['attempt'])
                else:
                    with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                        with admit_execution(root, {**task,'attempt':2}):
                            self.fail('unsafe replay admitted')

    def test_receipt_failure_prevents_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            marker = root / 'unexpected'
            command = [sys.executable, '-c', 'import sys;open(sys.argv[1],"w").close()', str(marker)]
            with patch('workflow_dispatch_execution.save_receipt', side_effect=OSError('storage unavailable')):
                with self.assertRaises(OSError):
                    run_worker(command, env=os.environ, stdout=subprocess.DEVNULL, project=root, task=task)
            self.assertFalse(marker.exists())

    def test_admitted_but_unstarted_worker_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            def interrupted():
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                run_worker([sys.executable, '-c', 'raise SystemExit(0)'], env=os.environ,
                    stdout=subprocess.DEVNULL, project=root, task=task, before_start=interrupted)
            with self.assertRaisesRegex(ValueError, 'needs_inspection'):
                with admit_execution(root, task):
                    self.fail('uncertain admission was replayed')

    def test_running_receipt_failure_never_releases_gated_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            marker = root / 'unexpected'
            scripts = str(Path(__file__).resolve().parents[1] / 'scripts')
            program = (f'import sys;sys.path.insert(0,{scripts!r})\n'
                'from pathlib import Path\nimport workflow_dispatch_guardian as g\n'
                'def fail(*args): raise OSError("storage unavailable")\n'
                'g.save_receipt=fail\n'
                'try: g._guard(Path(sys.argv[1]))\n'
                'except OSError: raise SystemExit(125)\n')
            command = [sys.executable, '-c', 'import sys;open(sys.argv[1],"w").close()', str(marker)]
            with admit_execution(root, task) as (path, _, lock):
                guardian = subprocess.Popen([sys.executable, '-c', program, str(path)],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    pass_fds=(lock,))
                try:
                    guardian.stdin.write(json.dumps({'command':command,'env':dict(os.environ)}).encode() + b'\n')
                    guardian.stdin.flush()  # Keep the lifeline alive; fail at the running write.
                    self.assertEqual(125, guardian.wait(timeout=4))
                finally:
                    guardian.stdin.close()
                    if guardian.poll() is None:
                        guardian.kill()
                        guardian.wait(timeout=3)
            self.assertFalse(marker.exists())
            self.assertEqual('admitted', json.loads(path.read_text())['state'])


if __name__ == '__main__':
    unittest.main()
