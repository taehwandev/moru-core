"""Fresh-process evidence that ordinary mailbox paths need no execution policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from startup_import_guard import guarded_command
from startup_path_support import PROJECT, environment, prepare


class MailboxStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mailbox-startup-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project, _ = prepare(self.base)

    def guarded(self, script, args, blocked):
        return subprocess.run(guarded_command(sys.executable, script, args, blocked),
            cwd=self.project, env=environment(self.base), stdin=subprocess.DEVNULL,
            capture_output=True, timeout=15)

    def test_mailbox_help_avoids_mailbox_implementation(self):
        done = self.guarded(PROJECT / "scripts/agent-mailbox.py", ["--help"], ["agent_mailbox"])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn(b"receive", done.stdout)

    def test_empty_status_avoids_execution_capsule(self):
        done = self.guarded(PROJECT / "scripts/agent-mailbox.py", ["status", "--project",
            str(self.project), "--runtime", "codex", "--json"], ["agent_execution_capsule"])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual({"runtime": "codex", "pending": 0, "expired": 0, "acked": 0, "rejected": 0},
                         json.loads(done.stdout))

    def test_new_prompt_pauses_armed_task_without_loading_binding_checks(self):
        script = self.base / "pause.py"
        script.write_text("\n".join([
            "import json,sys", f"sys.path.insert(0, {str(PROJECT / 'scripts')!r})",
            "from pathlib import Path", "from agent_mailbox_task import TaskContinuation",
            "identity={'runtime':'codex','session_id':'synthetic'}",
            "task=TaskContinuation(Path(sys.argv[1]),identity)",
            "task.root.mkdir(parents=True,exist_ok=True)",
            "record=task.path('c'*32)",
            "record.write_text(json.dumps({'identity':identity,'status':'armed'}))",
            "task.budget.write_text('{}')", "task.new_prompt()",
            "print(json.dumps({'status':json.loads(record.read_text())['status'],'budget':task.budget.exists()}))",
        ]))
        done = self.guarded(script, [str(self.project)], ["agent_mailbox_task_binding"])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual({"status": "paused", "budget": False}, json.loads(done.stdout))

    def test_repository_identity_is_read_once_per_prompt_and_fresh_next_prompt(self):
        from contextlib import redirect_stdout
        import io
        from agent_mailbox_hook import deliver
        real_run = subprocess.run
        with patch.dict(os.environ, environment(self.base), clear=True), \
                patch("agent_project_memory.subprocess.run", wraps=real_run) as run, \
                redirect_stdout(io.StringIO()):
            payload = {"cwd": str(self.project), "session_id": "synthetic-count"}
            self.assertEqual(0, deliver(payload, "codex"))
            first = sum(call.args[0][-3:] == ["rev-parse", "--path-format=absolute", "--git-common-dir"]
                        for call in run.call_args_list)
            self.assertEqual(1, first)
            self.assertEqual(0, deliver(payload, "codex"))
            total = sum(call.args[0][-3:] == ["rev-parse", "--path-format=absolute", "--git-common-dir"]
                        for call in run.call_args_list)
            self.assertEqual(2, total)


if __name__ == "__main__":
    unittest.main()
