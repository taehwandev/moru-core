"""A run its own session replaced from another checkout has nothing to finish.

Observed live: a session started a run in the main checkout, moved its work to
a linked worktree, and the next start there cancelled the first run with
``superseded_by``. A later finish in the main checkout evaluated that run's
empty gate ledger -- or, before that, another task's months-old legacy
preflight -- and demanded a retrospective repair for work done elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

RUN_ID = "0123456789abcdef0123456789abcdef"


def _load_hook_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "agent-hook.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load agent-hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_hook_script("agent_hook_for_test_finish_superseded_run")


class FinishSupersededRunTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.evidence = self.project / ".moru" / "runs" / RUN_ID / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.evidence.write_text(json.dumps({"agent_run_id": RUN_ID}), encoding="utf-8")
        self.args = Namespace(
            project=self.project, rules=self.project, evidence=self.evidence, output=None,
            repair_cycle=0, allow_vibeguard_review=None, hook="finish",
        )

    def _finish(self, run: dict) -> tuple[bool, list[str], bool]:
        seen: dict = {}

        def capture(name, success, details, output, payload, repair_cycle, invocation_error=False, **_):
            seen.update(success=success, details=details, invocation_error=invocation_error)
            return 0 if success else 1

        def checked(*_args, **_kwargs):
            raise AssertionError("the finish check must not run for a replaced run")

        with (
            patch.object(agent_hook, "registered_run", return_value=run),
            patch.object(agent_hook, "finish_with_result", side_effect=capture),
            patch.object(agent_hook, "run_script_main", side_effect=checked),
        ):
            agent_hook.finish_hook(self.args)
        return seen["success"], seen["details"], seen["invocation_error"]

    def test_a_replaced_run_is_named_without_evaluating_its_gates(self) -> None:
        run = {"run_id": RUN_ID, "state": "cancelled", "superseded_by": "f" * 32}
        success, details, invocation_error = self._finish(run)
        self.assertFalse(success, "a replaced run is not reported as finished")
        self.assertTrue(invocation_error, "no gate ran, so there is nothing to repair")
        self.assertIn("f" * 32, details[0])
        self.assertIn("nothing left to finish", details[1])

    def test_other_runs_still_reach_the_finish_check(self) -> None:
        for run in (
            {"run_id": RUN_ID, "state": "running"},
            {"run_id": RUN_ID, "state": "cancelled"},
        ):
            with self.subTest(run=run):
                with patch.object(agent_hook, "registered_run", return_value=run):
                    self.assertIsNone(agent_hook._superseded_run(self.args))


if __name__ == "__main__":
    unittest.main()
