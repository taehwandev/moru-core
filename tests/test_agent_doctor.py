"""Tests for agent_doctor.py (`doctor` read-only diagnostics)."""

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

import agent_doctor as doctor  # noqa: E402


class AgentDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_home = self.root / "state-home"
        env = mock.patch.dict(os.environ, {"TAO_STATE_HOME": str(self.state_home)})
        env.start()
        self.addCleanup(env.stop)
        self.project = self.root / "sample-project"
        self.project.mkdir()
        subprocess.run(["git", "-C", str(self.project), "init", "-q"], check=True)

    def test_detect_project_stacks_identifies_manifests(self) -> None:
        self.assertEqual([], doctor.detect_project_stacks(self.project))
        (self.project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        (self.project / "package.json").write_text('{"scripts":{"test":"jest"}}\n', encoding="utf-8")
        self.assertEqual(["node", "python"], doctor.detect_project_stacks(self.project))

    def test_doctor_reports_missing_agents_and_legacy_state_without_mutating(self) -> None:
        (self.project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        report = doctor.inspect_project_health(self.project)
        self.assertEqual(str(self.project.resolve()), report["project"])
        self.assertIn("python", report["stacks"])
        self.assertFalse(report["instructions"]["agents_md_present"])
        self.assertTrue(any("repo-agents-routing.md" in rec for rec in report["recommendations"]))
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_cli_markdown_and_json_modes(self) -> None:
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doctor.main(["--project", str(self.project), "--format", "json"])
        self.assertEqual(0, code)
        payload = json.loads(out.getvalue())
        self.assertEqual(str(self.project.resolve()), payload["project"])


if __name__ == "__main__":
    unittest.main()
