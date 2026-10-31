"""Fresh-process import avoidance and strict volatile-field comparisons."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from startup_import_guard import guarded_command
from runtime_snapshot_normalize import normalize_output
from startup_path_support import PROJECT, environment, prepare


class StartupPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="startup-paths-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project, self.active = prepare(self.base)

    def guarded(self, script, args, blocked):
        return subprocess.run(guarded_command(sys.executable, PROJECT / "scripts" / script, args, blocked),
            env=environment(self.base), cwd=self.project, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)

    def test_status_help_does_not_import_status_or_validation_implementation(self):
        done = self.guarded("agent-os-status.py", ["--help"], ["agent_observability", "agent_os_api"])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn(b"--efficiency-trends", done.stdout)

    def test_basic_status_does_not_load_trend_libraries(self):
        done = self.guarded("agent-os-status.py", ["--project", str(self.project), "--validate"],
                            ["sqlite3", "statistics"])
        self.assertEqual(0, done.returncode, done.stderr)
        value = json.loads(done.stdout)
        self.assertTrue(value["valid"])
        self.assertEqual(1, value["snapshot"]["active_runs"])
        self.assertEqual({"queued": 1, "done": 1}, value["snapshot"]["task_counts"])
        normalize_output(done.stdout, "validated_status")

    def test_next_help_and_no_active_run_do_not_load_gate_or_review_stack(self):
        for args in (["--help"], ["--project", str(self.project), "--format", "json"]):
            done = self.guarded("agent_next_action.py", args, ["agent_gate_evidence", "agent_review_hook"])
            self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("no_active_run", json.loads(done.stdout)["status"])

    def test_active_next_still_uses_original_gate_templates(self):
        done = subprocess.run([sys.executable, "-B", str(PROJECT / "scripts/agent_next_action.py"),
            "--project", str(self.project), "--evidence", str(self.active), "--format", "json"],
            env=environment(self.base), cwd=self.project, capture_output=True, timeout=15)
        self.assertEqual(0, done.returncode, done.stderr)
        value = json.loads(done.stdout)
        self.assertEqual("active_run", value["status"])
        self.assertEqual("record_pre_review_gates", value["next_step"])
        self.assertIn('"gate":"tests"', value["copyable_command"])
        self.assertEqual(["agent_operating_skill"], value["loaded_skills"])

    def test_import_guard_is_real_and_arguments_are_data(self):
        script = self.base / "script space.py"
        script.write_text("import json,sys;print(json.dumps(sys.argv[1:]))")
        args = ["space value", "$(never-run)", "line\nbreak"]
        done = subprocess.run(guarded_command(sys.executable, script, args, ["sqlite3"]),
                              env=environment(self.base), capture_output=True, timeout=15)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(args, json.loads(done.stdout))
        script.write_text("import sqlite3")
        rejected = subprocess.run(guarded_command(sys.executable, script, [], ["sqlite3"]),
                                  env=environment(self.base), capture_output=True, timeout=15)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn(b"sqlite3", rejected.stderr)

    def test_normalizer_preserves_nonvolatile_and_unknown_fields(self):
        def encoded(value):
            return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
        first = {"snapshot_id": "a" * 32, "captured_at": datetime.now(timezone.utc).isoformat(),
                 "active_runs": 1, "unknown": {"id": "c" * 32}}
        second = dict(first, snapshot_id="b" * 32, captured_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(normalize_output(encoded(first), "status"), normalize_output(encoded(second), "status"))
        second["unknown"] = {"id": "d" * 32}
        self.assertNotEqual(normalize_output(encoded(first), "status"), normalize_output(encoded(second), "status"))
        for bad in [dict(first, snapshot_id="bad"), dict(first, captured_at="2026-01-01"),
                    dict(first, captured_at="2026-01-01T00:00:00+09:00")]:
            with self.assertRaises(ValueError):
                normalize_output(encoded(bad), "status")
        with self.assertRaises(ValueError):
            normalize_output(json.dumps(first).encode(), "status")


if __name__ == "__main__":
    unittest.main()
