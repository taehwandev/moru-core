"""Unit tests for scripts/agent_behavior_eval.py offline trace/artifact grader.

Synthetic traces verify offline grading behavior only, not live provider scores.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "agent-behavior-cases.json"
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_behavior_eval.py"
_SPEC = importlib.util.spec_from_file_location("agent_behavior_eval", SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
eval_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["agent_behavior_eval"] = eval_mod
_SPEC.loader.exec_module(eval_mod)


def _ev(*kinds: str, final: str | None = "ok") -> list[dict[str, str]]:
    items = [{"kind": k} for k in kinds]
    if final is not None:
        items.append({"kind": "final", "status": final})
    return items


VALID_CASE_EVENTS = {
    "durable_prompt_completion": _ev("durable_record_written", "prompt_submitted", "run_completed", final="ok"),
    "parent_death_session_observed": _ev("prompt_submitted", "parent_died", "session_observed", final="needs_inspection"),
    "startup_retry_before_submit": _ev("startup_retry_before_submit", "prompt_submitted", final="ok"),
    "ambiguous_submission": _ev("prompt_submitted", "submission_ambiguous", final="needs_inspection"),
    "auth_failure_blocked": _ev("auth_failed", final="blocked"),
    "cancellation_blocked": _ev("prompt_submitted", "cancel_requested", "cancel_confirmed", final="blocked"),
    "empty_result_needs_inspection": _ev("prompt_submitted", "empty_result_detected", final="needs_inspection"),
    "compact_gate_ok": _ev("prompt_submitted", "gate_passed", final="ok"),
}


def _write_artifact(root: Path, provider: str, cid: str, rel: str, text: str = "ready\n") -> Path:
    target = root / provider / cid / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target


def _single_case_doc(
    cid: str = "c1", status: str = "ok", max_prompts: int = 1,
    req: list[str] | None = None, forb: list[str] | None = None,
    pairs: list[list[str]] | None = None, artifacts: dict[str, str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "cases": [{
            "id": cid, "expected_status": status, "max_prompts": max_prompts,
            "required_events": req or [], "forbidden_events": forb or [],
            "ordered_pairs": pairs or [], "artifacts": artifacts or {},
        }],
    }


class AgentBehaviorEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases_doc = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(self.cases_doc["cases"]), 8)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for p in eval_mod.SUPPORTED_PROVIDERS:
            _write_artifact(self.root, p, "durable_prompt_completion", "result.txt", "ready\n")
        self.traces_doc = {
            "schema_version": 1,
            "runs": [
                {"provider": p, "case_id": c["id"], "events": copy.deepcopy(VALID_CASE_EVENTS[c["id"]])}
                for p in eval_mod.SUPPORTED_PROVIDERS
                for c in self.cases_doc["cases"]
            ],
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_matrix_across_all_three_providers(self) -> None:
        report = eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)
        self.assertEqual((report["total"], report["passed"], report["failed"]), (24, 24, 0))
        self.assertEqual({r["provider"] for r in report["results"]}, {"codex", "claude", "agy"})
        self.assertTrue(all(r["passed"] and r["failures"] == [] for r in report["results"]))

    def test_missing_coverage_fails(self) -> None:
        self.traces_doc["runs"] = [
            r for r in self.traces_doc["runs"] if not (r["provider"] == "agy" and r["case_id"] == "compact_gate_ok")
        ]
        report = eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)
        self.assertEqual((report["passed"], report["failed"]), (23, 1))
        failed = [r for r in report["results"] if not r["passed"]]
        self.assertEqual(failed, [{"provider": "agy", "case_id": "compact_gate_ok", "passed": False, "failures": ["missing_run"]}])

    def test_replayed_history_without_completion_receipt_cannot_claim_ok(self):
        run = next(r for r in self.traces_doc['runs']
                   if (r['provider'], r['case_id']) == ('agy', 'parent_death_session_observed'))
        run['events'][-1]['status'] = 'ok'
        report = eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)
        self.assertEqual(report['failed'], 1, 'History replay is not an end_turn receipt')

    def test_duplicate_unknown_and_malformed_inputs_reject(self) -> None:
        dup_cases, dup_runs = copy.deepcopy(self.cases_doc), copy.deepcopy(self.traces_doc)
        dup_cases["cases"].append(copy.deepcopy(dup_cases["cases"][0]))
        dup_runs["runs"].append(copy.deepcopy(dup_runs["runs"][0]))
        unk_case = {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "missing_id", "events": _ev()}]}
        unk_prov = {"schema_version": 1, "runs": [{"provider": "other", "case_id": "compact_gate_ok", "events": _ev()}]}
        bad_nonfinal = {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "compact_gate_ok", "events": [{"kind": "gate_passed", "status": "ok"}]}]}
        bad_final = {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "compact_gate_ok", "events": [{"kind": "final", "status": "unknown"}]}]}
        for c_doc, t_doc, root, provs in [
            (dup_cases, self.traces_doc, self.root, ("codex",)),
            (self.cases_doc, dup_runs, self.root, ("codex",)),
            (self.cases_doc, unk_case, self.root, ("codex",)),
            (self.cases_doc, unk_prov, self.root, ("codex",)),
            (self.cases_doc, self.traces_doc, self.root, ("other",)),
            (self.cases_doc, self.traces_doc, self.root, ()),
            ({"schema_version": 1, "cases": []}, self.traces_doc, self.root, ("codex",)),
            (self.cases_doc, {"schema_version": 1, "runs": []}, self.root, ("codex",)),
            ({"schema_version": True, "cases": self.cases_doc["cases"]}, self.traces_doc, self.root, ("codex",)),
            (_single_case_doc(max_prompts=-1), {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "c1", "events": _ev()}]}, self.root, ("codex",)),
            (self.cases_doc, bad_nonfinal, self.root, ("codex",)),
            (self.cases_doc, bad_final, self.root, ("codex",)),
            (self.cases_doc, self.traces_doc, self.root / "missing_root", ("codex",)),
        ]:
            with self.subTest(provs=provs), self.assertRaises(ValueError):
                eval_mod.evaluate(c_doc, t_doc, root, providers=provs)

    def test_replay_and_final_anomalies_fail_despite_plausible_ok(self) -> None:
        for r in self.traces_doc["runs"]:
            key = (r["provider"], r["case_id"])
            if key == ("codex", "durable_prompt_completion"):
                r["events"] = _ev("durable_record_written", "prompt_submitted", "prompt_submitted", "run_completed", final="ok")
            elif key == ("claude", "parent_death_session_observed"):
                r["events"] = _ev("prompt_submitted", "parent_died", "prompt_submitted", "session_observed", final="ok")
            elif key == ("agy", "compact_gate_ok"):
                r["events"] = [{"kind": "prompt_submitted"}, {"kind": "gate_passed"}]
            elif key == ("codex", "ambiguous_submission"):
                r["events"] = _ev("prompt_submitted", "submission_ambiguous", final="ok")
        by_key = {(r["provider"], r["case_id"]): r for r in eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)["results"]}
        self.assertIn("max_prompts_exceeded:2>1", by_key[("codex", "durable_prompt_completion")]["failures"])
        self.assertIn("max_prompts_exceeded:2>1", by_key[("claude", "parent_death_session_observed")]["failures"])
        self.assertIn("final_event_count:0", by_key[("agy", "compact_gate_ok")]["failures"])
        self.assertIn("final_status:ok!=expected:needs_inspection", by_key[("codex", "ambiguous_submission")]["failures"])

    def test_wrong_order_and_missing_ordering_endpoints_fail(self) -> None:
        cases = _single_case_doc(req=["prompt_submitted"], pairs=[["step_a", "step_b"]])
        for evs, expected_err in (
            (_ev("prompt_submitted"), "ordered_pair_missing:step_a->step_b"),
            (_ev("prompt_submitted", "step_a"), "ordered_pair_missing:step_a->step_b"),
            (_ev("step_b", "step_a", "prompt_submitted"), "ordered_pair_out_of_order:step_a->step_b"),
        ):
            runs = {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "c1", "events": evs}]}
            rep = eval_mod.evaluate(cases, runs, self.root, providers=("codex",))
            self.assertEqual(rep["failed"], 1)
            self.assertIn(expected_err, rep["results"][0]["failures"])

    def test_forbidden_credential_and_billing_changes_fail(self) -> None:
        for r in self.traces_doc["runs"]:
            if (r["provider"], r["case_id"]) == ("codex", "auth_failure_blocked"):
                r["events"] = _ev("auth_failed", "credential_change", final="blocked")
            if (r["provider"], r["case_id"]) == ("claude", "durable_prompt_completion"):
                r["events"] = _ev("durable_record_written", "prompt_submitted", "paid_fallback", "run_completed", final="ok")
        by_key = {(r["provider"], r["case_id"]): r for r in eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)["results"]}
        self.assertIn("forbidden_event:credential_change", by_key[("codex", "auth_failure_blocked")]["failures"])
        self.assertIn("forbidden_event:paid_fallback", by_key[("claude", "durable_prompt_completion")]["failures"])

    def test_missing_wrong_and_path_escaping_artifacts_fail(self) -> None:
        (self.root / "claude" / "durable_prompt_completion" / "result.txt").unlink()
        _write_artifact(self.root, "agy", "durable_prompt_completion", "result.txt", "wrong\n")
        by_key = {(r["provider"], r["case_id"]): r for r in eval_mod.evaluate(self.cases_doc, self.traces_doc, self.root)["results"]}
        self.assertTrue(by_key[("codex", "durable_prompt_completion")]["passed"])
        self.assertIn("artifact_missing:result.txt", by_key[("claude", "durable_prompt_completion")]["failures"])
        self.assertIn("artifact_mismatch:result.txt", by_key[("agy", "durable_prompt_completion")]["failures"])
        with tempfile.TemporaryDirectory() as out_tmp:
            outside = Path(out_tmp) / "secret.txt"
            outside.write_bytes(b"ready\n")
            t_doc = {"schema_version": 1, "runs": [{"provider": "codex", "case_id": "c1", "events": _ev()}]}
            for bad_rel in ("../secret.txt", str(outside)):
                r_esc = eval_mod.evaluate(_single_case_doc(artifacts={bad_rel: "ready\n"}), t_doc, self.root, providers=("codex",))
                self.assertIn(f"artifact_path_escape:{bad_rel}", r_esc["results"][0]["failures"])
            sym_dir = self.root / "codex" / "c1"
            sym_dir.mkdir(parents=True, exist_ok=True)
            (sym_dir / "result.txt").symlink_to(outside)
            r_sym = eval_mod.evaluate(_single_case_doc(artifacts={"result.txt": "ready\n"}), t_doc, self.root, providers=("codex",))
            self.assertIn("artifact_symlink_escape:result.txt", r_sym["results"][0]["failures"])

    def test_cli_exit_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as io_tmp:
            traces_file = Path(io_tmp) / "traces.json"
            traces_file.write_text(json.dumps(self.traces_doc), encoding="utf-8")
            out_ok, err_ok = io.StringIO(), io.StringIO()
            code_ok = eval_mod.main(
                ["--cases", str(FIXTURE_PATH), "--traces", str(traces_file), "--artifact-root", str(self.root), "--providers", "codex,claude"],
                stdout=out_ok, stderr=err_ok,
            )
            self.assertEqual((code_ok, json.loads(out_ok.getvalue())["total"]), (0, 16))
            (self.root / "codex" / "durable_prompt_completion" / "result.txt").unlink()
            out_fail, err_fail = io.StringIO(), io.StringIO()
            code_fail = eval_mod.main(["--cases", str(FIXTURE_PATH), "--traces", str(traces_file), "--artifact-root", str(self.root)], stdout=out_fail, stderr=err_fail)
            self.assertEqual(code_fail, 1)
            self.assertGreater(json.loads(out_fail.getvalue())["failed"], 0)
            out_bad, err_bad = io.StringIO(), io.StringIO()
            code_bad = eval_mod.main(["--cases", str(FIXTURE_PATH), "--traces", str(Path(io_tmp) / "nope.json"), "--artifact-root", str(self.root)], stdout=out_bad, stderr=err_bad)
            self.assertEqual(code_bad, 2)
            self.assertIn("error:", err_bad.getvalue())

    @unittest.skipUnless(os.environ.get("MORU_TEST_BEHAVIOR_EVAL_NATIVE") == "1",
                         "requires native debug fixture")
    def test_native_cli_matches_python_bytes_and_never_needs_path_tools(self) -> None:
        from native_launcher_support import NATIVE

        self.assertTrue(NATIVE.is_file(), "native debug fixture required")
        with tempfile.TemporaryDirectory() as io_tmp:
            folder = Path(io_tmp)
            cases = folder / "cases.json"
            traces = folder / "traces.json"
            empty = folder / "empty"
            empty.mkdir()
            cid = "한글😀"
            self.cases_doc = _single_case_doc(
                cid=cid, req=["prompt_submitted"], forb=["after"],
                artifacts={"docs/safe.txt": "ready\n", "docs/absent.txt": "another"})
            self.traces_doc = {"schema_version": 1, "runs": [
                {"provider": "agy", "case_id": cid, "events": _ev("prompt_submitted")}
            ]}
            artifact = _write_artifact(self.root, "agy", cid, "docs/safe.txt")
            other = _write_artifact(self.root, "agy", cid, "docs/absent.txt", "another")
            cases.write_text(json.dumps(self.cases_doc), encoding="utf-8")
            traces.write_text(json.dumps(self.traces_doc), encoding="utf-8")
            args = ["--cases", str(cases), "--traces", str(traces),
                    "--artifact-root", str(self.root), "--providers", "agy"]

            def compare(argv, exit_code, native_flags=()):
                out, err = io.StringIO(), io.StringIO()
                expected = eval_mod.main(argv, stdout=out, stderr=err)
                native = subprocess.run(
                    [str(NATIVE), "offline-eval", "--behavior-eval", *native_flags, *argv],
                    env={**os.environ, "PATH": str(empty)}, capture_output=True, timeout=8)
                self.assertEqual(exit_code, expected)
                self.assertEqual((expected, out.getvalue().encode(), err.getvalue().encode()),
                                 (native.returncode, native.stdout, native.stderr))

            compare(args, 0)
            compare([f"--cases={cases}", f"--traces={traces}",
                     f"--artifact-root={self.root}", "--providers=agy"], 0)
            other.unlink()
            other.symlink_to(artifact)
            compare(args, 1)
            other.unlink()
            compare(args, 1)
            other.write_bytes(b"\xff")
            compare(args, 1)
            other.write_bytes(b"a" * eval_mod.MAX_ARTIFACT_BYTES)
            self.cases_doc["cases"][0]["artifacts"]["docs/absent.txt"] = (
                "a" * eval_mod.MAX_ARTIFACT_BYTES)
            cases.write_text(json.dumps(self.cases_doc), encoding="utf-8")
            compare(args, 0)
            other.write_bytes(b"a" * (eval_mod.MAX_ARTIFACT_BYTES + 1))
            compare(args, 1)
            other.unlink()
            os.mkfifo(other)
            compare(args, 1)
            (artifact.parent.parent / "alias").symlink_to(artifact.parent, target_is_directory=True)
            self.cases_doc["cases"][0]["artifacts"]["alias/safe.txt"] = "ready\n"
            cases.write_text(json.dumps(self.cases_doc), encoding="utf-8")
            self.traces_doc["runs"][0]["events"] = _ev("after", "after", final="blocked")
            traces.write_text(json.dumps(self.traces_doc), encoding="utf-8")
            compare(args, 1)  # Ordered trace and artifact failures in the same report.
            compare(args[:-1] + ["agy,agy"], 2)
            compare(args[:3] + [str(folder / "missing.json")] + args[4:], 2)
            traces.write_text('{"schema_version":1,"runs":[}', encoding="utf-8")
            compare(args, 2)
            traces.write_text('{"schema_version":1,"runs":[]}', encoding="utf-8")
            compare(args, 2)
            root_case = '{"schema_version":1,"cases":[{"id":"c1","expected_status":"ok","max_prompts":%s}]}'
            traces.write_text('{"schema_version":1,"runs":[{"provider":"agy","case_id":"c1",'
                              '"events":[{"kind":"final","status":"ok"}]}]}', encoding="utf-8")
            for token, code in [("-0", 0), ("18446744073709551615", 0),
                                ("18446744073709551616", 0), ("9" * 350, 0),
                                ("-1", 2), ("true", 2), ("0.0", 2), ("-0.0", 2),
                                ("NaN", 2), ("1e309", 2)]:
                with self.subTest(token=token):
                    cases.write_text(root_case % token, encoding="utf-8")
                    compare(args, code)
            # Exercise the wide-object index and the first-position/last-value
            # behavior when a decoded key repeats after the index is populated.
            fields = ['"a.txt":"stale"', '"b.txt":"stale"']
            fields.extend(f'"missing-{index}.txt":"value"' for index in range(40))
            fields.extend([r'"\u0061.txt":"still missing"', r'"\u0062.txt":"ready\n"'])
            _write_artifact(self.root, "agy", "c1", "b.txt")
            cases.write_text((root_case % "0").replace(
                '"max_prompts":0', '"max_prompts":0,"artifacts":{' + ",".join(fields) + "}"),
                encoding="utf-8")
            compare(args, 1)
            declined = subprocess.run(
                [str(NATIVE), "offline-eval", "--behavior-eval", "--int-max-str-digits=invalid", *args],
                env={**os.environ, "PATH": str(empty)}, capture_output=True, timeout=8)
            self.assertEqual((declined.returncode, declined.stdout, declined.stderr), (78, b"", b""))
            if hasattr(sys, "set_int_max_str_digits"):
                minimum = sys.int_info.str_digits_check_threshold
                original = sys.get_int_max_str_digits()
                limit_flag = (f"--int-max-str-digits={minimum}",)
                limit = "9" * minimum
                too_wide = limit + "9"
                try:
                    sys.set_int_max_str_digits(minimum)
                    cases.write_text(root_case % limit, encoding="utf-8")
                    compare(args, 0, limit_flag)
                    cases.write_text(root_case % too_wide, encoding="utf-8")
                    compare(args, 2, limit_flag)
                    cases.write_text((root_case % too_wide).replace(
                        '"max_prompts":' + too_wide,
                        f'"max_prompts":{too_wide},"max_prompts":0'), encoding="utf-8")
                    compare(args, 2, limit_flag)
                    sys.set_int_max_str_digits(0)
                    compare(args, 0, ("--int-max-str-digits=0",))
                    cases.write_text(root_case % ("9" * (sys.int_info.default_max_str_digits + 1)),
                                     encoding="utf-8")
                    compare(args, 0, ("--int-max-str-digits=0",))
                finally:
                    sys.set_int_max_str_digits(original)

    @unittest.skipUnless(os.environ.get("MORU_TEST_BEHAVIOR_EVAL_NATIVE") == "1",
                         "requires source-bound native debug fixture")
    def test_public_cli_uses_native_report_and_preserves_legacy_profiles(self) -> None:
        # Watch actual subprocess admission and Python grader calls in the
        # script process without replacing its verified candidate.
        observe = """
