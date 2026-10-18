"""Real checks and durable bounded-loop transitions in isolated repositories."""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _moru_test_support import ROOT
from agent_loop_state import LoopRun
from agent_run_registry import register_run, request_fingerprint, route_fingerprint, transition_run


def loop_fixture(case):
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    project = Path(temporary.name).resolve()
    environment = patch.dict(os.environ, {"CODEX_THREAD_ID": "loop-fixture", "CLAUDE_CODE_SESSION_ID": "",
                                        "MORU_STATE_HOME": str(project / "state-home")})
    environment.start()
    case.addCleanup(environment.stop)
    (project / ".gitignore").write_text(".moru/\n__pycache__/\nstate-home/\n")
    (project / "value.txt").write_text("10")
    (project / "tests").mkdir()
    for name, assertion in (("goal", "self.assertLessEqual(value, 6)"),
                            ("regression", "self.assertGreaterEqual(value, 1)")):
        (project / "tests" / f"test_{name}.py").write_text(
            "import json, os, unittest\nfrom pathlib import Path\n"
            "class Check(unittest.TestCase):\n    def test_value(self):\n"
            "        value = int(Path('value.txt').read_text())\n"
            "        output = os.environ.get('MORU_LOOP_MEASUREMENT_PATH')\n"
            "        if output: Path(output).write_text(json.dumps({'value': value}))\n"
            f"        {assertion}\n")
    for arguments in (("init", "-q"), ("add", "."),
                      ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                       "commit", "-qm", "baseline")):
        subprocess.run(["git", "-C", str(project), *arguments], check=True, capture_output=True)
    run_id = "a" * 32
    evidence = project / ".moru" / "runs" / run_id / "preflight.json"
    evidence.parent.mkdir(parents=True)
    route = {"command": "feature", "gates": ["tests", "review hook"], "lifecycle_version": 2}
    intake = {"request": "bounded fixture"}
    evidence.write_text(json.dumps({"project": str(project), "rules": str(project),
        "agent_run_id": run_id, "execution_mode": {"read_only": False}, "route": route,
        "request_intake": intake,
        "execution_snapshot": {"schema_version": 1, "route_fingerprint": route_fingerprint(route),
                               "request_fingerprint": request_fingerprint(intake), "required_docs": []},
        "runtime_session": {"runtime": "codex", "session_id": "loop-fixture"}}))
    run = register_run(project, evidence, route, intake)
    case.assertEqual(run_id, run["run_id"])
    return project, evidence, run_id


def loop_config():
    return {"objective": "value at most six with positive regression", "owned": ["value.txt"],
            "verifiers": ["tests/test_goal.py", "tests/test_regression.py"], "directory": "tests",
            "goal_pattern": "test_goal.py", "regression_pattern": "test_regression.py",
            "max_iterations": 5, "max_seconds": 60, "max_model_calls": 10,
            "metric": {"direction": "min", "min_delta": 1.0}}


