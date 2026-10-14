from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_scheduler import cancel_task, claim_next, claim_task, checkpoint_task, choose_capacity, enqueue_task, heartbeat_task, recover_stale_tasks, resume_task, retry_task, transition_task


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


if __name__ == "__main__":
    unittest.main()
