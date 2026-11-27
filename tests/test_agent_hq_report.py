from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_hq_report import (
    MAX_REPORT_BYTES,
    SCHEMA_VERSION,
    emit_hq_finish_report,
    emit_hq_report_for_finish,
)
import agent_hq_report as hq
from native_pretool_support import environment, prepare
from support.native_probe_transport import NativeProbe


class AgentHqReportTests(unittest.TestCase):
    def test_native_bounds_keep_utf8_bytes_tie_order_and_caller_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            prepare(base)
            payload = {
                "schema": 1, "runId": "tie", "projectId": "", "taskId": "t", "operatorLabel": "op",
                "status": "finished", "result": "a" * 60, "evidence": "한" * 60,
                "decisionNeeded": "", "finishedAt": 1700000000000,
            }
            payload["projectId"] = "p" * (MAX_REPORT_BYTES + 1 - len(hq._encode_compact(payload)))
            self.assertEqual(MAX_REPORT_BYTES + 1, len(hq._encode_compact(payload)))
            expected = dict(payload)
            encoded = hq._bound_payload_reference(expected)
            with patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True), patch.object(
                hq, "_bound_payload_reference", side_effect=AssertionError("native HQ encoding declined"),
            ):
                self.assertEqual(encoded, hq._bound_payload(payload))
            self.assertEqual(expected, payload)
            self.assertEqual("a" * 60, payload["result"])
            self.assertEqual("한" * 56 + "...", payload["evidence"])

    def test_native_decision_and_finish_write_exact_python_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            _, project = prepare(base)
            options = ["가" * 60, "🧪" * 60, "☃" * 60]
            private = "unused-synthetic-private-value"
            preflight = {
                "hq_run_id": "lower-priority", "hq_project_id": "lower-project",
                "request_intake": {"target_summary": "  selected\nsummary", "raw_request": private},
                "route": {"command": "alternative-result", "notes": private}, "unrelated": private,
            }
            cases = [
                (emit_hq_finish_report, dict(preflight=preflight, passed_gates=['gate "quoted"', 'gate "quoted"'])),
                (hq.emit_hq_decision_report, dict(question="Which option?", evidence="A\nB", options=options)),
            ]
            for emit, kwargs in cases:
                with self.subTest(emit=emit.__name__), patch.object(hq.time, "time", return_value=1700000000):
                    args = {"project": project, "env": {"MORU_HQ_RUN_ID": emit.__name__,
                            "MORU_HQ_PROJECT_ID": "selected-project", "OTHER_PRIVATE_FIELD": private}, **kwargs}
                    with patch.dict(os.environ, {**environment(base), "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                        path = emit(**args)
                        expected = path.read_bytes()
                    path.unlink()
                    with patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True), patch.object(
                        hq, "_finish_bytes_reference", side_effect=AssertionError("Python finish fallback"),
                    ), patch.object(hq, "_decision_bytes_reference", side_effect=AssertionError("Python decision fallback")), (
                        patch.object(NativeProbe, "request", wraps=NativeProbe.request)
                    ) as transport:
                        self.assertEqual(path, emit(**args))
                        transport.assert_called_once()
                        protocol, operation, request = transport.call_args.args
                        self.assertEqual("--completion-probe", protocol)
                        self.assertEqual("hq-finish-assemble" if emit is emit_hq_finish_report
                                         else "hq-decision-assemble", operation)
                        self.assertNotIn(private, json.dumps(request))
                        self.assertNotIn("OTHER_PRIVATE_FIELD", json.dumps(request))
                    self.assertEqual(expected, path.read_bytes())
                    self.assertLessEqual(len(expected), MAX_REPORT_BYTES)
                    if emit is hq.emit_hq_decision_report:
                        kept = json.loads(expected)["decisionOptions"]
                        self.assertLess(len(kept), len(options))
                        self.assertEqual(options[:len(kept)], kept)
                    else:
                        data = json.loads(expected)
                        self.assertEqual(("selected-project", "selected summary", 'gate "quoted"'),
                                         (data["projectId"], data["result"], data["evidence"]))

    def test_non_hq_run_returns_none_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo-project"
            project.mkdir()
            result = emit_hq_finish_report(
                project=project,
                preflight={"agent_run_id": "run-local-1", "route": {"command": "small-change"}},
                passed_gates=["tests", "review hook"],
                env={},
            )
            self.assertIsNone(result)
            self.assertFalse((project / ".moru").exists())
            self.assertFalse((project / ".moru" / "hq").exists())

    def test_hq_env_run_writes_schema1_report_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "moru-app"
            project.mkdir()
            report_path = emit_hq_finish_report(
                project=project,
                preflight={
                    "agent_run_id": "agent-42",
                    "request_intake": {"target_summary": "wire finish bridge\nwith clean newline"},
                },
                passed_gates=["source docs", "tests", "tests", "review hook"],
                env={
                    "MORU_HQ_RUN_ID": "hq-run_2026.11",
                    "MORU_HQ_PROJECT_ID": "proj-moru",
                    "MORU_HQ_OPERATOR_LABEL": "codex-worker",
                    "MORU_HQ_DECISION_NEEDED": "Approve merge",
                },
            )
            expected = project / ".moru" / "hq" / "reports" / "hq-run_2026.11.json"
            self.assertEqual(report_path, expected)
            self.assertTrue(expected.is_file())
            raw = expected.read_bytes()
            self.assertLessEqual(len(raw), MAX_REPORT_BYTES)
            mode = stat.S_IMODE(expected.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(list(expected.parent.glob("*.tmp")), [])

            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["schema"], SCHEMA_VERSION)
            self.assertEqual(payload["runId"], "hq-run_2026.11")
            self.assertEqual(payload["projectId"], "proj-moru")
            self.assertEqual(payload["taskId"], "agent-42")
            self.assertEqual(payload["operatorLabel"], "codex-worker")
            self.assertEqual(payload["status"], "finished")
            self.assertEqual(payload["result"], "wire finish bridge with clean newline")
            self.assertEqual(payload["evidence"], "source docs, tests, review hook")
            self.assertEqual(payload["decisionNeeded"], "Approve merge")
            self.assertIsInstance(payload["finishedAt"], int)
            self.assertGreater(payload["finishedAt"], 1_700_000_000_000)

    def test_preflight_hq_run_id_and_origin_hq_emit_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "workspace-x"
            project.mkdir()

            path_from_id = emit_hq_finish_report(
                project=project,
                preflight={"hq_run_id": "preflight-run-7", "route": {"command": "implement"}},
                passed_gates=["tests"],
                env={},
            )
            self.assertEqual(path_from_id, project / ".moru" / "hq" / "reports" / "preflight-run-7.json")
            data_id = json.loads(path_from_id.read_text(encoding="utf-8"))
            self.assertEqual(data_id["projectId"], "workspace-x")
            self.assertEqual(data_id["taskId"], "preflight-run-7")
            self.assertEqual(data_id["result"], "finish passed (implement)")

            path_from_origin = emit_hq_finish_report(
                project=project,
                preflight={"origin": "hq", "agent_run_id": "origin-run-9"},
                passed_gates=[],
                env={},
            )
            self.assertEqual(path_from_origin, project / ".moru" / "hq" / "reports" / "origin-run-9.json")
            data_origin = json.loads(path_from_origin.read_text(encoding="utf-8"))
            self.assertEqual(data_origin["runId"], "origin-run-9")
            self.assertEqual(data_origin["evidence"], "all required gates passed")

    def test_oversized_fields_are_bounded_to_500_utf8_bytes_with_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bounded-app"
            project.mkdir()
            long_result = "결과요약 " * 120
            long_evidence = ", ".join(f"gate-verification-step-{i}" for i in range(60))
            long_decision = "Please review and approve deployment " * 30
            report_path = emit_hq_finish_report(
                project=project,
                preflight={"hq_run_id": "hq-oversized-1", "hq_result": long_result},
                passed_gates=[long_evidence],
                env={"MORU_HQ_DECISION_NEEDED": long_decision},
            )
            self.assertIsNotNone(report_path)
            raw = report_path.read_bytes()
            self.assertLessEqual(len(raw), MAX_REPORT_BYTES)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["runId"], "hq-oversized-1")
            self.assertEqual(payload["status"], "finished")
            self.assertTrue(payload["result"].endswith("..."))
            self.assertTrue(payload["evidence"].endswith("..."))

    def test_unsafe_run_ids_are_rejected_without_writing(self) -> None:
        unsafe_ids = [
            "../escape",
            "../../etc/passwd",
            "nested/run",
            "back\\slash",
            "..",
            ".hidden",
            "run..id",
            "has space",
            "bad\x00id",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "safe-app"
            project.mkdir()
            for unsafe in unsafe_ids:
                with self.subTest(run_id=unsafe):
                    result = emit_hq_finish_report(
                        project=project,
                        preflight={"hq_run_id": unsafe},
                        passed_gates=["tests"],
                        env={},
                    )
                    self.assertIsNone(result)
                    self.assertFalse((project / ".moru").exists())

    def test_finish_wrapper_filters_passed_gates_and_swallows_os_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "finish-app"
            project.mkdir()
            signals = [
                {"gate": "source docs", "signal": "SUCCESS"},
                {"gate": "ignored fail", "signal": "FAIL"},
                {"gate": "tests", "signal": "SUCCESS"},
            ]
            report = emit_hq_report_for_finish(
                project,
                {"hq_run_id": "hq-finish-wrap-1"},
                signals,
            )
            self.assertIsNotNone(report)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["evidence"], "source docs, tests")

            # A file at `.moru` forces OSError on mkdir; wrapper must not fail finish.
            blocked_project = Path(tmp) / "blocked-app"
            blocked_project.mkdir()
            (blocked_project / ".moru").write_text("not a dir", encoding="utf-8")
            self.assertIsNone(
                emit_hq_report_for_finish(
                    blocked_project,
                    {"hq_run_id": "hq-finish-wrap-2"},
                    signals,
                )
            )


if __name__ == "__main__":
    unittest.main()
