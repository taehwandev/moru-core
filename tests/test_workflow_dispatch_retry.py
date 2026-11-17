"""Worker failures must recover at the right boundary, without blind replay."""

from __future__ import annotations

import sys
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_scheduler import cancel_task, claim_task, enqueue_task, retry_task, resume_task, scheduler_path, transition_task
from workflow_dispatch_launch import _claim_scheduler_task, _run_scheduled_worker, _run_spooled_worker, execute_dispatch_manifest
from workflow_dispatch_handoff import worker_output_paths, build_worker_result_packet
from workflow_dispatch_retry import WorkerOutcome, recovery_message


class DispatchRetryTests(unittest.TestCase):
    def test_spawn_error_keeps_public_exception_and_actionable_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            prepared = {"preflight_evidence": str(project / "preflight.json"), "execution_capsule": {"reusable": True}}
            manifest = {"execution_mode": "child", "handoff_state": {}, "work_profile": {},
                        "command": "task", "request": "review", "work_kind": "analysis",
                        "project": str(project), "sandbox_mode": "read-only"}
            with patch("workflow_dispatch_launch.prepare_launch_handoff", return_value=prepared):
                with self.assertRaisesRegex(RuntimeError, "Unable to start the delegated Codex worker"):
                    execute_dispatch_manifest(
                        manifest, runner=None, execution_capsule_state=lambda *a, **k: {},
                        isolated_worker_evidence=lambda *a, **k: project,
                        codex_argv=lambda *a, **k: [str(project / "missing-worker")],
                        build_handoff_prompt=lambda *a, **k: "review")
            self.assertEqual("failed", self.latest(project)["state"])
            packet = json.loads(Path(worker_output_paths(prepared)["result_path"]).read_text())
            self.assertIn("installed tool path", packet["next_action"])

    def test_unknown_failure_preserves_the_workers_specific_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = {"preflight_evidence": str(Path(directory) / "preflight.json")}
            raw = json.dumps({"status": "blocked", "next_action": "ask user to choose X"})
            for action in ("inspect_failure_and_correct_owner", "retry_transient"):
                packet = build_worker_result_packet(prepared, returncode=1, raw_output=raw,
                                                    recovery_action=recovery_message(action))
                self.assertEqual("ask user to choose X", packet["next_action"])
            packet = build_worker_result_packet(prepared, returncode=1, raw_output=raw,
                                                recovery_action=recovery_message("check_existing_auth"))
            self.assertIn("existing host authentication", packet["next_action"])

    def test_legacy_null_and_explicit_retry_budgets_are_preserved(self):
        for value, attempts in ((None, 1), (0, 1), ("", 1), (5, 6)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                task = _claim_scheduler_task({"max_retries": value}, {"preflight_evidence": str(project / "preflight.json")}, project)
                self.assertEqual(attempts, task["max_attempts"])

    def task(self, project, *, retries=2, partial=None):
        task = enqueue_task(project, "run", max_retries=retries, partial_result_id=partial)
        claim_task(project, task["task_id"])
        return task

    def latest(self, project):
        return json.loads(scheduler_path(project).read_text())["tasks"][-1]

    def test_default_dispatch_reserves_two_recovery_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = _claim_scheduler_task({}, {"preflight_evidence": str(project / "preflight.json")}, project)
            self.assertEqual(3, task["max_attempts"])

    def test_invalid_invocation_is_not_repeated_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run", max_retries=2)
            claim_task(project, task["task_id"])
            calls = []
            self.assertEqual(2, _run_scheduled_worker([], lambda argv: calls.append(argv) or 2, project, task))
            self.assertEqual(1, len(calls))

    def test_transient_failure_recovers_with_backoff_and_bounded_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = self.task(project)
            results = iter([WorkerOutcome(1, "UNAVAILABLE", True), WorkerOutcome(1, "HTTP_429", True, 4), 0])
            output, diagnostic = io.StringIO(), io.StringIO()
            with patch("workflow_dispatch_launch.time.sleep") as wait, contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostic):
                self.assertEqual(0, _run_scheduled_worker([], lambda _: next(results), project, task))
            self.assertEqual("", output.getvalue())
            self.assertIn("retry=yes", diagnostic.getvalue())
            self.assertEqual([1, 4], [call.args[0] for call in wait.call_args_list])
            self.assertEqual("completed", self.latest(project)["state"])
            self.assertEqual(3, self.latest(project)["attempt"])

    def test_exhaustion_never_restarts_a_fourth_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = self.task(project)
            calls = []
            with patch("workflow_dispatch_launch.time.sleep") as wait:
                result = _run_scheduled_worker([], lambda argv: calls.append(argv) or WorkerOutcome(1, "UNAVAILABLE", True), project, task)
            self.assertEqual(1, result)
            self.assertEqual(3, len(calls))
            self.assertEqual(2, wait.call_count)

    def test_explicit_zero_retries_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = _claim_scheduler_task({"max_retries": 0}, {"preflight_evidence": str(project / "preflight.json")}, project)
            with patch("workflow_dispatch_launch.time.sleep") as wait:
                self.assertEqual(1, _run_scheduled_worker([], lambda _: WorkerOutcome(1, "UNAVAILABLE", True), project, task))
            wait.assert_not_called()
            self.assertEqual(1, self.latest(project)["attempt"])

    def test_cancel_during_backoff_does_not_revive_the_task(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = self.task(project)
            calls = []
            with patch("workflow_dispatch_launch.time.sleep", side_effect=lambda _: cancel_task(project, task["task_id"])):
                _run_scheduled_worker([], lambda argv: calls.append(argv) or WorkerOutcome(1, "UNAVAILABLE", True), project, task)
            self.assertEqual(1, len(calls))
            self.assertEqual("cancelled", self.latest(project)["state"])

    def test_retry_claims_cannot_take_a_newer_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = self.task(project, partial="partial")
            transition_task(project, task["task_id"], "failed")
            self.assertIsNone(retry_task(project, task["task_id"], expected_attempt=2))
            self.assertIsNone(resume_task(project, task["task_id"], expected_attempt=2))
            retry_task(project, task["task_id"], expected_attempt=1)
            self.assertIsNone(claim_task(project, task["task_id"], expected_attempt=1))
            self.assertEqual("queued", self.latest(project)["state"])

    def test_partial_result_and_attempt_context_survive_transient_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = self.task(project, partial="partial-1")
            context = {"task": task}
            seen = []
            def runner(_):
                seen.append((context["task"]["attempt"], context["task"]["partial_result_id"]))
                return WorkerOutcome(1, "UNAVAILABLE", True) if len(seen) == 1 else 0
            with patch("workflow_dispatch_launch.time.sleep"):
                self.assertEqual(0, _run_scheduled_worker([], runner, project, task, task_context=context))
            self.assertEqual([(1, "partial-1"), (2, "partial-1")], seen)

    def run_process_scenario(self, error, *, tool_started=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name)
        prepared = {"preflight_evidence": str(project / "preflight.json"), "execution_capsule": {"reusable": True}}
        paths = worker_output_paths(prepared)
        marker = project / "calls"
        events = ([{"type": "item.started", "item": {"type": "command_execution"}}] if tool_started else [])
        events.append({"type": "turn.failed", "error": error})
        program = (
            "import json,sys; from pathlib import Path; p=Path(sys.argv[1]); "
            "n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); "
            "[print(json.dumps(e)) for e in json.loads(sys.argv[3])] if n==1 else "
            "Path(sys.argv[2]).write_text(json.dumps({'status':'ok','summary':'recovered'})); "
            "sys.exit(1 if n==1 else 0)"
        )
        task = _claim_scheduler_task({}, prepared, project)
        context = {"task": task}
        with patch("workflow_dispatch_launch.time.sleep") as wait:
            result = _run_scheduled_worker(
                [sys.executable, "-c", program, str(marker), paths["last_message_path"], json.dumps(events)],
                lambda argv: _run_spooled_worker(argv, prepared, context["task"], "", project=project),
                project, task, task_context=context)
        packet = json.loads(Path(paths["result_path"]).read_text())
        return result, int(marker.read_text()), packet, wait.call_count

    def test_real_pre_tool_transport_failure_recovers_on_second_process(self):
        result, calls, packet, waits = self.run_process_scenario({"status_code": 503})
        self.assertEqual((0, 2, 1), (result, calls, waits))
        self.assertEqual("ok", packet["status"])

    def test_real_auth_failure_keeps_actionable_recovery_in_the_packet(self):
        result, calls, packet, waits = self.run_process_scenario({"status_code": 401})
        self.assertEqual((1, 1, 0), (result, calls, waits))
        self.assertIn("existing host authentication", packet["next_action"])

    def test_real_tool_started_failure_cannot_duplicate_external_work(self):
        result, calls, packet, waits = self.run_process_scenario({"status_code": 503}, tool_started=True)
        self.assertEqual((1, 1, 0), (result, calls, waits))
        self.assertIn("reconcile external effects", packet["next_action"])


if __name__ == "__main__":
    unittest.main()
