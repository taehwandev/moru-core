from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_retention import prune_runtime_state
from agent_run_registry import register_run, transition_run


class AgentRetentionTests(unittest.TestCase):
    def test_prunes_old_terminal_records_and_keeps_active_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            evidence = project / "preflight.json"
            run = register_run(project, evidence, {"command": "task"}, {})
            transition_run(project, evidence, "completed")
            registry = project / ".moru" / "run-registry.json"
            payload = json.loads(registry.read_text())
            payload["runs"][0]["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            registry.write_text(json.dumps(payload), encoding="utf-8")
            active = register_run(project, project / "new-preflight.json", {"command": "task"}, {})

            removed = prune_runtime_state(project, retention_seconds=60)
            remaining = json.loads(registry.read_text())["runs"]
            self.assertEqual(1, removed["runs"])
            self.assertEqual([active["run_id"]], [item["run_id"] for item in remaining])

    def test_max_records_never_discards_active_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runs = [register_run(project, project / f"preflight-{index}.json", {"command": "task"}, {}) for index in range(3)]

            removed = prune_runtime_state(project, retention_seconds=60, max_records=1)
            registry = project / ".moru" / "run-registry.json"
            remaining = json.loads(registry.read_text())["runs"]
            self.assertEqual(0, removed["runs"])
            self.assertEqual({run["run_id"] for run in runs}, {item["run_id"] for item in remaining})


if __name__ == "__main__":
    unittest.main()
