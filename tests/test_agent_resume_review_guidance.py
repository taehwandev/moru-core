"""Resume guidance observes the current binding after runtime reattachment."""

import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_hook_resume


class ResumeReviewGuidanceTests(unittest.TestCase):
    def run_case(self, *, gates=None, checkpoint="finish", failures=None,
                 refused=False, unreadable=False, recorded=False, programming_error=False):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / "preflight.json"
            evidence.write_text(json.dumps({"route": {"gates": gates if gates is not None else
                                                     ["act", "review hook", "handoff"]}}))
            result = dict(result="live_owner_refused" if refused else "ready", reason="",
                          run_id="a" * 32, evidence_path=str(evidence), route_command="bugfix",
                          resume_generation=1, checkpoint=checkpoint, holder_state="free",
                          changed_signals=[], affected_paths=[], work={"objective": "retained objective"},
                          reuse={"successful_verification": [{"id": "regression", "kind": "unit"}]})
            args = Namespace(project=project, rules=project, runtime="claude",
                             runtime_session_id="resumed-session", output=None, repair_cycle=0)
            if recorded:
                args.runtime = args.runtime_session_id = ""
            rebound = []

            def rebind(**kwargs):
                rebound.append(True)
                payload = json.loads(evidence.read_text())
                payload["runtime_session"] = {"session_id": "resumed-session"}
                evidence.write_text("private-invalid-binding" if unreadable else json.dumps(payload))

            def validate(**kwargs):
                self.assertEqual([True], rebound)
                current = json.loads(evidence.read_text())
                self.assertEqual("resumed-session", current["runtime_session"]["session_id"])
                if programming_error:
                    raise TypeError("invalid validator invocation")
                return failures or []

            output = io.StringIO()
            with (
                patch.object(agent_hook_resume, "resume_last", return_value=result),
                patch.object(agent_hook_resume, "bind_resumed_runtime_session", side_effect=rebind),
                patch.object(agent_hook_resume, "rebind_recorded_runtime_session", side_effect=rebind),
                patch("agent_gate_evidence.merge_gate_evidence_from_ledger", return_value=(
                    {"review hook": "previous review"}, {"entry_fields": {}, "sources": {}})),
                patch("agent_review_attestation.ReviewAttestation.failures", side_effect=validate) as check,
                redirect_stdout(output),
            ):
                code = agent_hook_resume._resume_last(args)
            self.assertEqual(checkpoint, result["checkpoint"])
            return code, output.getvalue(), check.call_count

    def test_stale_review_is_the_next_checkpoint_after_session_rebind(self):
        code, output, calls = self.run_case(failures=["preflight binding is stale"])
        self.assertEqual(0, code)
        self.assertEqual(1, calls)
        self.assertIn("resume checkpoint: review hook", output)
        self.assertIn("refresh the required review before finish", output)
        self.assertIn("verification=regression(unit)", output)

    def test_current_review_does_not_add_another_review(self):
        code, output, calls = self.run_case()
        self.assertEqual((0, 1), (code, calls))
        self.assertIn("resume checkpoint: finish", output)
        self.assertNotIn("refresh the required review", output)

    def test_no_review_route_keeps_its_checkpoint(self):
        code, output, calls = self.run_case(gates=["act", "handoff"])
        self.assertEqual((0, 0), (code, calls))
        self.assertIn("resume checkpoint: finish", output)

    def test_an_earlier_unfinished_gate_stays_first(self):
        code, output, calls = self.run_case(checkpoint="act")
        self.assertEqual((0, 0), (code, calls))
        self.assertIn("resume checkpoint: act", output)

    def test_refusal_never_checks_or_renders_review_advice(self):
        code, output, calls = self.run_case(refused=True)
        self.assertEqual((1, 0), (code, calls))
        self.assertNotIn("retained objective", output)
        self.assertNotIn("refresh the required review", output)

    def test_unreadable_binding_requires_inspection_without_echoing_values(self):
        code, output, calls = self.run_case(unreadable=True)
        self.assertEqual((0, 0), (code, calls))
        self.assertIn("resume checkpoint: finish", output)
        self.assertIn("next action: inspect resume evidence", output)
        self.assertNotIn("private-invalid-binding", output)

    def test_a_later_handoff_checkpoint_refreshes_review_first(self):
        code, output, calls = self.run_case(checkpoint="handoff", failures=["stale binding"])
        self.assertEqual((0, 1), (code, calls))
        self.assertIn("resume checkpoint: review hook", output)

    def test_recorded_runtime_rebind_is_checked_after_rebinding_too(self):
        code, output, calls = self.run_case(recorded=True, failures=["stale binding"])
        self.assertEqual((0, 1), (code, calls))
        self.assertIn("resume checkpoint: review hook", output)

    def test_validator_programming_errors_are_not_hidden_as_inspection_advice(self):
        with self.assertRaisesRegex(TypeError, "invalid validator invocation"):
            self.run_case(programming_error=True)

    def test_real_review_becomes_stale_after_real_runtime_rebind(self):
        from agent_gate_evidence import (
            merge_gate_evidence_from_ledger, record_gate_evidence, reset_gate_evidence_ledger,
        )
        from agent_review_attestation import ReviewAttestation
        from agent_runtime_session import bind_resumed_runtime_session
        from test_agent_review_attestation import initialize_repository
        from test_agent_runtime_session import RuntimeFixture

        route = {"command": "review", "gates": ["review hook"], "required_docs": []}
        with tempfile.TemporaryDirectory() as directory, patch("test_agent_runtime_session.ROUTE", route):
            fixture = RuntimeFixture(directory)
            initialize_repository(fixture.project)
            initialize_repository(fixture.rules)
            fixture.preflight["agent_run_id"] = fixture.run_id
            fixture.evidence.write_text(json.dumps(fixture.preflight))
            reset_gate_evidence_ledger(fixture.evidence, fixture.preflight)
            review = ReviewAttestation.record(
                project=fixture.project, rules=fixture.rules, evidence_path=fixture.evidence,
                preflight=fixture.preflight, review_scope="pathspec: tracked.txt",
                review_paths=["tracked.txt"], changed_path_count=0,
                checks={"review_outcome": "pass", "workflow_validate": {"returncode": 0},
                        "diff_check": {"returncode": 0},
                        "vibeguard": {"returncode": 0, "overall": "Ready"}},
            )
            record_gate_evidence(
                evidence_path=fixture.evidence, preflight=fixture.preflight, gate="review hook",
                evidence="observed synthetic review", fields=ReviewAttestation.ledger_fields(review),
                status="SUCCESS", source="review",
            )
            result = {"evidence_path": str(fixture.evidence), "checkpoint": "finish", "reuse": {}}
            current = agent_hook_resume._review_resume_checkpoint(
                result, project=fixture.project, rules=fixture.rules)
            self.assertEqual("finish", current["checkpoint"])
            review_bytes = ReviewAttestation.path(fixture.evidence).read_bytes()
            fixture.set_generation(1)
            bind_resumed_runtime_session(
                project=fixture.project, evidence_path=fixture.evidence, run_id=fixture.run_id,
                resume_generation=1, runtime="claude", session_id="new-session",
            )
            resumed = agent_hook_resume._review_resume_checkpoint(
                result, project=fixture.project, rules=fixture.rules)
            gates, ledger = merge_gate_evidence_from_ledger(route=route, evidence_path=fixture.evidence)
            self.assertIn("review hook", gates)
            failures = ReviewAttestation.failures(
                project=fixture.project, rules=fixture.rules, evidence_path=fixture.evidence,
                route=route, ledger_fields=ledger["entry_fields"]["review hook"],
                ledger_source=ledger["sources"]["review hook"],
            )
            self.assertIn("review hook attestation preflight binding is stale or foreign", failures)
            self.assertEqual("review hook", resumed["checkpoint"])
            self.assertTrue(resumed["review_refresh_required"])
            self.assertEqual(result["reuse"], resumed["reuse"])
            self.assertEqual(review_bytes, ReviewAttestation.path(fixture.evidence).read_bytes())


if __name__ == "__main__":
    unittest.main()
