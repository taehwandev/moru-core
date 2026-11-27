"""HQ follow-up attempts reuse unchanged evidence; contradictions stop with one question."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_agent_gate_reuse as fixture
from agent_gate_evidence import merge_gate_evidence_from_ledger
from agent_hq_report import MAX_REPORT_BYTES, emit_hq_decision_report, main
from agent_work_continuity import WorkContinuity

OTHER_SESSION = {"runtime": "claude", "session_id": "hq-attempt-2"}
ATTESTED = "HQ follow-up attempt; same toolchain and external inputs"


class HqFollowUpContinuityTests(unittest.TestCase):
    setUp_base = fixture.GateEvidenceReuseTests.setUp
    git = staticmethod(fixture.GateEvidenceReuseTests.git)
    make_run = fixture.GateEvidenceReuseTests.make_run
    record_source = fixture.GateEvidenceReuseTests.record_source

    def setUp(self):
        self.setUp_base()
        self.bind(self.source.evidence, hq="task-1")

    @staticmethod
    def bind(path, hq=None, session=None):
        payload = json.loads(path.read_text())
        if hq:
            payload["hq_run_id"] = hq
        if session:
            payload["runtime_session"] = session
        path.write_text(json.dumps(payload))

    def attempt(self, hq="task-1", reason=ATTESTED):
        """A second attempt: new runtime session, no --continue-from named by the agent."""
        self.bind(self.target.evidence, hq=hq, session=OTHER_SESSION)
        self.target.continue_from = ""
        self.target.reuse_inputs = reason
        with patch.dict("os.environ", {"MORU_HQ_RUN_ID": hq}), \
                patch("agent_work_continuity.runtime_session", return_value=OTHER_SESSION):
            continuity = WorkContinuity(self.target)
            return continuity, continuity.apply(self.target.evidence)

    def passed(self):
        payload = json.loads(self.target.evidence.read_text())
        return merge_gate_evidence_from_ledger(route=payload["route"], evidence_path=self.target.evidence)[0]

    def test_follow_up_attempt_links_and_carries_unchanged_tests_across_sessions(self):
        self.record_source()
        continuity, details = self.attempt()
        self.assertEqual(self.source_id, continuity.source_id)
        self.assertEqual(self.source_id, self.target.continue_from)
        self.assertIn("Carried local gates: ['tests']", details)
        self.assertIn("tests", self.passed())
        self.assertNotIn("review hook", self.passed())
        self.assertEqual(self.source_id, json.loads(self.target.evidence.read_text())["work"]["id"])

    def test_changed_inputs_link_history_but_do_not_carry(self):
        self.record_source()
        (self.project / "README.md").write_text("the answer changed this file")
        continuity, details = self.attempt()
        self.assertEqual(self.source_id, continuity.source_id)
        self.assertNotIn("tests", self.passed())
        self.assertIn("Local gate not carried: tests; missing, stale or incompatible evidence; revalidate this gate.", details)

    def test_without_attestation_nothing_carries(self):
        self.record_source()
        continuity, details = self.attempt(reason="")
        self.assertEqual(self.source_id, continuity.source_id)
        self.assertNotIn("tests", self.passed())

    def test_other_hq_task_is_not_linked_and_attestation_is_dropped_not_refused(self):
        self.record_source()
        continuity, details = self.attempt(hq="task-2")
        self.assertEqual("", continuity.source_id)
        self.assertIn("no earlier attempt of this HQ task", details[0])
        self.assertNotIn("tests", self.passed())

    def test_named_source_from_another_session_still_needs_the_same_hq_task(self):
        # Negative control: an explicit foreign-session source without a shared
        # HQ binding keeps the existing refusal.
        self.record_source()
        self.bind(self.source.evidence, hq="task-9")
        self.target.continue_from = self.source_id
        self.target.reuse_inputs = ATTESTED
        with patch.dict("os.environ", {"MORU_HQ_RUN_ID": "task-1"}), \
                patch("agent_work_continuity.runtime_session", return_value=OTHER_SESSION):
            continuity = WorkContinuity(self.target)
        self.assertIn("another session", continuity.dropped)


class HqDecisionReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()

    def test_contradiction_writes_one_bounded_question_with_options(self):
        path = emit_hq_decision_report(
            project=self.project, question="Which field owns the price: Order or Cart?",
            evidence="spec says Cart, schema says Order " * 20,
            options=["Order owns it", "Cart owns it " * 10, "Both, synced", "a fourth"],
            env={"MORU_HQ_RUN_ID": "task-1"})
        raw = path.read_bytes()
        report = json.loads(raw)
        self.assertLessEqual(len(raw), MAX_REPORT_BYTES)
        self.assertEqual("decision_needed", report["status"])
        self.assertEqual(self.project / ".moru/hq/reports/task-1.json", path)
        self.assertLessEqual(len(report["decisionOptions"]), 3)
        self.assertTrue(all(len(option) <= 60 for option in report["decisionOptions"]))
        self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_outside_hq_nothing_is_written_and_cli_says_what_to_do(self):
        self.assertIsNone(emit_hq_decision_report(project=self.project, question="q", evidence="e",
                                                  options=[], env={}))
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(2, main(["decision", "--project", str(self.project), "--question", "q"]))
        self.assertFalse((self.project / ".moru").exists())

    def test_cli_writes_report_for_hq_process(self):
        with patch.dict("os.environ", {"MORU_HQ_RUN_ID": "task-7"}):
            code = main(["decision", "--project", str(self.project), "--question", "Keep v1 API?",
                         "--option", "keep", "--option", "drop"])
        self.assertEqual(0, code)
        report = json.loads((self.project / ".moru/hq/reports/task-7.json").read_text())
        self.assertEqual(["keep", "drop"], report["decisionOptions"])


if __name__ == "__main__":
    unittest.main()