import os, runpy, sys
script = sys.argv.pop(1)
sys.argv[0] = script
sys.path.insert(0, os.path.dirname(script))
counts = [0, 0]
def audit(event, args):
    if event == 'subprocess.Popen':
        counts[0] += 1
def profile(frame, event, arg):
    if event == 'call' and frame.f_code.co_name == 'evaluate' and frame.f_code.co_filename == script:
        counts[1] += 1
sys.addaudithook(audit)
sys.setprofile(profile)
try:
    runpy.run_path(script, run_name='__main__')
finally:
    assert counts == list(map(int, os.environ['EXPECTED_COUNTS'].split(','))), counts
"""
        args = ["--cas", str(self.root / "cases.json"), "--traces", str(self.root / "traces.json"),
                "--artifact-root", str(self.root), "--providers", "agy"]
        cases, traces = Path(args[1]), Path(args[3])
        cases.write_text(json.dumps(_single_case_doc(
            artifacts={"sub/ready.txt": "ready\n"})), encoding="utf-8")
        traces.write_text(json.dumps({"schema_version": 1, "runs": [
            {"provider": "agy", "case_id": "c1", "events": _ev()}
        ]}), encoding="utf-8")
        artifact = _write_artifact(self.root, "agy", "c1", "sub/ready.txt")
        folder = artifact.parent

        def run(backend, counts):
            return subprocess.run([sys.executable, "-S", "-B", "-X", "int_max_str_digits=640",
                                   "-c", observe,
                                   str(SCRIPT_PATH), *args],
                                  env={**os.environ, "MORU_LAUNCHER_BACKEND": backend,
                                       "EXPECTED_COUNTS": counts, "PYTHONIOENCODING": "utf-16-le"},
                                  capture_output=True, timeout=12)

        def compare(exit_code, native_counts):
            reference = run("python", "0,1")
            actual = run("auto", native_counts)
            self.assertEqual((reference.returncode, reference.stderr), (exit_code, b""))
            self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                             (exit_code, reference.stdout, b""))

        folder.chmod(0o111)
        try:
            compare(0, "1,0")
            artifact.write_text("mismatch", encoding="utf-8")
            compare(1, "1,0")
        finally:
            folder.chmod(0o700)
        cases.write_text(json.dumps(_single_case_doc(max_prompts=2**80)), encoding="utf-8")
        compare(0, "1,0")


if __name__ == "__main__":
    unittest.main()
