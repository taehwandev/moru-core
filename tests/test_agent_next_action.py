"""Tests for agent_next_action.py (`next` step advisor and verification target discovery)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_next_action as next_action  # noqa: E402


class AgentNextActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = mock.patch.dict(os.environ, {"MORU_STATE_HOME": str(self.root / "state-home")})
        env.start()
        self.addCleanup(env.stop)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "-C", str(self.project), "init", "-q"], check=True)
        subprocess.run(
            ["git", "-C", str(self.project), "-c", "user.email=t@example.com", "-c", "user.name=t",
             "commit", "-q", "--allow-empty", "-m", "init"],
            check=True,
        )

    def test_no_active_run_recommends_start(self) -> None:
        info = next_action.inspect_next_action(self.project)
        self.assertEqual("no_active_run", info["status"])
        self.assertEqual("start", info["next_step"])
        self.assertIn("start --project", info["copyable_command"])

    def test_active_run_progresses_from_tests_to_review_to_closeout(self) -> None:
        run_id = "a" * 32
        run_dir = self.project / ".moru" / "runs" / run_id
        run_dir.mkdir(parents=True)
        preflight_path = run_dir / "preflight.json"
        preflight = {
            "agent_run_id": run_id,
            "work": {"id": "b" * 32},
            "route": {
                "command": "small-change",
                "gates": ["tests", "review hook", "retrospective check"],
                "required_docs": ["common/skills/agent-operating-skill/SKILL.md"],
            },
        }
        preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

        step1 = next_action.inspect_next_action(self.project, evidence=preflight_path)
        self.assertEqual("active_run", step1["status"])
        self.assertEqual("record_pre_review_gates", step1["next_step"])
        self.assertIn("gate-batch", step1["copyable_command"])
        self.assertIn('"gate":"tests"', step1["copyable_command"])

        from agent_gate_evidence import record_gate_evidence
        record_gate_evidence(
            evidence_path=preflight_path,
            preflight=preflight,
            gate="tests",
            evidence="passed",
            fields={"check": "unittest", "result": "1 passed"},
        )
        step2 = next_action.inspect_next_action(self.project, evidence=preflight_path)
        self.assertEqual("review", step2["next_step"])
        self.assertIn("review --project", step2["copyable_command"])

    def test_closeout_command_leaves_outcomes_for_the_agent(self) -> None:
        command = next_action._build_gate_batch_command(
            "L", self.project, self.project / "preflight.json",
            ["retrospective check"], ["bugfix_debugging"],
        )
        record = json.loads(command.split("--gate-record '", 1)[1].rstrip("'"))[0]
        self.assertEqual("bugfix_debugging", record["fields"]["skills_checked"])
        self.assertEqual("<no_reusable_gap|no_skill_used|reusable_gap>", record["fields"]["outcome"])
        self.assertEqual("<not_needed|recorded>", record["fields"]["observation"])
        self.assertIn("alignment_evidence", record["fields"])
        self.assertIn("causal_assessment", record["fields"])
        self.assertIn("learning_decision", record["fields"])
        self.assertEqual("<SUCCESS or FAIL>", record["status"])

    def test_another_sessions_registered_run_is_not_selected(self) -> None:
        run_dir = self.project / ".moru" / "runs" / ("c" * 32)
        run_dir.mkdir(parents=True)
        (run_dir / "preflight.json").write_text("{}", encoding="utf-8")
        (self.project / ".moru" / "preflight.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(next_action, "runtime_session", return_value={}):
            info = next_action.inspect_next_action(self.project)
        self.assertEqual("no_active_run", info["status"])
        self.assertIn("--rules", info["copyable_command"])
        self.assertIn("--command <route>", info["copyable_command"])

    def test_suggest_verification_targets_maps_python_files_to_matching_tests(self) -> None:
        (self.project / "scripts").mkdir()
        (self.project / "tests").mkdir()
        (self.project / "scripts" / "foo_bar.py").write_text("x = 1\n", encoding="utf-8")
        (self.project / "tests" / "test_foo_bar.py").write_text("import unittest\n", encoding="utf-8")

        ver = next_action.suggest_verification_targets(self.project)
        self.assertIn("tests.test_foo_bar", ver["matched_test_modules"])
        self.assertTrue(any("py_compile" in cmd for cmd in ver["suggested_commands"]))
        self.assertTrue(any("tests.test_foo_bar" in cmd for cmd in ver["suggested_commands"]))

    def test_cli_json_and_markdown_outputs(self) -> None:
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(0, next_action.main(["--project", str(self.project), "--format", "json"]))
        data = json.loads(out.getvalue())
        self.assertEqual("no_active_run", data["status"])


if __name__ == "__main__":
    unittest.main()
