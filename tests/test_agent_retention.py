from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_retention import _plan_prune, _plan_prune_reference, prune_runtime_state
from agent_run_registry import register_run, transition_run
from native_pretool_support import environment, prepare


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


    def test_native_retention_plan_preserves_protected_records_and_append_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            cutoff = datetime.fromisoformat("2026-01-01T00:00:00.123456+00:00")
            before = "2026-01-01T01:00:00.123455+01:00"
            equal = "2026-01-01T01:00:00.123456+01:00"
            later = "2026-02-01T00:00:00"
            active = {"run_id": "active", "state": "running"}
            held = {"run_id": "held", "state": "completed", "updated_at": before}
            terminal = frozenset({"completed"})
            cases = {
                "runs": (
                    [active, held, {"run_id": "old", "state": "completed", "updated_at": before},
                     {"run_id": "newer-time", "state": "completed", "updated_at": later},
                     None, {"run_id": "virtually-settled", "state": "failed", "queued_at": equal}],
                    [0, 1, 5],
                ),
                "tasks": (
                    [{"state": "running"}, {"state": "completed", "queued_at": before},
                     {"state": "completed", "queued_at": equal}],
                    [0, 2],
                ),
                "events": (
                    [{"created_at": later}, {"created_at": before}, {"created_at": equal}],
                    [2],
                ),
            }
            for key, (records, indexes) in cases.items():
                with self.subTest(key=key):
                    args = ({key: records}, key, cutoff, 1, terminal,
                            frozenset({"held", "virtually-settled"}), frozenset({"held"}))
                    with patch.dict(os.environ, {**environment(base), "MORU_LAUNCHER_BACKEND": "python"},
                                    clear=True):
                        reference = _plan_prune(*args)
                    with patch.dict(os.environ, environment(base), clear=True), patch(
                        "agent_retention._plan_prune_reference",
                        side_effect=AssertionError("native retention declined"),
                    ):
                        native = _plan_prune(*args)
                    self.assertEqual((len(records) - len(indexes), [records[i] for i in indexes]), native)
                    self.assertEqual(reference, native)
                    for kept, index in zip(native[1], indexes):
                        self.assertIs(kept, records[index])

    def test_native_retention_defers_malformed_terminal_time_to_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            event = {"created_at": "malformed"}
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            with patch.dict(os.environ, environment(base), clear=True), patch(
                "agent_retention._plan_prune_reference", wraps=_plan_prune_reference,
            ) as reference:
                result = _plan_prune({"events": [event]}, "events", cutoff, 1,
                                     frozenset(), frozenset(), frozenset())
            reference.assert_called_once()
            self.assertEqual((0, [event]), result)


if __name__ == "__main__":
    unittest.main()
