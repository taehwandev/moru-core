"""Durable ACP CLI recovery across process death, not just normal return."""
import json
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from test_agent_review_acp import FAKE, deny_owned_cleanup
from agent_review_acp import _main

ROOT = Path(__file__).resolve().parents[1]


class ReviewJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls.jsonl'
        self.output = self.root / 'review.json'
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Review supplied source; no tools.')

    def command(self, scenario):
        fake = self.root / 'fake-acp'
        fake.write_text('#!' + sys.executable + '\nimport sys\nsys.argv=' +
                        repr(['fake', scenario, str(self.log)]) + '\n' + FAKE)
        fake.chmod(0o700)
        return [sys.executable, str(ROOT / 'scripts/agent_review_acp.py'),
                '--project', str(self.root), '--prompt-file', str(self.prompt),
                '--output', str(self.output), '--executable', str(fake),
                '--idle-timeout', '10', '--max-seconds', '20']

    def calls(self, method):
        if not self.log.exists():
            return []
        return [x for x in map(json.loads, self.log.read_text().splitlines())
                if x.get('method') == method]

    def active(self):
        proc = subprocess.Popen(self.command('idle'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: self.stop(proc))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.output.exists() and self.calls('session/prompt'):
                return proc
            if proc.poll() is not None:
                self.fail(proc.communicate()[1].decode())
            time.sleep(.01)
        self.fail('session was not durably submitted')

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=4)

    def test_parent_death_leaves_session_and_restart_loads_without_new_prompt(self):
        proc = self.active()
        state = json.loads(self.output.read_text())
        self.assertEqual(state['session_id'], 'owned')
        self.assertEqual(state['phase'], 'submitted')
        self.assertNotIn(self.prompt.read_text(), self.output.read_text())
        os.kill(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=4)
        result = subprocess.run(self.command('idle'), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads(self.output.read_text())
        self.assertEqual(state['status'], 'needs_inspection')
        self.assertEqual(state['next_action'], 'inspect_existing_session')
        self.assertEqual(len(self.calls('session/load')), 1)
        self.assertEqual(len(self.calls('session/prompt')), 1)

    def test_concurrent_invocation_cannot_submit_second_turn(self):
        self.active()
        result = subprocess.run(self.command('idle'), capture_output=True, text=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['failure_code'], 'review_already_running')
        self.assertEqual(len(self.calls('initialize')), 1)
        self.assertEqual(len(self.calls('session/prompt')), 1)

    def test_completed_record_is_reused_without_provider_call(self):
        command = self.command('normal')
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('session/prompt')), 1)
        self.assertEqual(json.loads(self.output.read_text())['status'], 'ok')

    def test_changed_prompt_cannot_reuse_record_or_launch_duplicate(self):
        subprocess.run(self.command('normal'), capture_output=True, check=True, timeout=4)
        self.prompt.write_text('A different request')
        result = subprocess.run(self.command('normal'), capture_output=True, text=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['failure_code'], 'review_inputs_changed')
        self.assertEqual(len(self.calls('session/prompt')), 1)

    def test_cleanup_failure_is_persisted_and_reuse_never_relaunches(self):
        command = self.command('linger_after_prompt')
        with deny_owned_cleanup(), patch.object(sys,'argv',command[1:]), redirect_stdout(io.StringIO()):
            self.assertEqual(_main(), 1)
            self.assertEqual(_main(), 1)
            state = json.loads(self.output.read_text())
            self.assertEqual(state['status'], 'needs_inspection')
            self.assertEqual(state['response'], 'No blocking defects found.')
            self.assertEqual(state['session_id'], 'owned')
            self.assertEqual(state['cleanup_error'], 'permission_denied')
            self.assertEqual(state['next_action'], 'inspect_owned_process')
            self.assertTrue(state['end_turn_observed'])
        self.assertEqual(len(self.calls('initialize')), 1)
        self.assertEqual(len(self.calls('session/prompt')), 1)
        self.assertFalse(self.calls('session/load'))
