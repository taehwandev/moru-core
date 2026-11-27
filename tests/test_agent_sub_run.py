"""A project lead requests headless sub runs and reads its inbox through files Moru Control owns."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_sub_run as sub  # noqa: E402


class SubRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()
        self.hq = self.project / ".moru" / "hq"

    def control_accepts(self, run_id="hqrun-1", refuse=None):
        """Stand in for Moru Control: accept the first request it sees."""
        def worker():
            folder = self.hq / "sub-requests"
            for _ in range(200):
                requests = [p for p in folder.glob("subreq-*.json")
                            if not p.name.endswith((".processed.json", ".failed.json"))] if folder.is_dir() else []
                if requests:
                    req = requests[0]
                    stem = req.name[:-len(".json")]
                    if refuse:
                        (folder / f"{stem}.failed.json").write_text(json.dumps({"error": refuse}))
                    else:
                        (folder / f"{stem}.processed.json").write_text(json.dumps({"runId": run_id}))
                    return
                time.sleep(0.02)
        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(thread.join)

    def test_request_carries_runtime_parent_and_lead_task_and_returns_the_run(self):
        (self.hq).mkdir(parents=True)
        (self.hq / "lead.json").write_text(json.dumps({"schema": 1, "sessionId": "lead-sess", "taskId": "task-9"}))
        self.control_accepts()
        result = sub.request_sub_run(self.project, "codex", "Fix the cart slice.",
                                     environ={"MORU_RUN_ID": "run-7"}, wait_seconds=3, poll=0.02)
        self.assertEqual({"runId": "hqrun-1", "state": "accepted"}, {k: result[k] for k in ("runId", "state")})
        request = json.loads((self.hq / "sub-requests" / f"{result['reqId']}.json").read_text())
        self.assertEqual("codex", request["runtime"])
        self.assertEqual("lead-sess", request["parentSessionId"])  # falls back to lead.json
        self.assertEqual("run-7", request["parentRunId"])
        self.assertEqual("task-9", request["moruTaskId"])
        mode = (self.hq / "sub-requests" / f"{result['reqId']}.json").stat().st_mode & 0o777
        self.assertEqual(0o600, mode)

    def test_session_env_wins_over_lead_file_and_refusal_is_reported(self):
        self.control_accepts(refuse="project cap reached")
        with self.assertRaisesRegex(RuntimeError, "project cap reached"):
            sub.request_sub_run(self.project, "agy", "x", environ={"MORU_SESSION_ID": "sess-a"}, wait_seconds=3, poll=0.02)
        request = next(p for p in (self.hq / "sub-requests").glob("subreq-*.json")
                       if not p.name.endswith(".failed.json"))
        self.assertEqual("sess-a", json.loads(request.read_text())["parentSessionId"])

    def test_unpicked_request_is_pending_not_an_error(self):
        result = sub.request_sub_run(self.project, "claude", "x", environ={}, wait_seconds=0.1, poll=0.02)
        self.assertEqual("pending", result["state"])
        self.assertEqual("pending", sub.request_status(self.project, result["reqId"])["state"])

    def test_bad_input_writes_nothing(self):
        for runtime, brief in (("gpt", "x"), ("claude", "   "), ("claude", "x" * 20001)):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                sub.request_sub_run(self.project, runtime, brief, environ={}, wait_seconds=0)
        self.assertFalse((self.hq / "sub-requests").exists())

    def test_status_and_stop_use_the_run_files(self):
        run = self.hq / "runs" / "hqrun-2"
        run.mkdir(parents=True)
        (run / "status.json").write_text(json.dumps({"runId": "hqrun-2", "state": "running", "origin": "lead_sub",
                                                     "permissionBypass": True, "lastStep": "Edit a.py"}))
        self.assertEqual("running", sub.run_status(self.project, "hqrun-2")["state"])
        self.assertTrue(sub.run_status(self.project, "hqrun-2")["permissionBypass"])
        sub.stop_run(self.project, "hqrun-2")
        self.assertEqual("stop", json.loads((run / "control.json").read_text())["action"])
        with self.assertRaises(ValueError):
            sub.stop_run(self.project, "../hqrun-2")
        with self.assertRaises(ValueError):
            sub.stop_run(self.project, "hqrun-missing")

    def test_inbox_lists_open_items_and_done_hides_them(self):
        inbox = self.hq / "lead-inbox"
        inbox.mkdir(parents=True)
        for item in ("leadreq-a", "leadreq-b"):
            (inbox / f"{item}.json").write_text(json.dumps({"id": item, "title": item, "request": "do it"}))
        (inbox / "leadreq-b.done.json").write_text("{}")
        self.assertEqual(["leadreq-a"], [i["id"] for i in sub.open_inbox(self.project)])
        sub.mark_inbox_done(self.project, "leadreq-a")
        self.assertEqual([], sub.open_inbox(self.project))
        with self.assertRaises(ValueError):
            sub.mark_inbox_done(self.project, "leadreq-zzz")

    def test_cli_start_reads_the_brief_from_stdin(self):
        self.control_accepts(run_id="hqrun-cli")
        out = io.StringIO()
        with patch("sys.stdin", io.StringIO("brief text")), redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = sub.main(["--project", str(self.project), "start", "--runtime", "claude", "--brief-file", "-",
                             "--wait", "3"])
        self.assertEqual(0, code)
        self.assertEqual("hqrun-cli", json.loads(out.getvalue())["runId"])


if __name__ == "__main__":
    unittest.main()
