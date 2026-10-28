from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_ipc import read_events
from agent_scheduler import claim_next, claim_task, enqueue_task, heartbeat_task, retry_task, scheduler_path, transition_task
from workflow_dispatch_launch import _claim_scheduler_task, _run_scheduled_worker
from workflow_dispatch import build_dispatch_manifest


class DispatchHeartbeatTests(unittest.TestCase):
    def test_manifest_defaults_heartbeat_to_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_dispatch_manifest(
                "task",
                "Inspect the scheduler",
                Path(directory),
                work_kind="analysis",
                request_classified=True,
                classification_evidence="clear-scoped analysis blockers resolved",
                request_classification={
                    "clarity": "clear-scoped",
                    "question_drill": False,
                    "recommended_route": "task",
                },
                route={"required_docs": ["AGENTS.md"], "gates": []},
            )
            self.assertEqual(0, manifest["heartbeat_interval_seconds"])

    def test_default_dispatch_emits_no_heartbeat_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1")
            claim_next(project)
            self.assertEqual(0, _run_scheduled_worker([], lambda _argv: 0, project, task))
            self.assertEqual([], read_events(project, event_type="worker.heartbeat"))
            self.assertEqual([], read_events(project, event_type="worker.result"))

    def test_opt_in_dispatch_emits_heartbeat_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1")
            claim_next(project)

            def runner(_argv: list[str]) -> int:
                time.sleep(0.08)
                return 0

            self.assertEqual(
                0,
                _run_scheduled_worker(
                    [], runner, project, task, heartbeat_interval_seconds=0.02
                ),
            )
            self.assertGreaterEqual(len(read_events(project, event_type="worker.heartbeat")), 1)
            self.assertEqual(1, len(read_events(project, event_type="worker.result")))



class DispatchSchedulingTests(unittest.TestCase):
    def _states(self, project: Path) -> dict[str, str]:
        payload = json.loads(scheduler_path(project).read_text())
        return {task["task_id"]: task["state"] for task in payload["tasks"]}

    def test_claim_never_takes_another_queued_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            older = enqueue_task(project, "run-old", priority=5)
            prepared = {"preflight_evidence": str(project / ".moru" / "preflight.json")}
            claim_task(project, enqueue_task(project, "run-busy")["task_id"])

            with self.assertRaisesRegex(RuntimeError, "worker was not started"):
                _claim_scheduler_task({"priority": 0}, prepared, project)
            states = self._states(project)
            self.assertEqual("queued", states[older["task_id"]])
            self.assertEqual(1, list(states.values()).count("cancelled"))

            transition_task(project, next(key for key, value in states.items() if value == "running"), "completed")
            claimed = _claim_scheduler_task({"priority": 0}, prepared, project)
            self.assertEqual("running", self._states(project)[claimed["task_id"]])
            self.assertEqual("queued", self._states(project)[older["task_id"]])

    def test_lease_is_renewed_without_opt_in_heartbeat_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1")
            claim_task(project, task["task_id"])
            renewals: list[str] = []

            def runner(_argv: list[str]) -> int:
                time.sleep(0.08)
                return 0

            with patch("workflow_dispatch_launch.LEASE_RENEWAL_SECONDS", 0.02), patch(
                "workflow_dispatch_launch.heartbeat_task", side_effect=lambda p, t, **_kwargs: renewals.append(t) or {"task_id": t}
            ):
                self.assertEqual(0, _run_scheduled_worker([], runner, project, task))
            self.assertGreaterEqual(len(renewals), 1)
            self.assertEqual([], read_events(project, event_type="worker.heartbeat"))

    def test_finished_worker_does_not_overwrite_a_recovered_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claim_task(project, task["task_id"])

            def runner(_argv: list[str]) -> int:
                transition_task(project, task["task_id"], "failed")
                retry_task(project, task["task_id"])
                return 0

            self.assertEqual(0, _run_scheduled_worker([], runner, project, task))
            self.assertEqual("queued", self._states(project)[task["task_id"]])

    def test_retry_that_cannot_be_claimed_ends_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claim_task(project, task["task_id"])
            other = enqueue_task(project, "run-other")

            def runner(_argv: list[str]) -> int:
                claim_task(project, other["task_id"], capacity=2)
                return 1

            self.assertEqual(1, _run_scheduled_worker([], runner, project, task))
            self.assertEqual("failed", self._states(project)[task["task_id"]])

    def test_superseded_attempt_neither_renews_lease_nor_reports_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task = enqueue_task(project, "run-1", max_retries=1)
            claim_task(project, task["task_id"])

            def runner(_argv: list[str]) -> int:
                transition_task(project, task["task_id"], "failed")
                retry_task(project, task["task_id"])
                claim_task(project, task["task_id"])
                self.assertIsNone(heartbeat_task(project, task["task_id"], expected_attempt=1))
                return 0

            self.assertEqual(
                0, _run_scheduled_worker([], runner, project, task, heartbeat_interval_seconds=0.01)
            )
            self.assertEqual("running", self._states(project)[task["task_id"]])
            self.assertEqual([], read_events(project, event_type="worker.result"))

if __name__ == "__main__":
    unittest.main()
