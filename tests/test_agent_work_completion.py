"""A finish receipt cannot turn partial multi-outcome delivery into completion."""

import tempfile
import unittest
import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_finish_check_steps import read_preflight
from agent_gate_evidence import record_gate_evidence
from test_agent_run_interruption import Run


class WorkCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run(self.tmp.name, packet=True, writable=True)
        self.remaining = [
            {"checkpoint": "worktrees", "action": "Deliver approved worktree cleanup"},
            {"checkpoint": "local branches", "action": "Deliver approved local branch cleanup"},
        ]
        self.checkpoint(kind="initial", remaining=self.remaining)

    def checkpoint(self, *, kind="decision", remaining=None, blockers=None, phase="acting", mutation=None):
        return write_continuation_checkpoint(
            project=self.run.project, rules=self.run.project, run_id=self.run.run["run_id"],
            binding_path=self.run.evidence, kind=kind, phase=phase, mutation=mutation,
            work={"objective": "All three approved cleanup outcomes", "remaining_work": remaining or [],
                  "blockers": blockers or []})

    def finish_failures(self):
        failures = []
        read_preflight(self.run.evidence, failures, project=self.run.project)
        return failures

    def test_passed_route_gates_cannot_hide_remaining_requested_outcomes(self):
        for gate in self.run.route["gates"]:
            record_gate_evidence(evidence_path=self.run.evidence, preflight=self.run.binding,
                                 gate=gate, status="SUCCESS", evidence="Verified the declared route check")
        self.assertTrue(any("requested work remains unfinished" in x for x in self.finish_failures()))
        self.assertEqual("running", self.run.state())
        self.assertFalse(list((self.run.project / ".moru").rglob("finish.json")))

    def test_observed_delivery_and_empty_remaining_work_allow_finish_checks(self):
        for name in ("remote-result", "worktree-result", "local-branch-result"):
            (self.run.project / name).write_text("verified\n")
        self.checkpoint(remaining=[])
        self.assertEqual([], self.finish_failures())

    def test_global_blocker_is_partial_progress_without_completion(self):
        self.checkpoint(phase="blocked", blockers=["User decision is required"])
        self.assertTrue(any("unresolved blockers" in x for x in self.finish_failures()))

    def test_default_start_label_cannot_stand_in_for_reconciling_the_requested_scope(self):
        write_continuation_checkpoint(project=self.run.project, rules=self.run.project,
            run_id=self.run.run["run_id"], binding_path=self.run.evidence, kind="decision",
            work={"objective": "task workflow", "remaining_work": []})
        self.assertTrue(any("scope has not been reconciled" in x for x in self.finish_failures()))

    def test_pending_delivery_refuses_finish_without_failing_or_closing_the_active_run(self):
        from test_agent_hook_continuation import agent_hook

        args = SimpleNamespace(project=self.run.project, rules=self.run.project, evidence=self.run.evidence)
        with (patch.object(agent_hook, "_transferred_cancellation", return_value=(None, None)),
              patch.object(agent_hook, "_replaced_run_finish", return_value=None),
              patch.object(agent_hook, "run_script_main") as checks,
              redirect_stdout(io.StringIO()) as output):
            self.assertEqual(3, agent_hook.finish_hook(args))
        checks.assert_not_called()
        self.assertIn("delivery is still pending", output.getvalue())
        self.assertEqual("running", self.run.state())

    def test_real_finish_cli_keeps_partial_work_active_without_a_completion_receipt(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        env = dict(os.environ, CODEX_THREAD_ID="bound-session", CLAUDE_CODE_SESSION_ID="",
                   MORU_STATE_HOME=self.tmp.name + "/global-state")
        result = subprocess.run([sys.executable, "-B", str(scripts / "agent-hook.py"), "finish",
            "--project", str(self.run.project), "--rules", str(self.run.project),
            "--evidence", str(self.run.evidence)], text=True, capture_output=True, env=env)
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("delivery is still pending", result.stdout)
        self.assertEqual("running", self.run.state())
        self.assertFalse(list((self.run.project / ".moru").rglob("finish.json")))

    def test_an_unresolved_mutation_cannot_receive_a_completion_receipt(self):
        self.checkpoint(kind="pre_mutation", mutation={"kind": "update", "paths": ["source.txt"]})
        self.assertTrue(any("unresolved operation" in x for x in self.finish_failures()))

    def test_changed_binding_requires_reconciliation_instead_of_old_completion(self):
        import json

        altered = dict(self.run.binding, request_intake={"request": "different authorized action"})
        self.run.evidence.write_text(json.dumps(altered))
        self.assertTrue(any("unreadable or stale" in x for x in self.finish_failures()))

    def test_legacy_and_read_only_runs_keep_their_existing_completion_contract(self):
        import json

        for route in ({"command": "task"}, {"command": "analysis", "lifecycle_version": 2}):
            self.run.evidence.write_text(json.dumps({**self.run.binding, "route": route}))
            self.assertEqual([], self.finish_failures())

    def test_small_change_default_label_allows_finish_when_no_remaining_work_exists(self):
        import json

        for command in ("small-change", "writing", "editorial"):
            with self.subTest(command=command):
                light_route = {**self.run.route, "command": command}
                self.run.evidence.write_text(json.dumps({**self.run.binding, "route": light_route}))
                write_continuation_checkpoint(
                    project=self.run.project, rules=self.run.project, run_id=self.run.run["run_id"],
                    binding_path=self.run.evidence, kind="decision",
                    work={"objective": f"{command} workflow", "remaining_work": []})
                self.assertEqual([], self.finish_failures())

    def publication(self, **work):
        import json

        self.run.route.update(command="commit", gates=["request intake", "review hook", "commit readiness"])
        self.run.route["request_classification"]["intent_envelope"].update(
            authority="envelope", schema_valid=True, failures=[], effective_effect="external_write")
        self.run.evidence.write_text(json.dumps(self.run.binding))
        return write_continuation_checkpoint(project=self.run.project, rules=self.run.project,
            run_id=self.run.run["run_id"], binding_path=self.run.evidence, kind="decision",
            work={"objective": "commit workflow", "remaining_work": [], **work})

    def test_commit_pr_readiness_precedes_its_actual_publication_actions(self):
        pending = [{"checkpoint": "publication.commit", "action": "Create the authorized commit after finish"},
                   {"checkpoint": "publication.pull-request/main", "action": "Create the authorized PR after finish"}]
        packet = self.publication(remaining_work=pending)
        self.assertEqual([], self.finish_failures())
        self.assertEqual(pending, packet["work"]["remaining_work"])
        self.assertEqual("running", self.run.state())

    def test_commit_cannot_defer_unfinished_implementation_with_publication(self):
        self.publication(remaining_work=[
            {"checkpoint": "publication.commit", "action": "Commit after finish"},
            {"checkpoint": "implementation", "action": "Complete the requested behavior"}])
        self.assertTrue(any("remains unfinished" in x for x in self.finish_failures()))

    def test_commit_keeps_implementation_requirements_as_context_not_current_gates(self):
        required = {"revision": 1, "items": [{"id": "r1", "outcome": "Implement the requested behavior",
                    "owner": "lead", "gate": "tests", "artifacts": ["implementation.md"]}]}
        with patch("agent_completion_checks.requirement_update"):
            packet = self.publication(requirements=required)
        with patch("agent_completion_checks.coverage_failures") as coverage:
            self.assertEqual([], self.finish_failures())
        coverage.assert_not_called()
        self.assertEqual(required, packet["work"]["requirements"])

    def test_publication_still_refuses_blockers_pending_operations_and_stale_binding(self):
        import json

        self.publication(blockers=["Publication authorization unresolved"])
        self.assertTrue(any("unresolved blockers" in x for x in self.finish_failures()))
        self.publication(blockers=[])
        self.checkpoint(kind="pre_mutation", mutation={"kind": "update", "paths": ["source.txt"]})
        self.assertTrue(any("unresolved operation" in x for x in self.finish_failures()))
        altered = dict(self.run.binding, request_intake={"request": "foreign scope"})
        self.run.evidence.write_text(json.dumps(altered))
        self.assertTrue(any("unreadable or stale" in x for x in self.finish_failures()))

    def test_real_commit_finish_still_rejects_missing_review_and_readiness(self):
        self.publication(remaining_work=[{"checkpoint": "publication.pull-request/main", "action": "Create authorized PR after finish"}])
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        env = dict(os.environ, CODEX_THREAD_ID="bound-session", CLAUDE_CODE_SESSION_ID="",
                   MORU_STATE_HOME=self.tmp.name + "/global-state")
        result = subprocess.run([sys.executable, "-B", str(scripts / "agent-hook.py"), "finish",
            "--project", str(self.run.project), "--rules", str(self.run.project),
            "--evidence", str(self.run.evidence)], text=True, capture_output=True, env=env, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("requested delivery is still pending", result.stdout)
        self.assertIn("missing required gate evidence", result.stdout)
        self.assertIn("review hook", result.stdout)
        self.assertNotEqual("completed", self.run.state())
