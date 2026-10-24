from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_observability import discover_governed_projects, efficiency_trend_snapshot, status_snapshot
from agent_run_registry import register_run
from agent_scheduler import enqueue_task


class AgentObservabilityTests(unittest.TestCase):
    def test_snapshot_exposes_only_aggregated_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = register_run(project, project / "preflight.json", {"command": "task"}, {})
            enqueue_task(project, run["run_id"])
            snapshot = status_snapshot(project)
            self.assertEqual(2, snapshot["api_version"])
            self.assertTrue(snapshot["snapshot_id"])
            self.assertTrue(snapshot["captured_at"])
            self.assertEqual("project-state-lock", snapshot["consistency"])
            self.assertEqual(1, snapshot["api_contract"]["contract_version"])
            self.assertEqual(1, snapshot["active_runs"])
            self.assertEqual({"queued": 1}, snapshot["task_counts"])
            self.assertTrue(snapshot["events"]["run.started"])
            self.assertNotIn("request", str(snapshot))

    def test_efficiency_trend_snapshot_aggregates_cohorts_and_weekly_periods_content_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory)
            project = ws / "sample-repo"
            runs_dir = project / ".moru" / "runs"
            runs_dir.mkdir(parents=True)

            codex_session_id = "019a0500-0000-7000-8000-000000000001"
            codex_spill_id = "run_" + hashlib.sha256(codex_session_id.encode("utf-8")).hexdigest()[:24]
            claude_session_id = "claude-sess-oct-01"
            agy_session_id = "4e644c99-bbab-4318-a995-df2558c6a0c1"
            agy_spill_id = "run_" + hashlib.sha256(agy_session_id.encode("utf-8")).hexdigest()[:24]

            (project / ".moru" / "run-registry.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "runs": [
                            {
                                "run_id": "run_fresh_codex",
                                "command": "task",
                                "state": "completed",
                                "started_at": "2026-10-05T10:00:00+00:00",
                                "resume_generation": 0,
                            },
                            {
                                "run_id": "run_cont_codex",
                                "command": "small-change",
                                "state": "completed",
                                "started_at": "2026-10-16T10:00:00+00:00",
                                "resume_generation": 1,
                            },
                            {
                                "run_id": "run_fresh_claude",
                                "command": "analysis",
                                "state": "completed",
                                "started_at": "2026-10-20T12:00:00+00:00",
                                "resume_generation": 0,
                            },
                            {
                                "run_id": "run_fresh_agy",
                                "command": "small-change",
                                "state": "completed",
                                "started_at": "2026-10-23T05:00:00+00:00",
                                "resume_generation": 0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            for run_id, runtime, sess_id, ts, prev_action, docs, reused in [
                ("run_fresh_codex", "codex", codex_session_id, "2026-10-05T10:00:00+00:00", "", ["a.md", "b.md", "c.md"], False),
                ("run_cont_codex", "codex", codex_session_id, "2026-10-16T10:00:00+00:00", "run_fresh_codex", ["a.md"], True),
                ("run_fresh_claude", "claude", claude_session_id, "2026-10-20T12:00:00+00:00", "", ["x.md", "y.md"], False),
                ("run_fresh_agy", "agy", agy_session_id, "2026-10-23T05:00:00+00:00", "", ["s1.md", "s2.md"], False),
            ]:
                rdir = runs_dir / run_id
                rdir.mkdir(parents=True)
                (rdir / "preflight.json").write_text(
                    json.dumps(
                        {
                            "timestamp": ts,
                            "request_fingerprint": "secret_prompt_fingerprint_should_never_leak",
                            "runtime_session": {"runtime": runtime, "session_id": sess_id},
                            "work": {"id": "work_1", "previous_action": prev_action},
                            "route": {} if run_id == "run_fresh_claude" else {"command": "small-change" if prev_action else "task", "required_docs": docs},
                            "route_command": {
                                "command": ["python3", "workflow.py", "route", "analysis", "--request", "secret_prompt_fingerprint_should_never_leak"]
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                gate_entry = (
                    {"gate": "tests", "status": "SUCCESS", "source": "reuse", "reuse_provenance": {"run_id": prev_action, "reason": "same inputs"}}
                    if reused
                    else {"gate": "tests", "status": "SUCCESS", "source": "hook"}
                )
                (rdir / "gate-evidence.json").write_text(
                    json.dumps({"entries": [gate_entry]}),
                    encoding="utf-8",
                )

            codex_db = ws / "state_5.sqlite"
            with sqlite3.connect(codex_db) as conn:
                conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, model TEXT, reasoning_effort TEXT)")
                conn.execute("INSERT INTO threads VALUES (?, ?, ?)", (codex_session_id, "gpt-6.1-sol", "xhigh"))

            spill_db = ws / "events.sqlite3"
            with sqlite3.connect(spill_db) as conn:
                conn.execute(
                    "CREATE TABLE token_usage_events ("
                    "run_id TEXT, created_at TEXT, model TEXT, "
                    "accounting_uncached_input_tokens INTEGER, accounting_cache_creation_input_tokens INTEGER, "
                    "accounting_cache_read_input_tokens INTEGER, output_tokens INTEGER, "
                    "total_tokens INTEGER, accounting_reasoning_output_tokens INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO token_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (codex_spill_id, "2026-10-05T09:50:00Z", "gpt-6.1-sol", 999999, 0, 0, 99999, 1099998, 9999),
                        (codex_spill_id, "2026-10-05T10:01:00Z", "gpt-6.1-sol", 100000, 0, 500000, 10000, 610000, 4000),
                        (codex_spill_id, "2026-10-05T10:02:00+00:00", "gpt-6.1-sol", 100000, 0, 500000, 10000, 610000, 4000),
                        (codex_spill_id, "2026-10-16T10:01:00+00:00", "gpt-6.1-sol", 50000, 0, 200000, 5000, 255000, 1500),
                        (claude_session_id, "2026-10-20T12:01:00+00:00", "claude-opus-5-5", 2000, 10000, 100000, 3000, 115000, 0),
                        (agy_spill_id, "2026-10-23T05:01:00+00:00", "gemini-4-argon", 5000, 0, 95000, 1000, 101000, 0),
                    ],
                )

            discovered = discover_governed_projects(ws)
            self.assertEqual([project.resolve()], discovered)

            report = efficiency_trend_snapshot(discovered, spill_db=spill_db, codex_db=codex_db, month="2026-10")
            self.assertEqual("2026-10", report["month_filter"])
            self.assertEqual(4, report["total_runs"])
            self.assertEqual(4, report["spill_matched_runs"])
            self.assertEqual(1.0, report["binding_coverage_ratio"])
            self.assertEqual(3, report["fresh_runs"])
            self.assertEqual(1, report["continuation_runs"])

            by_mode = {(c["runtime"], c["model"], c["reasoning_effort"], c["same_work_mode"]): c for c in report["cohorts"]}
            fresh_codex = by_mode[("codex", "gpt-6.1-sol", "xhigh", "fresh")]
            cont_codex = by_mode[("codex", "gpt-6.1-sol", "xhigh", "continuation")]
            fresh_agy = by_mode[("antigravity", "gemini-4-argon", "unknown", "fresh")]
            self.assertEqual(2.0, fresh_codex["turns_p50"])
            self.assertEqual(1.0, cont_codex["turns_p50"])
            self.assertEqual(1.0, cont_codex["avg_reused_gates"])
            self.assertEqual(3.0, fresh_codex["avg_required_docs"])
            self.assertEqual(1.0, fresh_agy["turns_p50"])
            self.assertEqual(2.0, fresh_agy["avg_required_docs"])

            periods = {p["period"] for p in report["period_trends"]}
            self.assertEqual({"2026-10-W1", "2026-10-W3", "2026-10-W4"}, periods)
            self.assertNotIn("secret_prompt_fingerprint_should_never_leak", json.dumps(report))

            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent-os-status.py"),
                    "--efficiency-trends",
                    "--all-projects",
                    "--workspace-root",
                    str(ws),
                    "--month",
                    "2026-10",
                    "--spill-db",
                    str(spill_db),
                    "--codex-db",
                    str(codex_db),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            cli_payload = json.loads(proc.stdout)
            self.assertEqual(4, cli_payload["spill_matched_runs"])


if __name__ == "__main__":
    unittest.main()
