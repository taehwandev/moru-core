"""Lost checklist outcomes remain visible from the exact original intake."""
import json
import unittest
import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from agent_intake_context import IntakeContext


class IntakeContextTests(unittest.TestCase):
    def setUp(self):
        from test_agent_work_continuity import RetainedWorkSummaryTests
        self.fixture = RetainedWorkSummaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source, self.target = self.fixture.source, self.fixture.target
        self.source.preflight["request_intake"] = {"request": "Deliver feature A and feature B.",
                                                  "continuation_scope": "Keep keyboard access."}
        self.source.preflight["runtime_session"] = {"runtime": "codex", "session_id": "same-session"}
        self.fixture.write_preflight(self.source)
        self.source.checkpoint("decision", work={"acceptance_criteria": ["Deliver feature A."]})
        self.target.preflight["request_intake"] = {"request": "Continue."}
        self.target.preflight["runtime_session"] = self.source.preflight["runtime_session"]
        self.fixture.write_preflight(self.target)
        self.target.checkpoint("initial", work={"objective": "Deliver feature A."})

    def test_original_scope_survives_an_incomplete_agent_checklist(self):
        before = self.source.binding_path.read_bytes()
        result = IntakeContext.reference(self.target.project, self.target.binding_path)
        self.assertEqual("Deliver feature A and feature B.", result["quoted_intake"]["request"])
        self.assertEqual("Keep keyboard access.", result["quoted_intake"]["continuation_scope"])
        self.assertEqual("reference_only", result["authority"])
        self.assertEqual("Continue.", result["current_intake"]["request"])
        self.assertEqual(before, self.source.binding_path.read_bytes())

    def test_changed_original_binding_and_foreign_project_are_not_inferred(self):
        self.source.preflight["request_intake"]["request"] = "Unbound replacement"
        self.fixture.write_preflight(self.source)
        self.assertIsNone(IntakeContext.reference(self.target.project, self.target.binding_path))
        self.assertIsNone(IntakeContext.reference(self.target.rules, self.target.binding_path))

    def test_large_intake_uses_an_explicit_source_instead_of_truncation(self):
        self.source.preflight["request_intake"]["request"] = "A" * 4000 + "critical final requirement"
        self.fixture.write_preflight(self.source)
        self.source.checkpoint("decision")
        result = IntakeContext.reference(self.target.project, self.target.binding_path)
        self.assertEqual("read_source", result["availability"])
        self.assertNotIn("quoted_intake", result)
        self.assertEqual(str(self.source.binding_path), result["path"])

    def test_foreign_runtime_session_is_not_automatically_quoted(self):
        self.target.preflight["runtime_session"] = {"runtime": "claude", "session_id": "other-session"}
        self.fixture.write_preflight(self.target)
        self.target.checkpoint("decision")
        result = IntakeContext.reference(self.target.project, self.target.binding_path)
        self.assertEqual("read_source", result["availability"])
        self.assertNotIn("quoted_intake", result)

    def test_current_user_revision_remains_visible_beside_the_original(self):
        self.target.preflight["request_intake"]["request"] = "Only A; cancel B and keyboard access."
        self.fixture.write_preflight(self.target)
        self.target.checkpoint("decision")
        note = " ".join(IntakeContext.review_note(self.target.project, self.target.binding_path))
        self.assertIn("feature A and feature B", note)
        self.assertIn("Only A; cancel B and keyboard access.", note)
        self.assertIn("current user changes win", note)

    def test_original_source_symlink_is_not_quoted(self):
        backup = self.source.binding_path.with_name("saved-preflight.json")
        self.source.binding_path.rename(backup)
        self.source.binding_path.symlink_to(backup)
        try:
            self.assertIsNone(IntakeContext.reference(self.target.project, self.target.binding_path))
        finally:
            self.source.binding_path.unlink()
            backup.rename(self.source.binding_path)

    def test_review_note_is_for_implementation_and_does_not_gate_publication(self):
        self.assertIn("feature B", " ".join(IntakeContext.review_note(self.target.project, self.target.binding_path)))
        self.target.preflight["route"] = {**self.target.preflight["route"], "command": "commit"}
        self.fixture.write_preflight(self.target)
        self.assertEqual([], IntakeContext.review_note(self.target.project, self.target.binding_path))

    def test_resume_cli_delivers_original_outcome_missing_from_current_contract(self):
        from agent_hook_resume import resume_hook

        args = SimpleNamespace(references_mode=True, project=self.target.project,
            resume_run_id=self.target.run_id, check_files=False, output=None, repair_cycle=0)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, resume_hook(args))
        self.assertIn("feature B", output.getvalue())
        self.assertIn("Continue.", output.getvalue())
        self.assertIn("reference only", output.getvalue())

    def test_successful_review_delivers_original_scope_without_an_additional_gate(self):
        from agent_review_hook import _review_verdict

        args = SimpleNamespace(project=self.target.project, rules=self.target.rules,
            evidence=self.target.binding_path, output=None, repair_cycle=0,
            doc_takeaway="", allow_vibeguard_review="")
        checks = {"workflow_validate": {}, "diff_check": {}, "vibeguard": {"overall": "Ready"}}
        structure = {"checked_path_count": 0, "scope": "fixture", "net_deletions": []}
        captured = []
        def output(_name, success, details, *_args, **_kwargs):
            captured.extend(details)
            return 0 if success else 1
        with patch("agent_review_hook.record_successful_review_workflow_validation", return_value={}), \
                patch("agent_review_hook.record_review_gate"), patch("agent_review_hook.record_doc_takeaway"):
            self.assertEqual(0, _review_verdict(args, checks, [], structure, "working-tree", output, None))
        self.assertIn("feature B", " ".join(captured))
        self.assertIn("Continue.", " ".join(captured))
        self.assertIn("Machine checks do not establish semantic coverage", " ".join(captured))
