from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_scheduler import _next_attempt, _next_attempt_reference, cancel_task, claim_next, claim_task, checkpoint_task, choose_capacity, enqueue_task, heartbeat_task, recover_stale_tasks, resume_task, retry_task, transition_task
from native_pretool_support import environment, prepare


class AgentSchedulerTests(unittest.TestCase):
    def test_small_work_stays_serial_and_independent_work_is_bounded(self) -> None:
        self.assertEqual(1, choose_capacity(0, 3))
        self.assertEqual(1, choose_capacity(1, 3))
        self.assertEqual(2, choose_capacity(2, 2))
        self.assertEqual(3, choose_capacity(4, 8))

    def test_claims_highest_priority_and_respects_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            low = enqueue_task(project, "run-low", priority=1)
            high = enqueue_task(project, "run-high", priority=5)

            claimed = claim_next(project, capacity=1)
            self.assertEqual(high["task_id"], claimed["task_id"])
            self.assertIsNone(claim_next(project, capacity=1))
            self.assertEqual("completed", transition_task(project, claimed["task_id"], "completed")["state"])
            self.assertEqual(low["task_id"], claim_next(project, capacity=1)["task_id"])

    def test_unknown_task_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                transition_task(Path(directory), "missing", "unknown")

    def test_retry_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            self.assertEqual(task["task_id"], claim_next(project)["task_id"])
            transition_task(project, task["task_id"], "failed")
            retried = retry_task(project, task["task_id"])
            self.assertEqual(2, retried["attempt"])
            self.assertEqual(task["task_id"], claim_next(project)["task_id"])
            transition_task(project, task["task_id"], "failed")
            self.assertIsNone(retry_task(project, task["task_id"]))

    def test_targeted_claim_does_not_replace_retry_with_another_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            retryable = enqueue_task(project, "run-retry", priority=1, max_retries=1)
            other = enqueue_task(project, "run-other", priority=9)
            transition_task(project, retryable["task_id"], "failed")
            retried = retry_task(project, retryable["task_id"])
            self.assertEqual("queued", retried["state"])
            self.assertEqual(retryable["task_id"], claim_task(project, retryable["task_id"], capacity=1)["task_id"])
            self.assertEqual(other["task_id"], claim_next(project, capacity=2)["task_id"])

    def test_recover_stale_tasks_marks_old_active_tasks_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            queued = enqueue_task(project, "run-queued", max_retries=1)
            running = enqueue_task(project, "run-running", max_retries=1)
            claim_task(project, running["task_id"])
            scheduler = project / ".moru" / "scheduler.json"
            payload = json.loads(scheduler.read_text())
            old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            for task in payload["tasks"]:
                task["updated_at"] = old
            scheduler.write_text(json.dumps(payload), encoding="utf-8")

            recovered = recover_stale_tasks(project, stale_after_seconds=60)
            self.assertEqual({queued["task_id"], running["task_id"]}, {task["task_id"] for task in recovered})
            self.assertEqual({"failed"}, {task["state"] for task in recovered})
            self.assertEqual("queued", retry_task(project, queued["task_id"])["state"])

    def test_heartbeat_checkpoint_and_cancel_follow_task_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claimed = claim_next(project)
            heartbeat = heartbeat_task(project, claimed["task_id"])
            self.assertEqual(claimed["task_id"], heartbeat["task_id"])
            checkpoint = checkpoint_task(project, task["task_id"], "result-1")
            self.assertEqual("result-1", checkpoint["partial_result_id"])
            self.assertEqual("cancelled", cancel_task(project, task["task_id"])["state"])

    def test_native_recovery_matches_reference_at_the_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            _, reference = prepare(base)
            native = base / "other"
            moment = datetime(2026, 1, 2, tzinfo=timezone.utc)
            cutoff = moment - timedelta(seconds=60)
            records = [
                {"task_id": task_id, "run_id": "run-1", "state": state, "updated_at": updated.isoformat()}
                for task_id, state, updated in (
                    ("equal", "queued", cutoff),
                    ("queued", "queued", (cutoff - timedelta(microseconds=1)).astimezone(
                        timezone(timedelta(hours=9)))),
                    ("completed", "completed", cutoff - timedelta(days=1)),
                    ("running", "running", cutoff - timedelta(minutes=1)),
                )
            ]
            for project in (reference, native):
                state = project / ".moru"
                state.mkdir(parents=True, exist_ok=True)
                (state / "scheduler.json").write_text(json.dumps({"schema_version": 1, "tasks": records}))
            with patch("agent_scheduler.datetime", wraps=datetime) as clock:
                clock.now.return_value = moment
                with patch.dict(os.environ, {**environment(base), "MORU_LAUNCHER_BACKEND": "python"},
                                clear=True):
                    expected = recover_stale_tasks(reference, stale_after_seconds=60)
                with patch.dict(os.environ, environment(base), clear=True), patch(
                    "agent_scheduler._stale_tasks_reference", side_effect=AssertionError("native declined"),
                ):
                    actual = recover_stale_tasks(native, stale_after_seconds=60)
            self.assertEqual(["queued", "running"], [task["task_id"] for task in actual])
            self.assertEqual(expected, actual)
            self.assertEqual((reference / ".moru/scheduler.json").read_bytes(),
                             (native / ".moru/scheduler.json").read_bytes())

    def test_native_retry_and_resume_reject_stale_or_exhausted_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            _, project = prepare(base)
            task = enqueue_task(project, "run-1", max_retries=2)
            task_id = task["task_id"]
            claim_task(project, task_id)
            transition_task(project, task_id, "failed")
            scheduler = project / ".moru/scheduler.json"
            before = scheduler.read_bytes()
            with patch.dict(os.environ, environment(base), clear=True), patch(
                "agent_scheduler._next_attempt_reference", side_effect=AssertionError("native declined"),
            ):
                self.assertIsNone(retry_task(project, task_id, expected_attempt=0))
                self.assertIsNone(resume_task(project, task_id, expected_attempt=1))
                self.assertEqual(before, scheduler.read_bytes())
                self.assertEqual(2, retry_task(project, task_id, expected_attempt=1)["attempt"])
                claim_task(project, task_id)
                checkpoint_task(project, task_id, "retained-partial")
                transition_task(project, task_id, "failed")
                resumed = resume_task(project, task_id, expected_attempt=2)
                self.assertEqual((3, "retained-partial"), (resumed["attempt"], resumed["partial_result_id"]))
                claim_task(project, task_id)
                transition_task(project, task_id, "failed")
                self.assertIsNone(retry_task(project, task_id, expected_attempt=3))

    def test_native_retry_defers_legacy_string_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            with patch.dict(os.environ, environment(base), clear=True), patch(
                "agent_scheduler._next_attempt_reference", wraps=_next_attempt_reference,
            ) as reference:
                self.assertEqual(2, _next_attempt({"attempt": "1", "max_attempts": "3"}, 1,
                                                  require_partial=False))
            reference.assert_called_once()

    def test_failed_task_with_partial_result_can_resume_with_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claim_task(project, task["task_id"])
            checkpoint_task(project, task["task_id"], "result-1")
            transition_task(project, task["task_id"], "failed")
            resumed = resume_task(project, task["task_id"])
            self.assertEqual("queued", resumed["state"])
            self.assertEqual("result-1", resumed["partial_result_id"])

    def test_enqueue_accepts_external_partial_result_for_dispatch_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = enqueue_task(Path(directory), "run-1", partial_result_id="external-1")
            self.assertEqual("external-1", task["partial_result_id"])



class GuardedTransitionTests(unittest.TestCase):
    def test_expected_state_and_attempt_guard_terminal_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claim_task(project, task["task_id"])
            transition_task(project, task["task_id"], "failed")
            retry_task(project, task["task_id"])

            self.assertIsNone(transition_task(project, task["task_id"], "completed", expected_state="running"))
            claim_task(project, task["task_id"])
            self.assertIsNone(
                transition_task(project, task["task_id"], "completed", expected_state="running", expected_attempt=1)
            )
            completed = transition_task(project, task["task_id"], "completed", expected_state="running", expected_attempt=2)
            self.assertEqual("completed", completed["state"])

    def test_enqueue_records_requested_workers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(3, enqueue_task(Path(directory), "run-1", requested_workers=3)["requested_workers"])

if __name__ == "__main__":
    unittest.main()
