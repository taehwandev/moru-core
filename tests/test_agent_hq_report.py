from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
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
    def test_generated_hq_alias_native_decision_and_source_guard(self) -> None:
        from benchmark_native_sha import capture

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            source = base / "source"
            capture(source)
            entry, project = prepare(base, source)
            empty = base / "empty-path"
            empty.mkdir()
            report = project / ".moru/hq/reports/alias-run.json"
            args = ["decision", "--project", str(project), "--question", "어떤 옵션?", "--option", "첫째"]

            def run(arguments, **overrides):
                env = {**environment(base, source), "MORU_HQ_RUN_ID": "alias-run", **overrides}
                return subprocess.run([str(entry), "agent-hq-report", *arguments], env=env, cwd=project,
                                      capture_output=True, timeout=12)

            reference = run(args, MORU_LAUNCHER_BACKEND="python", MORU_HQ_RUN_ID="")
            denied = run(args, PATH=str(empty), MORU_HQ_RUN_ID="")
            self.assertEqual(2, denied.returncode)
            self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                             (denied.returncode, denied.stdout, denied.stderr))
            self.assertFalse(report.parent.exists())

            malformed = [*args, "--unexpected"]
            reference = run(malformed, MORU_LAUNCHER_BACKEND="python")
            actual = run(malformed)
            self.assertEqual(2, actual.returncode)
            self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                             (actual.returncode, actual.stdout, actual.stderr))
            self.assertEqual(127, run(malformed, PATH=str(empty)).returncode)
            self.assertFalse(report.parent.exists())

            reference = run(args, MORU_LAUNCHER_BACKEND="python")
            self.assertEqual((0, b""), (reference.returncode, reference.stderr))
            expected = report.read_bytes()
            report.unlink()
            actual = run(args, PATH=str(empty))
            self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                             (actual.returncode, actual.stdout, actual.stderr))
            observed = report.read_bytes()
            before, after = (json.loads(raw)["finishedAt"] for raw in (expected, observed))
            self.assertIs(type(after), int)
            self.assertEqual(expected.replace(str(before).encode(), str(after).encode()), observed)
            report.unlink()

            with (source / "scripts/agent_hq_report.py").open("ab") as stream:
                stream.write(b"\n# source no longer matches the launcher\n")
            stale = run(args, PATH=str(empty))
            self.assertEqual((127, b""), (stale.returncode, stale.stdout))
            self.assertEqual([], list(report.parent.iterdir()))

    def test_direct_decision_cli_native_selection_fallback_and_lost_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            entry, project = prepare(base)
            probe = entry.with_name("moru-hook-native")
            real = probe.with_name("original-native")
            probe.rename(real)
            calls = base / "operations"
            lose_reply = base / "lose-reply"
            saved = base / "completed-write"
            report = project / ".moru/hq/reports/cli-run.json"
            quote = lambda path: shlex.quote(str(path))
            # Delegate every request to the real binary, recording native success or pre-effect decline.
            probe.write_text(
                f'#!/bin/sh\n{quote(real)} "$@"\nstatus=$?\n'
                f'printf "%s %s\\n" "$3" "$status" >> {quote(calls)}\n'
                f'if [ "$3" = hq-decision-cli ] && [ "$status" = 0 ] && [ -f {quote(lose_reply)} ]; then\n'
                f'  /bin/ln {quote(report)} {quote(saved)} || exit 3\n  exit 3\nfi\nexit "$status"\n'
            )
            probe.chmod(0o700)
            args = ["decision", "--project", str(project), "--question", "  Which\noption? ",
                    "--option", "  첫째 ", "--option", "second"]
            env = {**environment(base), "PATH": "", "MORU_HQ_RUN_ID": "cli-run"}

            def run(arguments, backend, **overrides):
                return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/agent_hq_report.py"), *arguments],
                                      env={**env, "MORU_LAUNCHER_BACKEND": backend, **overrides},
                                      cwd=project, capture_output=True, timeout=12)

            for arguments, run_id, expected_code, native_status in (
                (args, "cli-run", 0, 0), (args, "../foreign", 2, 0),
                (args + ["--unexpected"], "cli-run", 2, 125),
            ):
                with self.subTest(run=run_id, last_arg=arguments[-1]):
                    reference = run(arguments, "python", MORU_HQ_RUN_ID=run_id)
                    if reference.returncode == 0:
                        previous = report.read_bytes()
                        report.unlink()
                    calls.write_text("")
                    actual = run(arguments, "auto", MORU_HQ_RUN_ID=run_id)
                    self.assertEqual(expected_code, actual.returncode, actual.stderr)
                    self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                                     (actual.returncode, actual.stdout, actual.stderr))
                    self.assertEqual([f"hq-decision-cli {native_status}"], calls.read_text().splitlines())
                    if expected_code == 0:
                        current = report.read_bytes()
                        old_time, new_time = (json.loads(raw)["finishedAt"] for raw in (previous, current))
                        self.assertIs(type(new_time), int)
                        self.assertEqual(previous.replace(str(old_time).encode(), str(new_time).encode()), current)
                        report.unlink()
                    self.assertEqual([], list(report.parent.iterdir()))

            calls.write_text("")
            lose_reply.touch()
            uncertain = run(args, "auto")
            self.assertEqual(1, uncertain.returncode)
            self.assertEqual(b"", uncertain.stdout)
            self.assertIn(b"outcome could not be determined", uncertain.stderr)
            self.assertEqual(["hq-decision-cli 0"], calls.read_text().splitlines())
            self.assertTrue(report.samefile(saved))

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
                    path.write_bytes(b"old contents")
                    path.chmod(0o644)
                    with path.open("rb") as old_file, patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True), patch.object(
                        hq, "_finish_bytes_reference", side_effect=AssertionError("Python finish fallback"),
                    ), patch.object(hq, "_decision_bytes_reference", side_effect=AssertionError("Python decision fallback")), (
                        patch.object(hq, "_atomic_write_bytes_reference", side_effect=AssertionError("Python write fallback"))
                    ), (
                        patch.object(NativeProbe, "request", wraps=NativeProbe.request)
                    ) as transport:
                        self.assertEqual(path, emit(**args))
                        self.assertEqual(b"old contents", old_file.read())
                        operations = [call.args[1] for call in transport.call_args_list]
                        self.assertEqual(["hq-report-run-id", "hq-finish-assemble" if emit is emit_hq_finish_report
                                          else "hq-decision-assemble", "hq-report-replace"], operations)
                        for call in transport.call_args_list:
                            self.assertEqual("--completion-probe", call.args[0])
                            self.assertNotIn(private, json.dumps(call.args[2]))
                            self.assertNotIn("OTHER_PRIVATE_FIELD", call.args[2])
                    self.assertEqual(expected, path.read_bytes())
                    self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
                    self.assertEqual([], list(path.parent.glob("*.tmp")))
                    self.assertLessEqual(len(expected), MAX_REPORT_BYTES)
                    if emit is hq.emit_hq_decision_report:
                        kept = json.loads(expected)["decisionOptions"]
                        self.assertLess(len(kept), len(options))
                        self.assertEqual(options[:len(kept)], kept)
                    else:
                        data = json.loads(expected)
                        self.assertEqual(("selected-project", "selected summary", 'gate "quoted"'),
                                         (data["projectId"], data["result"], data["evidence"]))

    def test_writer_refuses_symlink_ancestors_and_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            prepare(base)
            external = base / "external"
            external.mkdir()
            sentinel = external / "protected"
            sentinel.write_bytes(b"unchanged")
            parts = (".moru", "hq", "reports", "r.json")
            with patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True):
                for index, part in enumerate(parts):
                    with self.subTest(part=part):
                        project = base / f"test-{index}"
                        link = project.joinpath(*parts[:index + 1])
                        link.parent.mkdir(parents=True)
                        link.symlink_to(sentinel if index == 3 else external, target_is_directory=index < 3)
                        with self.assertRaises(OSError):
                            emit_hq_finish_report(project=project, preflight={"hq_run_id": "r"},
                                                  passed_gates=["tests"], env={})
                        self.assertTrue(link.is_symlink())
                        self.assertEqual([sentinel], list(external.iterdir()))
                        self.assertEqual(b"unchanged", sentinel.read_bytes())

    def test_lost_acknowledgement_after_native_replace_does_not_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            _, project = prepare(base)
            run_process = subprocess.run
            writes = []

            def lose_write_response(argv, **kwargs):
                done = run_process(argv, **kwargs)
                if argv[-1] == "hq-report-replace":
                    self.assertEqual((0, b""), (done.returncode, done.stderr))
                    writes.append(done)
                    raise subprocess.TimeoutExpired(argv, 10)
                return done

            with patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True), patch.object(
                hq, "_atomic_write_bytes_reference", side_effect=AssertionError("write replayed"),
            ), patch("support.native_probe_transport.subprocess.run", side_effect=lose_write_response):
                with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                    emit_hq_finish_report(project=project, preflight={"hq_run_id": "once"}, passed_gates=[], env={})
            self.assertEqual(1, len(writes))
            path = project / ".moru/hq/reports/once.json"
            self.assertEqual("once", json.loads(path.read_bytes())["runId"])
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_native_run_id_selects_only_the_authorized_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            prepare(base)
            hidden = "unrelated-lower-priority"
            cases = [
                ("  env-ok ", hidden, hidden, hidden, "env-ok", {"env_id": "  env-ok "}),
                ("../invalid", hidden, hidden, hidden, None, {"env_id": "../invalid"}),
                (None, "preflight-ok", hidden, hidden, "preflight-ok", {"preflight_id": "preflight-ok"}),
                (None, "bad..id", "HQ", hidden, None, {"preflight_id": "bad..id"}),
                (None, None, " hQ ", "_worker", "_worker", {"origin": " hQ ", "agent_id": "_worker"}),
            ]
            with patch.dict(os.environ, {**environment(base), "PATH": ""}, clear=True):
                native_request = NativeProbe.request
                for env_id, pf_id, origin, agent_id, expected, selected in cases:
                    def check_reply(*args):
                        reply = native_request(*args)
                        self.assertEqual({"run_id": expected or ""}, reply)
                        return reply

                    with self.subTest(expected=expected, selected=selected), patch.object(
                        NativeProbe, "request", side_effect=check_reply,
                    ) as transport:
                        preflight = {"hq_run_id": pf_id, "origin": origin, "agent_run_id": agent_id,
                                     "unrelated": hidden}
                        self.assertEqual(expected, hq._resolve_hq_run_id(preflight, {"MORU_HQ_RUN_ID": env_id}))
                        request = dict.fromkeys(("env_id", "preflight_id", "origin", "agent_id"))
                        transport.assert_called_once_with("--completion-probe", "hq-report-run-id", request | selected)
                with patch.object(NativeProbe, "request", side_effect=AssertionError("unrelated HQ probe")):
                    self.assertIsNone(emit_hq_finish_report(project=base, preflight={"origin": "local",
                                      "agent_run_id": hidden}, passed_gates=["tests"], env={}))
                    self.assertFalse((base / ".moru").exists())
                for reply in (None, {"unexpected": True}, {"run_id": "different-safe-id"}):
                    with self.subTest(reply=reply), patch.object(NativeProbe, "request", return_value=reply):
                        self.assertEqual("original-id", hq.hq_run_id_from_env({"MORU_HQ_RUN_ID": "original-id"}))
                        self.assertEqual("", hq.hq_run_id_from_env({"MORU_HQ_RUN_ID": "../invalid"}))

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
