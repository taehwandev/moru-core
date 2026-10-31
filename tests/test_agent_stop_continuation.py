"""A partially delivered approved task gets one continuation, never new authority."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import claude_stop_gate
import codex_stop_gate
from agent_continuation_checkpoint import write_continuation_checkpoint
from test_agent_run_interruption import Run


class StopContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"MORU_STATE_HOME": self.tmp.name + "/state"})
        env.start()
        self.addCleanup(env.stop)

    def run_fixture(self, runtime="codex", *, phase="acting", blockers=None, writable=True):
        directory = tempfile.mkdtemp(dir=self.tmp.name)
        run = Run(directory, runtime, packet=True, writable=writable)
        write_continuation_checkpoint(
            project=run.project, rules=run.project, run_id=run.run["run_id"],
            binding_path=run.evidence, kind="initial", phase=phase,
            work={"objective": "Deliver all three approved cleanup outcomes",
                  "remaining_work": [{"checkpoint": "worktrees", "action": "Remove approved worktrees"},
                                     {"checkpoint": "local branches", "action": "Finish approved local branches"}],
                  "blockers": blockers or []})
        return run

    def stop(self, run, **flags):
        adapter = codex_stop_gate if run.session["runtime"] == "codex" else claude_stop_gate
        output = io.StringIO()
        payload = {"cwd": str(run.project), "session_id": run.session["session_id"], **flags}
        with patch.object(adapter, "find_project_root", return_value=run.project), redirect_stdout(output):
            self.assertEqual(0, adapter.decide(payload))
        return json.loads(output.getvalue()) if output.getvalue() else None

    def test_partial_cleanup_continues_in_both_runtimes_without_closing_the_run(self):
        for runtime in ("codex", "claude"):
            with self.subTest(runtime=runtime):
                run = self.run_fixture(runtime)
                result = self.stop(run)
                self.assertIsNotNone(result)
                self.assertEqual("block", result["decision"])
                self.assertIn("approved", result["reason"])
                self.assertEqual("running", run.state())
                self.assertFalse(list((run.project / ".moru").rglob("finish.json")))

    def test_a_blocked_item_does_not_abandon_other_declared_executable_work(self):
        run = self.run_fixture(blockers=["A separate target needs a user decision"])
        self.assertEqual("block", self.stop(run)["decision"])

    def test_user_stop_approval_wait_and_retry_budget_allow_the_turn_to_end(self):
        for flags in ({"user_interrupted": True}, {"approval_pending": True},
                      {"waiting_for_approval": True}, {"stop_hook_active": True},
                      {"stop_reason": "cancelled"}):
            with self.subTest(flags=flags):
                run = self.run_fixture()
                self.assertIsNone(self.stop(run, **flags))
                self.assertNotEqual("completed", run.state())

    def test_global_blocker_and_missing_write_authority_never_trigger_continuation(self):
        for options in ({"phase": "blocked", "blockers": ["Waiting for user approval"]},
                        {"writable": False}):
            with self.subTest(options=options):
                self.assertIsNone(self.stop(self.run_fixture(**options)))

    def test_foreign_session_cannot_continue_or_settle_the_owning_run(self):
        run = self.run_fixture()
        self.assertIsNone(self.stop(run, session_id="foreign-session"))
        self.assertEqual("running", run.state())

    def test_unresolved_mutation_is_not_replayed_by_a_stop(self):
        run = self.run_fixture()
        write_continuation_checkpoint(project=run.project, rules=run.project,
            run_id=run.run["run_id"], binding_path=run.evidence, kind="pre_mutation",
            mutation={"kind": "update", "paths": ["source.txt"]})
        self.assertIsNone(self.stop(run))
        self.assertNotEqual("completed", run.state())

    def test_continuation_can_deliver_remaining_outputs_without_another_user_prompt(self):
        from agent_finish_check_steps import read_preflight

        run = self.run_fixture()
        self.assertEqual("block", self.stop(run)["decision"])
        for name in ("worktree-result", "local-branch-result"):
            (run.project / name).write_text("verified delivery\n")
        write_continuation_checkpoint(project=run.project, rules=run.project,
            run_id=run.run["run_id"], binding_path=run.evidence, kind="decision",
            phase="verifying", work={"remaining_work": []})
        failures = []
        read_preflight(run.evidence, failures, project=run.project)
        self.assertEqual([], failures)
        self.assertIsNone(self.stop(run, stop_hook_active=True))

    def test_pending_operator_approval_prevents_automatic_work(self):
        import time

        run = self.run_fixture()
        directory = Path(self.tmp.name) / "state" / "codex-operator-review"
        directory.mkdir(parents=True)
        (directory / "pending.json").write_text(json.dumps({
            "session_id": "bound-session", "status": "pending", "expires_at": time.time() + 60}))
        self.assertIsNone(self.stop(run))

    def test_reading_only_without_scope_accounting_gets_one_reconciliation_pass(self):
        run = self.run_fixture()
        write_continuation_checkpoint(project=run.project, rules=run.project,
            run_id=run.run["run_id"], binding_path=run.evidence, kind="decision",
            work={"objective": "task workflow", "remaining_work": []})
        self.assertEqual("block", self.stop(run)["decision"])

    def test_malformed_lifecycle_version_cannot_gain_continuation(self):
        run = self.run_fixture()
        preflight = json.loads(run.evidence.read_text())
        preflight["route"]["lifecycle_version"] = 2.0
        run.evidence.write_text(json.dumps(preflight))
        self.assertIsNone(self.stop(run))

    def test_native_entrypoints_emit_continuation_without_a_model_or_another_user_prompt(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        for runtime, name in (("codex", "codex_stop_gate.py"), ("claude", "claude_stop_gate.py")):
            with self.subTest(runtime=runtime):
                run = self.run_fixture(runtime)
                payload = {"cwd": str(run.project), "session_id": "bound-session"}
                result = subprocess.run([sys.executable, "-B", str(scripts / name)],
                    input=json.dumps(payload), text=True, capture_output=True, cwd=run.project)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("block", json.loads(result.stdout)["decision"])
                self.assertEqual("running", run.state())
