from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_ipc import emit_event
from agent_run_registry import register_run
from agent_scheduler import claim_next, enqueue_task


def _register_worker(project_name: str, index: int, results) -> None:
    project = Path(project_name)
    run = register_run(project, project / ".moru" / f"preflight-{index}.json", {"command": "task"}, {})
    results.put(run["run_id"])


def _event_worker(project_name: str, index: int, results) -> None:
    event = emit_event(Path(project_name), "worker.started", run_id=f"run-{index}", state="running")
    results.put(event["event_id"])


def _claim_worker(project_name: str, results) -> None:
    task = claim_next(Path(project_name), capacity=1)
    results.put(task["task_id"] if task else None)


def _start_processes(ctx, target, args_list):
    processes = [ctx.Process(target=target, args=args) for args in args_list]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        if process.exitcode != 0:
            raise AssertionError(f"worker exited with {process.exitcode}")
    return processes


class AgentConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ctx = multiprocessing.get_context("fork")

    def test_parallel_run_registration_preserves_all_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = self.ctx.Queue()
            args = [(directory, index, queue) for index in range(12)]
            _start_processes(self.ctx, _register_worker, args)
            run_ids = [queue.get(timeout=2) for _ in args]
            payload = json.loads((Path(directory) / ".moru" / "run-registry.json").read_text())
            self.assertEqual(12, len(run_ids))
            self.assertEqual(12, len(payload["runs"]))
            self.assertEqual(12, len({run["run_id"] for run in payload["runs"]}))

    def test_parallel_event_emission_preserves_all_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = self.ctx.Queue()
            args = [(directory, index, queue) for index in range(12)]
            _start_processes(self.ctx, _event_worker, args)
            event_ids = [queue.get(timeout=2) for _ in args]
            payload = json.loads((Path(directory) / ".moru" / "events.json").read_text())
            self.assertEqual(12, len(event_ids))
            self.assertEqual(12, len(payload["events"]))
            self.assertEqual(12, len({event["event_id"] for event in payload["events"]}))

    def test_parallel_claim_respects_capacity_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for index in range(8):
                enqueue_task(project, f"run-{index}")
            queue = self.ctx.Queue()
            args = [(directory, queue) for _ in range(8)]
            _start_processes(self.ctx, _claim_worker, args)
            claims = [queue.get(timeout=2) for _ in args]
            self.assertEqual(1, len([task_id for task_id in claims if task_id]))


if __name__ == "__main__":
    unittest.main()
