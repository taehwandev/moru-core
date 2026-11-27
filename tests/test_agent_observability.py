from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_observability import _bind_run_metrics, _trend_groups, discover_governed_projects, efficiency_trend_snapshot, status_snapshot
from agent_run_registry import register_run
from agent_scheduler import enqueue_task
from native_pretool_support import environment, prepare


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
            ws = Path(directory).resolve()
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
                            {"run_id": "run_fresh_codex", "started_at": "2026-09-01", "state": "failed"},
                            {"run_id": "empty-preflight", "started_at": "2026-10-05"},
                            {"run_id": "missing-preflight", "started_at": "2026-10-05"},
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
                conn.execute("CREATE TABLE threads (id TEXT, model TEXT, reasoning_effort TEXT)")
                conn.execute("INSERT INTO threads VALUES (?, ?, ?)", (codex_session_id, "old-model", "low"))
                conn.execute("INSERT INTO threads VALUES (?, ?, ?)", (codex_session_id, "gpt-6.1-sol", "xhigh"))
                conn.execute("INSERT INTO threads VALUES (?, ?, ?)", ("unused-thread", "unused-model", None))

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
                        (codex_spill_id, "2026-10-04 23:01:00.125-11:00", "gpt-6.1-sol", 100000, 0, 500000, 10000, 610000, 4000),
                        (codex_spill_id, "2026-10-05T10:02:00+00:00", "gpt-6.1-sol", 100000, 0, 500000, 10000, 610000, 4000),
                        (codex_spill_id, "2026-10-16T10:01:00+00:00", "gpt-6.1-sol", 50000, 0, 200000, 5000, 255000, 1500),
                        (claude_session_id, "2026-10-20T12:01:00+00:00", "claude-opus-5-5", 2000, 10000, 100000, 3000, 115000, 0),
                        (agy_spill_id, "2026-10-23T05:01:00-00:00", "gemini-4-argon", 5000, 0, 95000, 1000, 101000, 0),
                        ("unused-spill", "2026-10-23T05:01:00+00:00", "unused-model", 97, 0, 0, 0, 97, 0),
                    ],
                )

            discovered = discover_governed_projects(ws)
            self.assertEqual([project.resolve()], discovered)
            (runs_dir / "missing-preflight").mkdir()
            (runs_dir / "empty-preflight").mkdir()
            (runs_dir / "empty-preflight" / "preflight.json").write_text("{}")

            native_home = ws / "native-probe"
            native_home.mkdir()
            launcher, _ = prepare(native_home)
            env = environment(native_home)
            discovery_root = ws / "discovery-only"
            alias_target = discovery_root / "z-project"
            registry_only = discovery_root / "a-project"
            (alias_target / ".moru" / "runs").mkdir(parents=True)
            (registry_only / ".moru").mkdir(parents=True)
            (registry_only / ".moru" / "run-registry.json").write_text("{}")
            (discovery_root / "00-link").symlink_to(alias_target, target_is_directory=True)
            with patch.dict(os.environ, env, clear=True), patch(
                "agent_observability._discover_governed_projects_reference", side_effect=AssertionError("native discovery declined"),
            ):
                self.assertEqual([alias_target, registry_only, alias_target], discover_governed_projects(discovery_root))
                self.assertEqual(discovered, discover_governed_projects(ws))
            with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                report = efficiency_trend_snapshot(discovered, spill_db=spill_db, codex_db=codex_db, month="2026-10")
            with patch.dict(os.environ, env, clear=True), patch(
                "agent_observability._trend_groups_reference", side_effect=AssertionError("native declined"),
            ), patch(
                "agent_observability._trend_window_reference", side_effect=AssertionError("native window declined"),
            ), patch("sqlite3.connect", side_effect=AssertionError("native database read declined")), patch(
                "agent_observability._trend_report_reference", side_effect=AssertionError("native report declined"),
            ), patch(
                "agent_observability._trend_run_sources_reference", side_effect=AssertionError("native run files declined"),
            ), patch(
                "agent_observability._collect_runs_reference", side_effect=AssertionError("native run metadata declined"),
            ), patch(
                "agent_observability._bind_run_metrics_reference", side_effect=AssertionError("native run binding declined"),
            ):
                native = efficiency_trend_snapshot(discovered, spill_db=spill_db, codex_db=codex_db, month="2026-10")
            self.assertEqual({**report, "captured_at": native["captured_at"]}, native)
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

            from native_runtime_status_support import invoke
            args = ["--efficiency-trends", "--all-projects", "--workspace-root", str(ws),
                    "--month", "2026-10", "--spill-db", str(spill_db), "--codex-db", str(codex_db)]
            reference = invoke(launcher, native_home, project, args, backend="python")
            actual = invoke(launcher, native_home, project, args, PATH="")
            for process in (reference, actual):
                self.assertEqual((0, b""), (process.returncode, process.stderr))
            reference_report, actual_report = (json.loads(proc.stdout) for proc in (reference, actual))
            self.assertEqual(4, actual_report["spill_matched_runs"])
            self.assertRegex(actual_report["captured_at"], r"^\d{4}-\d\d-\d\dT")
            self.assertEqual(actual.stdout, reference.stdout.replace(
                json.dumps(reference_report["captured_at"]).encode(),
                json.dumps(actual_report["captured_at"]).encode(), 1,
            ))

            # Fraction lengths outside the shared Python profile must defer.
            from support.native_probe_transport import NativeProbe
            with patch.dict(os.environ, env, clear=True):
                native_sources = NativeProbe.request("--completion-probe", "status-trend-run-files", {
                    "state_dir": str(project / ".moru"),
                })
            self.assertEqual(4, len(native_sources["runs"]))
            self.assertNotIn("secret_prompt_fingerprint_should_never_leak", json.dumps(native_sources))
            with sqlite3.connect(spill_db) as conn:
                conn.execute("UPDATE token_usage_events SET created_at = ? WHERE run_id = ?",
                             ("2026-10-05T10:01:00.1Z", codex_spill_id))
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(NativeProbe.request("--completion-probe", "status-trend-db-utc", {
                    "dataset": "spill", "path": str(spill_db), "ids": [codex_spill_id],
                }))

    def test_native_trend_ties_keep_report_order_and_even_percentile_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            rows = [
                {"runtime": "codex", "model": model, "reasoning_effort": "high",
                 "same_work_mode": "fresh", "route": "task", "period_bucket": "2026-10",
                 "state": "completed", "turns": count, "weighted_tokens": count * 1234.5,
                 "reasoning_tokens": 2 * count, "required_docs_count": count,
                 "reused_gate_count": 0, "session_id": "must-not-be-sent"}
                for model in ("z-model", "a-model")
                for count in range(1, 7)
            ]
            env = environment(base)
            with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                reference = _trend_groups(rows)
            with patch.dict(os.environ, env, clear=True), patch(
                "agent_observability._trend_groups_reference", side_effect=AssertionError("native declined"),
            ):
                native = _trend_groups(rows)
            self.assertEqual(reference, native)
            self.assertEqual(["a-model", "z-model"], [row["model"] for row in native["cohorts"]])
            self.assertEqual(["z-model", "a-model"], [row["model"] for row in native["period_trends"]])
            self.assertEqual(5.0, native["period_trends"][0]["turns_p90"])
            self.assertEqual(3.5, native["period_trends"][0]["turns_p50"])
            self.assertNotIn("must-not-be-sent", json.dumps(native))

    def test_native_windows_preserve_equal_starts_and_next_month_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            first = "2026-10-01T00:00:00+00:00"
            second = "2026-10-31T23:59:59+00:00"
            outside = "2026-11-01T00:00:00+00:00"
            session = "session-id-not-in-wire"
            spill_id = "spill-id-not-in-wire"
            runs = [
                {"runtime": "codex", "session_id": session, "spill_run_id": spill_id, "run_id": name,
                 "started_at": stamp, "stamped_model": "", "stamped_effort": ""}
                for name, stamp in (("later", second), ("empty-tie", first), ("tie-winner", first),
                                    ("next-month", outside))
            ]
            events = {spill_id: [
                ("2026-09-30T23:59:59+00:00", "too-early", 100.0, 100, 100),
                (first, "initial", 0.1, 10, 1),
                (first, "latest-label", 0.2, 20, 2),
                (first, "", 0.3, 30, 3),
                (second, "last", 1.0, 50, 4),
                (outside, "outside", 100.0, 100, 100),
            ]}
            env = environment(base)
            with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                reference = _bind_run_metrics(runs, events, {}, month="2026-10")
            from support.native_probe_transport import NativeProbe
            with patch.dict(os.environ, env, clear=True), patch(
                "agent_observability._trend_window_reference", side_effect=AssertionError("native declined"),
            ), patch.object(NativeProbe, "request", wraps=NativeProbe.request) as transport:
                native = _bind_run_metrics(runs, events, {}, month="2026-10")
            self.assertEqual(reference, native)
            self.assertEqual(["empty-tie", "tie-winner", "later"], [row["run_id"] for row in native])
            self.assertEqual([0, 3, 1], [row["turns"] for row in native])
            self.assertEqual(["unknown", "latest-label", "last"], [row["model"] for row in native])
            self.assertEqual([0, 60, 50], [row["raw_tokens"] for row in native])
            payload = json.dumps(transport.call_args.args[2])
            self.assertNotIn(session, payload)
            self.assertNotIn(spill_id, payload)

    def test_run_window_ends_when_the_run_settles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            spill_id = "spill-settle"
            stamp = "2026-10-{}T10:00:00+00:00".format
            runs = [
                {"runtime": "claude", "session_id": "s", "spill_run_id": spill_id, "run_id": name,
                 "started_at": start, "settled_at": settled, "stamped_model": "m", "stamped_effort": ""}
                for name, start, settled in (
                    ("first", stamp("01"), stamp("02")),   # finished before the next run starts
                    ("open", stamp("05"), stamp("10")),    # settle cannot extend past the next start
                    ("late", stamp("08"), stamp("09")),    # last run in the session, finished
                )
            ]
            events = {spill_id: [(stamp(day), "m", 1.0, 1, 0)
                                 for day in ("01", "02", "03", "05", "06", "08", "09", "10", "20")]}
            env = environment(base)
            with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                reference = _bind_run_metrics(runs, events, {}, month="2026-10")
            # Usage at or after settlement is unattributed until the next run.
            self.assertEqual({"first": 1, "open": 2, "late": 1},
                             {row["run_id"]: row["turns"] for row in reference})
            from support.native_probe_transport import NativeProbe
            with patch.dict(os.environ, env, clear=True), patch(
                "agent_observability._trend_window_reference", side_effect=AssertionError("native declined"),
            ), patch.object(NativeProbe, "request", wraps=NativeProbe.request) as transport:
                native = _bind_run_metrics(runs, events, {}, month="2026-10")
            self.assertEqual(reference, native)
            projected = transport.call_args.args[2]["runs"]
            allowed = {"runtime", "session_id", "spill_run_id", "started_at", "settled_at",
                       "stamped_model", "stamped_effort", "index"}
            self.assertTrue(all(set(row) <= allowed for row in projected))
            self.assertEqual(
                [(stamp("01"), stamp("02")), (stamp("05"), stamp("10")), (stamp("08"), stamp("09"))],
                [(row["started_at"], row["settled_at"]) for row in projected],
            )


if __name__ == "__main__":
    unittest.main()
