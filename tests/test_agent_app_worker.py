"""A lead can start and stop visible Moru app worker sessions through moru-ade."""

from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_app_worker as worker  # noqa: E402

STUB = """#!/bin/sh
echo "$@" >> "$LOG"
if [ "$1" = "task" ] && [ "$2" = "run" ]; then cat > "$LOG.brief"; fi
case "$1 $2" in
  "open "*) echo '{"resolved":{"projectId":"proj-1"}}' ;;
  "task create") echo '{"resolved":{"taskId":"task-1"}}' ;;
  "task run") echo '{"resolved":{"runId":"run-1"}}' ;;
  "task stop-run") [ "$STOP_FAIL" = "1" ] && { echo "no such run" >&2; exit 4; }; echo '{}' ;;
esac
"""


class AppWorkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.binary = self.root / "moru-ade"
        self.binary.write_text(STUB)
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.log = self.root / "calls.log"
        self.project = self.root / "repo"
        self.project.mkdir()
        self.env = {"MORU_ADE_BIN": str(self.binary), "LOG": str(self.log)}

    def run_cli(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env), patch("sys.stdin", io.StringIO(stdin)), \
                redirect_stdout(out), redirect_stderr(err):
            code = worker.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_start_opens_a_visible_session_with_the_brief_and_returns_ids_to_stop_it(self):
        code, out, _ = self.run_cli(["start", "--project", str(self.project), "--runtime", "codex",
                                     "--brief-file", "-"], stdin="Implement the cart slice only.")
        self.assertEqual(0, code)
        self.assertEqual({"projectId": "proj-1", "taskId": "task-1", "runId": "run-1", "runtime": "codex"},
                         json.loads(out))
        calls = self.log.read_text().splitlines()
        self.assertEqual(f"open {self.project}", calls[0])
        self.assertEqual("task run --project proj-1 --task task-1 --runtime codex --prompt-file - --submit", calls[2])
        self.assertEqual("Implement the cart slice only.", Path(f"{self.log}.brief").read_text())

        code, out, _ = self.run_cli(["stop", "--project-id", "proj-1", "--task-id", "task-1", "--run-id", "run-1"])
        self.assertEqual(0, code)
        self.assertEqual("task stop-run --project proj-1 --task task-1 --run run-1",
                         self.log.read_text().splitlines()[-1])

    def test_stop_failure_is_reported_not_hidden(self):
        self.env["STOP_FAIL"] = "1"
        code, _, err = self.run_cli(["stop", "--project-id", "proj-1", "--task-id", "task-1", "--run-id", "run-1"])
        self.assertEqual(1, code)
        self.assertIn("exit 4", err)

    def test_unavailable_app_falls_back_to_the_runtime_worker(self):
        self.env["MORU_ADE_BIN"] = str(self.root / "missing")
        with patch.object(worker, "APP_HELPER", self.root / "also-missing"):
            code, _, err = self.run_cli(["available"])
        self.assertEqual(3, code)
        self.assertIn("use the runtime's own worker", err)

    def test_bad_input_starts_nothing(self):
        code, _, _ = self.run_cli(["start", "--project", str(self.project), "--brief-file", "-"], stdin="   ")
        self.assertEqual(1, code)
        code, _, _ = self.run_cli(["stop", "--project-id", "proj 1;rm", "--task-id", "t", "--run-id", "r"])
        self.assertEqual(1, code)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
