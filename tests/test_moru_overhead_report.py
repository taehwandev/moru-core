"""The overhead report aggregates sessions inside the requested window only."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from moru_overhead_report import build_report, parse_args, render_markdown

NOW = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)


def _session(cwd: str, stamp: str, command: str) -> str:
    entry = {
        "type": "assistant", "timestamp": stamp, "cwd": cwd,
        "message": {"id": stamp, "usage": {"input_tokens": 100},
                    "content": [{"type": "tool_use", "id": stamp, "name": "Bash", "input": {"command": command}}]},
    }
    return json.dumps(entry) + "\n"


class OverheadReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        projects = self.base / "projects" / "p"
        projects.mkdir(parents=True)
        (projects / "inside.jsonl").write_text(
            _session("/w/moru-core", "2026-10-10T00:00:00Z", "moru-hook start") +
            _session("/w/moru-core", "2026-10-10T00:01:00Z", "ls"), encoding="utf-8")
        (projects / "other.jsonl").write_text(
            _session("/w/app", "2026-10-11T00:00:00Z", "moru-hook review"), encoding="utf-8")
        old = projects / "old.jsonl"
        old.write_text(_session("/w/app", "2026-08-01T00:00:00Z", "moru-hook finish"), encoding="utf-8")
        stamp = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc).timestamp()
        os.utime(old, (stamp, stamp))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report(self, *extra: str) -> dict:
        args = parse_args([
            "--projects-dir", str(self.base / "projects"), "--timings", str(self.base / "none.jsonl"),
            "--moru-root", "/w/moru-core", "--until", NOW.isoformat(), *extra,
        ])
        return build_report(args, NOW)

    def test_window_and_project_split(self) -> None:
        report = self._report("--days", "30")
        self.assertEqual(2, report["all"]["sessions"])
        self.assertEqual(1, report["moru_core"]["sessions"])
        self.assertEqual(50.0, report["moru_core"]["lifecycle_share_of_tool_calls_pct"])
        self.assertEqual({"start": 1, "review": 1}, report["all"]["lifecycle_calls_by_subcommand_total"])
        self.assertEqual(0, report["timings_jsonl"]["records"])

    def test_since_excludes_earlier_sessions_and_markdown_renders(self) -> None:
        report = self._report("--since", "2026-10-11T00:00:00+00:00")
        self.assertEqual(1, report["all"]["sessions"])
        text = render_markdown(report)
        self.assertIn("| lifecycle (launcher) Bash calls | 1.0 |", text)
        self.assertIn("Sessions: all=1, moru-core=0, other=1", text)


if __name__ == "__main__":
    unittest.main()
