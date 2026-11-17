"""Cancellation stops a real child; a late successful runner cannot complete."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_scheduler import cancel_task, claim_task, enqueue_task, transition_task, retry_task
from workflow_dispatch_launch import _run_scheduled_worker
from workflow_dispatch_process import run_worker
from workflow_dispatch_handoff import build_worker_result_packet, worker_output_paths
from agent_ipc import read_events
from agent_state_read import read_json_object, scheduler_path


class WorkerProcessTests(unittest.TestCase):
    def task(self, root):
        task = enqueue_task(root, 'run', max_retries=1)
        return claim_task(root, task['task_id'])

    def test_zero_exit_with_blocked_packet_cannot_complete_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            prepared = {'preflight_evidence': str(root / 'preflight.json')}
            calls = []
            def runner(_):
                calls.append(1)
                build_worker_result_packet(prepared, returncode=0,
                    raw_output='{"status":"blocked","blockers":["needs input"],"next_action":"ask owner"}')
                return 0
            result = _run_scheduled_worker([], runner, root, task,
                task_context={'task': task, 'prepared': prepared})
            packet = json.loads(Path(worker_output_paths(prepared)['result_path']).read_text())
            self.assertNotEqual(0, result)
            self.assertEqual('failed', read_json_object(scheduler_path(root))['tasks'][-1]['state'])
            self.assertEqual([1], calls)
            self.assertEqual('ask owner', packet['next_action'])

    def test_parent_sigkill_stops_worker_and_ignoring_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            marker, escaped = root / 'pid', root / 'escaped'
            child = ('import signal,sys,time; from pathlib import Path; '
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                     'Path(sys.argv[1]).write_text("ready"); time.sleep(1.5); '
                     'Path(sys.argv[2]).write_text("orphan"); time.sleep(10)')
            worker = ('import os,subprocess,sys,time; from pathlib import Path; '
                      'Path(sys.argv[1]).write_text(str(os.getpid())); '
                      'subprocess.Popen([sys.executable,"-c",sys.argv[2],sys.argv[3],sys.argv[4]]); time.sleep(15)')
            supervisor = root / 'supervisor.py'
            supervisor.write_text('import json,os,subprocess,sys\nfrom pathlib import Path\n'
                f'sys.path.insert(0,{str(Path(__file__).resolve().parents[1] / "scripts")!r})\n'
                'from workflow_dispatch_process import run_worker\n'
                'run_worker(json.loads(sys.argv[1]), env=os.environ, stdout=subprocess.DEVNULL, '
                'project=Path(sys.argv[2]), task=json.loads(sys.argv[3]))\n')
            ready = root / 'ready'
            command = [sys.executable, '-c', worker, str(marker), child, str(ready), str(escaped)]
            parent = subprocess.Popen([sys.executable, str(supervisor), json.dumps(command), str(root), json.dumps(task)])
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                parent.kill()
                parent.wait(timeout=3)
                time.sleep(2)
                self.assertFalse(escaped.exists(), 'descendant survived dispatcher SIGKILL')
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=3)
                if marker.exists():
                    try:
                        os.killpg(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already reaped by the guardian.

    def test_cancelled_runner_cannot_return_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            def runner(_):
                cancel_task(root, task['task_id'])
                return 0
            self.assertEqual(130, _run_scheduled_worker([], runner, root, task))

    def test_new_attempt_cannot_be_completed_by_previous_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            def runner(_):
                transition_task(root, task['task_id'], 'failed')
                retry_task(root, task['task_id'])
                claim_task(root, task['task_id'])
                return 0
            self.assertEqual(130, _run_scheduled_worker([], runner, root, task))

    def test_rejected_late_success_replaces_success_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            prepared = {'preflight_evidence': str(root / 'preflight.json')}
            def runner(_):
                build_worker_result_packet(prepared, returncode=0, raw_output='{"status":"ok"}')
                cancel_task(root, task['task_id'])
                return 0
            result = _run_scheduled_worker([], runner, root, task, task_context={'task':task, 'prepared':prepared})
            packet = json.loads(Path(worker_output_paths(prepared)['result_path']).read_text())
            self.assertEqual(130, result)
            self.assertEqual('blocked', packet['status'])

    def test_already_cancelled_task_does_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            cancel_task(root, task['task_id'])
            marker = root / 'unexpected'
            result = run_worker([sys.executable, '-c', 'open(__import__("sys").argv[1],"w").close()', str(marker)],
                                env=os.environ, stdout=subprocess.DEVNULL, project=root, task=task)
            self.assertEqual(130, result.returncode)
            self.assertFalse(marker.exists())

    def test_keyboard_interrupt_cancels_task_and_reports_no_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            def interrupted(_):
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                _run_scheduled_worker([], interrupted, root, task, heartbeat_interval_seconds=.01)
            self.assertEqual('cancelled', read_json_object(scheduler_path(root))['tasks'][-1]['state'])
            self.assertEqual([], read_events(root, event_type='worker.failure'))
            self.assertEqual(1, len(read_events(root, event_type='worker.cancelled')))

    def test_running_child_stops_after_scheduler_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            marker = root / 'pid'
            failures = []
            def cancel_after_start():
                deadline = time.monotonic() + 4
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                if not marker.exists():
                    failures.append('worker did not start')
                cancel_task(root, task['task_id'])
            cancel = threading.Thread(target=cancel_after_start)
            cancel.start()
            try:
                program = 'import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(20)'
                started = time.monotonic()
                result = run_worker([sys.executable, '-c', program, str(marker)], env=os.environ,
                                    stdout=subprocess.DEVNULL, project=root, task=task)
            finally:
                cancel.join(timeout=5)
            self.assertEqual([], failures)
            self.assertEqual(130, result.returncode)
            self.assertLess(time.monotonic() - started, 7)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)

    def test_cancellation_kills_descendant_that_ignores_sigterm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.task(root)
            ready, escaped = root / 'ready', root / 'escaped'
            child = ('import signal,sys,time; from pathlib import Path; '
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                     'Path(sys.argv[1]).write_text("ready"); time.sleep(2); '
                     'Path(sys.argv[2]).write_text("still running"); time.sleep(20)')
            parent = ('import subprocess,sys,time; '
                      'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2],sys.argv[3]]); time.sleep(20)')
            def cancel_after_child_ready():
                deadline = time.monotonic() + 4
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                cancel_task(root, task['task_id'])
            cancel = threading.Thread(target=cancel_after_child_ready)
            cancel.start()
            try:
                result = run_worker([sys.executable, '-c', parent, child, str(ready), str(escaped)],
                                    env=os.environ, stdout=subprocess.DEVNULL, project=root, task=task)
            finally:
                cancel.join(timeout=5)
            self.assertTrue(ready.exists())
            self.assertEqual(130, result.returncode)
            time.sleep(2.1)
            self.assertFalse(escaped.exists())


if __name__ == '__main__':
    unittest.main()
