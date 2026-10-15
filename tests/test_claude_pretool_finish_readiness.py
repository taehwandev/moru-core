from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_gate_evidence import record_gate_evidence, reset_gate_evidence_ledger
from agent_hook_gate_records import gate_batch_hook
from claude_pretool_finish_readiness import finish_readiness_denial
from support.stable_launcher import stable_launcher_path

SPEC = importlib.util.spec_from_file_location("finish_readiness_hook", ROOT / "scripts/agent-hook.py")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)

GATE_SPEC = importlib.util.spec_from_file_location("finish_readiness_pretool", ROOT / "scripts/claude_pretool_gate.py")
GATE = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(GATE)


class FinishReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "AGENTS.md").write_text("# Fixture project\n")
        self.evidence = self.project / ".moru/preflight.json"
        self.evidence.parent.mkdir()
        self.preflight = {
            "agent_run_id": "a" * 32,
            "project": str(self.project),
            "route": {"command": "bugfix", "gates": ["tests", "retrospective check"],
                      "required_docs": ["common/skills/agent-operating-skill/SKILL.md"]},
        }
        self.evidence.write_text(json.dumps(self.preflight))
        reset_gate_evidence_ledger(self.evidence, self.preflight)
        self.command = [str(stable_launcher_path()), "finish", "--project", str(self.project)]

    def denial(self, command=None):
        return finish_readiness_denial(
            self.command if command is None else command, self.project, "fixture",
            lambda project, session: self.evidence,
        )

    def record(self, gate, status="SUCCESS"):
        fields = {"check": "fixture command", "result": "exit 0"} if gate == "tests" else {
            "skills_checked": "agent_operating_skill", "outcome": "no_reusable_gap", "observation": "not_needed",
        }
        record_gate_evidence(evidence_path=self.evidence, preflight=self.preflight,
                             gate=gate, fields=fields, status=status, source="fixture")

    def test_rejected_skill_record_blocks_finish_without_failing_a_checkpoint(self):
        self.record("tests")
        record = {"gate": "retrospective check", "status": "SUCCESS", "fields": {
            "skills_checked": "agent_operating_skill,unknown_external_skill",
            "outcome": "no_reusable_gap", "observation": "not_needed",
        }}
        args = HOOK.build_parser().parse_args([
            "gate-batch", "--project", str(self.project), "--rules", str(ROOT),
            "--evidence", str(self.evidence), "--gate-record", json.dumps(record),
        ])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(1, gate_batch_hook(args))
        self.assertIn("unknown canonical skills", output.getvalue())
        self.assertIn("retrospective check", self.denial())
        self.assertFalse((self.evidence.parent / "repair-checkpoints.json").exists())

    def test_corrected_record_releases_finish(self):
        self.record("tests")
        self.assertIn("retrospective check", self.denial())
        self.record("retrospective check")
        self.assertEqual("", self.denial())

    def test_latest_failed_gate_cannot_reuse_an_earlier_success(self):
        self.record("tests")
        self.record("retrospective check")
        self.record("tests", "FAIL")
        self.assertIn("tests", self.denial())

    def test_terminal_receipts_reach_finish_for_validation_without_source_gates(self):
        for run in (
            {"state": "cancelled", "superseded_by": "b" * 32},
            {"state": "cancelled", "cancellation": {}},
            {"state": "running", "cancellation": {}},
        ):
            with self.subTest(run=run), patch(
                "claude_pretool_finish_readiness.registered_run", return_value=run, create=True,
            ):
                self.assertEqual("", self.denial())

    def test_cancelled_run_without_receipt_cannot_skip_missing_gates(self):
        with patch("claude_pretool_finish_readiness.registered_run",
                   return_value={"state": "cancelled"}, create=True):
            self.assertIn("tests", self.denial())

    def test_unreadable_ledger_stays_blocked(self):
        self.evidence.write_text("invalid json")
        self.assertIn("cannot be read", self.denial())

    def test_other_hooks_and_help_remain_available(self):
        for action in ("gate-batch", "review", "repair-verify", "checkpoint"):
            with self.subTest(action=action):
                self.assertEqual("", self.denial([self.command[0], action]))
        self.assertEqual("", self.denial([*self.command, "--help"]))

    def test_launcher_alias_and_canonical_script_obey_same_prerequisites(self):
        for command in (
            [self.command[0], "agent-hook", *self.command[1:]],
            [sys.executable, str(ROOT / "scripts/agent-hook.py"), *self.command[1:]],
            [str(ROOT / "scripts/agent-hook.py"), *self.command[1:]],
        ):
            with self.subTest(command=command):
                self.assertIn("retrospective check", self.denial(command))

    def test_explicit_evidence_and_relative_project_use_the_requested_run(self):
        command = [self.command[0], "finish", "--project=.", f"--evidence={self.evidence}"]
        self.assertIn("retrospective check", self.denial(command))

    def test_finish_owned_checks_do_not_require_prerecorded_success(self):
        self.preflight["route"]["gates"] = ["finish", "commit readiness", "request intake"]
        self.evidence.write_text(json.dumps(self.preflight))
        reset_gate_evidence_ledger(self.evidence, self.preflight)
        self.assertEqual("", self.denial())

    def test_derived_checks_do_not_hide_missing_agent_owned_gates(self):
        self.preflight["route"]["gates"] = ["finish", "tests"]
        self.evidence.write_text(json.dumps(self.preflight))
        reset_gate_evidence_ledger(self.evidence, self.preflight)
        self.assertIn("tests", self.denial())

    def test_pretool_refuses_finish_before_bootstrap_admission(self):
        payload = {"tool_name": "Bash", "cwd": str(self.project), "session_id": "fixture",
                   "tool_input": {"command": " ".join(self.command)}}
        with patch.object(GATE, "session_evidence", return_value=self.evidence), \
             patch.object(GATE, "_bootstrap_verdict", side_effect=AssertionError("premature finish admitted")), \
             redirect_stdout(io.StringIO()) as output:
            GATE.decide(payload)
        self.assertIn('"permissionDecision": "deny"', output.getvalue())
        self.assertIn("finish must wait", output.getvalue())


if __name__ == "__main__":
    unittest.main()