class LoopStateTests(unittest.TestCase):
    def setUp(self):
        self.project, self.evidence, self.run_id = loop_fixture(self)
        self.loop = LoopRun(self.project)
        self.config = loop_config()

    def start(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.loop.start(self.config)

    def check(self, value):
        (self.project / "value.txt").write_text(str(value))
        with contextlib.redirect_stdout(io.StringIO()):
            return self.loop.evaluate()

    def test_measured_attempts_keep_improvement_then_prove_goal(self):
        baseline = self.start()
        self.assertEqual(("ready", 10), (baseline["status"], baseline["baseline_value"]))
        self.loop.begin("reduce unnecessary work")
        result = self.check(8)
        self.assertFalse(result["attempt"]["result"]["goal"]["passed"])
        accepted = self.loop.resolve(True)
        self.assertEqual(("ready", 8), (accepted["status"], accepted["baseline_value"]))
        self.loop.begin("remove remaining work")
        self.check(5)
        final = self.loop.resolve(True)
        self.assertEqual(("succeeded", 2, 2), (final["status"], final["iterations"], final["model_calls"]))
        self.assertEqual(["accepted", "accepted"], [row["verdict"] for row in final["history"]])
        self.assertNotIn("candidate", final["history"][0]["result"])
        self.assertEqual("5", (self.project / "value.txt").read_text())

    def test_rejected_attempt_requires_actual_restoration(self):
        self.start()
        self.loop.begin("try a change")
        self.check(11)
        with self.assertRaises(ValueError):
            self.loop.resolve(True)
        with self.assertRaises(ValueError):
            self.loop.resolve(False)
        self.assertEqual("11", (self.project / "value.txt").read_text())
        (self.project / "value.txt").write_text("10")
        rejected = self.loop.resolve(False)
        self.assertEqual(("ready", "rejected"), (rejected["status"], rejected["history"][0]["verdict"]))

    def test_regression_failure_cannot_win_a_metric(self):
        self.start()
        self.loop.begin("break behavior while lowering number")
        self.check(0)
        with self.assertRaisesRegex(ValueError, "regressions failed"):
            self.loop.resolve(True)

    def test_nonmetric_loop_requires_goal_not_only_green_regressions(self):
        self.config["metric"] = None
        self.start()
        self.loop.begin("incomplete fix")
        self.check(8)
        with self.assertRaisesRegex(ValueError, "did not improve"):
            self.loop.resolve(True)
        (self.project / "value.txt").write_text("10")
        self.loop.resolve(False)
        self.loop.begin("complete fix")
        self.check(5)
        self.assertEqual("succeeded", self.loop.resolve(True)["status"])

    def test_changed_candidate_cannot_reuse_a_passing_result(self):
        self.start()
        self.loop.begin("candidate")
        self.check(5)
        (self.project / "value.txt").write_text("4")
        with self.assertRaisesRegex(ValueError, "candidate changed"):
            self.loop.resolve(True)

    def test_gate_prose_cannot_turn_a_failed_goal_into_success(self):
        self.config["metric"] = None
        self.start()
        (self.evidence.parent / "gate-evidence.json").write_text(json.dumps({
            "entries": [{"gate": "tests", "status": "SUCCESS", "source": "execution"}]}))
        self.loop.begin("still wrong")
        observed = self.check(8)
        self.assertFalse(observed["attempt"]["result"]["goal"]["passed"])
        with self.assertRaises(ValueError):
            self.loop.resolve(True)

    def test_iteration_limit_is_terminal_without_claiming_success(self):
        self.config["max_iterations"] = 1
        self.start()
        self.loop.begin("one shot")
        self.check(8)
        final = self.loop.resolve(True)
        self.assertEqual(("exhausted", 1), (final["status"], final["iterations"]))
        with self.assertRaises(ValueError):
            self.loop.start(self.config)

    def test_model_call_reservations_never_exceed_ceiling(self):
        self.config["max_model_calls"] = 2
        self.start()
        self.loop.begin("bounded work")
        self.assertEqual(2, self.loop.reserve(1)["model_calls"])
        refused = self.loop.reserve(1)
        self.assertEqual(("exhausted", 2), (refused["status"], refused["model_calls"]))
        self.assertEqual("10", (self.project / "value.txt").read_text())

    def test_oversized_begin_preserves_remaining_budget(self):
        self.start()
        before = self.loop.binding.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "remaining model-call budget"):
            self.loop.begin("oversized request", 11)
        self.assertEqual(before, self.loop.binding.path.read_bytes())
        self.assertEqual("attempting", self.loop.begin("smaller request", 1)["status"])

    def test_oversized_reservation_preserves_pending_attempt(self):
        self.start()
        self.loop.begin("pending request", 1)
        before = self.loop.binding.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "remaining model-call budget"):
            self.loop.reserve(20)
        self.assertEqual(before, self.loop.binding.path.read_bytes())
        self.assertEqual(2, self.loop.reserve(1)["model_calls"])

    def test_reconciliation_cannot_reopen_an_exhausted_loop(self):
        self.start()
        state = self.loop.begin("recover previously exhausted state", 1)
        state["status"] = "exhausted"
        self.loop.binding.path.write_text(json.dumps(state))
        rejected = self.loop.resolve(False)
        self.assertEqual(("exhausted", 1, 1),
                         (rejected["status"], rejected["iterations"], rejected["model_calls"]))
        with self.assertRaises(ValueError):
            self.loop.begin("terminal state stays closed")

    def test_uncertain_child_probe_preserves_original_check_failure(self):
        self.start()
        self.loop.begin("check with uncertain process ownership")

        def fail(checker, inputs, timeout):
            checker.process_admission(2 ** 30)
            raise RuntimeError("original check failure")

        with patch("agent_loop_candidate.LoopCheck.run", autospec=True, side_effect=fail), \
                patch("agent_loop_binding.os.killpg", side_effect=PermissionError("probe denied")):
            with self.assertRaisesRegex(RuntimeError, "original check failure"):
                self.loop.evaluate()
        state = self.loop.status()
        self.assertEqual("checking", state["status"])
        self.assertEqual([2 ** 30], state["inflight"]["groups"])

    def test_deadline_survives_pause_and_new_controller(self):
        self.start()
        before = self.loop.pause()
        resumed = LoopRun(self.project).resume()
        self.assertEqual(before["deadline"], resumed["deadline"])
        with patch("agent_loop_state.time.time", return_value=before["deadline"] + 1):
            final = self.loop.begin("too late")
        self.assertEqual(("exhausted", 0), (final["status"], final["iterations"]))

    def test_clock_rollback_does_not_extend_budget(self):
        before = self.start()
        with patch("agent_loop_state.time.time", return_value=before["updated_at"] - 1):
            with self.assertRaisesRegex(ValueError, "clock moved backwards"):
                self.loop.begin("clock rollback")

    def test_pause_resume_retains_attempt_and_requires_fresh_check(self):
        self.start()
        attempt = self.loop.begin("resumable attempt")
        self.check(8)
        self.loop.pause()
        resumed = LoopRun(self.project).resume()
        self.assertEqual(attempt["attempt"]["id"], resumed["attempt"]["id"])
        self.assertIsNone(resumed["attempt"]["result"])
        self.assertEqual((1, 1), (resumed["iterations"], resumed["model_calls"]))
        with self.assertRaises(ValueError):
            self.loop.resolve(True)
        self.check(8)
        self.assertEqual("ready", self.loop.resolve(True)["status"])

    def test_successful_baseline_needs_no_attempt_or_model_call(self):
        (self.project / "value.txt").write_text("5")
        final = self.start()
        self.assertEqual(("succeeded", 0, 0), (final["status"], final["iterations"], final["model_calls"]))

    def test_closed_task_is_readable_but_cannot_mutate_loop(self):
        self.start()
        transition_run(self.project, self.evidence, "completed")
        reader = LoopRun(self.project, self.run_id)
        self.assertEqual("ready", reader.status()["status"])
        with self.assertRaises(ValueError):
            reader.begin("closed task")

    def test_scope_drift_does_not_write_sources_or_reset_accepted_state(self):
        before = self.start()
        (self.project / "unrelated.txt").write_text("user work")
        with self.assertRaises(ValueError):
            self.loop.begin("wrong scope")
        self.assertEqual(before, self.loop.status())
        self.assertEqual("user work", (self.project / "unrelated.txt").read_text())

    def test_cancel_preserves_unresolved_edits_and_budget(self):
        self.start()
        self.loop.begin("cancelled experiment")
        (self.project / "value.txt").write_text("7")
        final = self.loop.cancel()
        self.assertEqual(("cancelled", 1, 1), (final["status"], final["iterations"], final["model_calls"]))
        self.assertEqual("7", (self.project / "value.txt").read_text())

    def test_invalid_numeric_contract_cannot_enroll(self):
        for key, value in (("max_iterations", 0), ("max_seconds", True), ("max_model_calls", -1)):
            with self.subTest(key=key):
                config = loop_config()
                config[key] = value
                with self.assertRaises(ValueError):
                    self.loop.start(config)
                self.assertFalse(self.loop.binding.path.exists())

    def test_call_limit_after_accepted_improvement_is_not_success(self):
        self.config["max_model_calls"] = 1
        self.start()
        self.loop.begin("only admitted call")
        self.check(8)
        final = self.loop.resolve(True)
        self.assertEqual(("exhausted", 8), (final["status"], final["baseline_value"]))
        with self.assertRaises(ValueError):
            self.loop.pause()

    def test_interrupted_check_keeps_budget_and_requires_fresh_execution(self):
        self.start()
        begun = self.loop.begin("interrupted attempt")
        with patch("agent_loop_state.LoopCheck.run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.loop.evaluate()
        paused = self.loop.status()
        self.assertEqual(("paused", 1, 1), (paused["status"], paused["iterations"], paused["model_calls"]))
        resumed = self.loop.resume()
        self.assertEqual(begun["attempt"]["id"], resumed["attempt"]["id"])
        self.assertIsNone(resumed["attempt"]["result"])
        self.check(5)
        self.assertEqual("succeeded", self.loop.resolve(True)["status"])

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX supervised check groups")
    def test_dead_check_parent_does_not_hide_a_live_test_child(self):
        self.start()
        state = self.loop.begin("recover child process")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 start_new_session=True)
        try:
            state["status"] = "checking"
            state["inflight"] = {"owner": 2 ** 30, "groups": [child.pid]}
            self.loop.binding.path.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError, "child group is still live"):
                LoopRun(self.project).resume()
            self.assertEqual((1, 1), (self.loop.status()["iterations"], self.loop.status()["model_calls"]))
        finally:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=5)
        resumed = LoopRun(self.project).resume()
        self.assertEqual(("attempting", 1, 1), (resumed["status"], resumed["iterations"], resumed["model_calls"]))
        self.check(5)
        self.assertEqual("succeeded", self.loop.resolve(True)["status"])

    def test_success_cannot_be_relabelled_as_cancellation(self):
        (self.project / "value.txt").write_text("5")
        self.start()
        with self.assertRaises(ValueError):
            self.loop.cancel()
        self.assertEqual("succeeded", self.loop.status()["status"])

    def test_real_task_resume_transfers_owner_without_resetting_loop(self):
        from agent_continuation_checkpoint import write_continuation_checkpoint
        from agent_continuation_resume import resume_last
        from agent_run_interruption import record_turn_boundary
        from agent_run_registry import registered_run
        from agent_runtime_session import bind_resumed_runtime_session

        self.start()
        begun = self.loop.begin("continue after a real task interruption")
        write_continuation_checkpoint(project=self.project, rules=self.project, run_id=self.run_id,
                                      kind="initial", binding_path=self.evidence,
                                      work={"objective": "resume bounded loop"})
        original = self.loop.binding.path.read_bytes()
        record_turn_boundary(self.project, runtime="codex", session_id="loop-fixture", evidence=self.evidence)
        self.assertEqual("interrupted", registered_run(self.project, self.evidence)["state"])
        claimed = resume_last(self.project, run_id=self.run_id, rules=self.project)
        self.assertEqual("ready", claimed["result"])
        bind_resumed_runtime_session(project=self.project, evidence_path=self.evidence,
                                     run_id=self.run_id, resume_generation=claimed["resume_generation"],
                                     runtime="codex", session_id="loop-resumed")
        self.assertEqual(original, self.loop.binding.path.read_bytes())
        with self.assertRaises(ValueError):
            self.loop.reserve(1)
        with patch.dict(os.environ, CODEX_THREAD_ID="loop-resumed"):
            new_owner = LoopRun(self.project)
            reserved = new_owner.reserve(1)
            self.assertEqual((begun["deadline"], begun["attempt"]["id"]),
                             (reserved["deadline"], reserved["attempt"]["id"]))
            self.assertEqual((1, 2), (reserved["iterations"], reserved["model_calls"]))
            (self.project / "value.txt").write_text("5")
            with contextlib.redirect_stdout(io.StringIO()):
                new_owner.evaluate()
            self.assertEqual("succeeded", new_owner.resolve(True)["status"])
