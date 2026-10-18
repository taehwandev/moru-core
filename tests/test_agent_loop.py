"""Consumer-facing CLI, actual subprocess checks and durable output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from _moru_test_support import ROOT
import test_agent_loop_state as fixture


class LoopCliTests(unittest.TestCase):
    def setUp(self):
        self.project, self.evidence, self.run_id = fixture.loop_fixture(self)

    def cli(self, command, *arguments, environment=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_loop.py"), command,
                               "--project", str(self.project), "--run-id", self.run_id, *arguments],
                              cwd=self.project, env=environment, capture_output=True, text=True, timeout=20)

    def enroll(self, iterations="3"):
        return self.cli("start", "--objective", "value at most six", "--path", "value.txt",
                        "--verifier-path", "tests/test_goal.py", "--verifier-path", "tests/test_regression.py",
                        "--goal-pattern", "test_goal.py", "--regression-pattern", "test_regression.py",
                        "--max-iterations", iterations, "--max-seconds", "60", "--max-model-calls", "5")

    def test_cli_proves_fixed_goal_and_emits_only_json_on_stdout(self):
        baseline = self.enroll()
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        self.assertEqual("ready", json.loads(baseline.stdout)["status"])
        self.assertIn("Ran 1 test", baseline.stderr)
        begun = self.cli("begin", "--hypothesis", "fix the actual value")
        self.assertEqual(0, begun.returncode, begun.stderr)
        (self.project / "value.txt").write_text("5")
        checked = self.cli("check")
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["attempt"]["result"]["goal"]["passed"])
        accepted = self.cli("accept")
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("succeeded", json.loads(accepted.stdout)["status"])
        persisted = self.cli("status")
        self.assertEqual("accepted", json.loads(persisted.stdout)["history"][0]["verdict"])

    def test_cli_denies_unrestored_rejection_and_foreign_session(self):
        self.assertEqual(0, self.enroll().returncode)
        self.assertEqual(0, self.cli("begin", "--hypothesis", "rejected change").returncode)
        (self.project / "value.txt").write_text("9")
        self.assertEqual(0, self.cli("check").returncode)
        self.assertEqual(2, self.cli("reject").returncode)
        self.assertEqual("9", (self.project / "value.txt").read_text())
        foreign = dict(os.environ, CODEX_THREAD_ID="another-session")
        refused = self.cli("cancel", environment=foreign)
        self.assertEqual(2, refused.returncode)
        self.assertIn("active run", refused.stderr)
        (self.project / "value.txt").write_text("10")
        self.assertEqual(0, self.cli("reject").returncode)

    def test_cli_exhaustion_is_distinct_from_success(self):
        self.assertEqual(0, self.enroll("1").returncode)
        self.assertEqual(0, self.cli("begin", "--hypothesis", "one attempt").returncode)
        (self.project / "value.txt").write_text("8")
        self.assertEqual(0, self.cli("check").returncode)
        (self.project / "value.txt").write_text("10")
        exhausted = self.cli("reject")
        self.assertEqual(4, exhausted.returncode, exhausted.stderr)
        self.assertEqual("exhausted", json.loads(exhausted.stdout)["status"])
        self.assertEqual(2, self.enroll().returncode)

    def test_cli_oversized_calls_are_invalid_without_exhausting_remaining_budget(self):
        self.assertEqual(0, self.enroll().returncode)
        path = self.evidence.parent / "loop.json"
        before = path.read_bytes()
        refused = self.cli("begin", "--hypothesis", "oversized", "--calls", "6")
        self.assertEqual(2, refused.returncode, refused.stderr)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0, self.cli("begin", "--hypothesis", "smaller", "--calls", "1").returncode)
        before = path.read_bytes()
        self.assertEqual(2, self.cli("reserve", "--calls", "5").returncode)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0, self.cli("reserve", "--calls", "1").returncode)

    def test_launcher_dispatches_loop_help_without_installation(self):
        from support.stable_launcher import _launcher_script_text
        launcher = self.project / "moru-hook"
        launcher.write_text(_launcher_script_text())
        result = subprocess.run([sys.executable, str(launcher), "loop", "--help"],
                                env=dict(os.environ, MORU_HOME=str(ROOT)), capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("max", self.cli("start", "--help").stdout)
        self.assertIn("accept", result.stdout)
