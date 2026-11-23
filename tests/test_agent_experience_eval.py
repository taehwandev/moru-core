from __future__ import annotations

import copy
from contextlib import redirect_stdout
from datetime import date
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_experience_eval", ROOT / "scripts/agent_experience_eval.py")
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class ExperienceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.json"
        self.fixture = {
            "schema_version": 1, "description": "Synthetic arithmetic fixture.",
            "records": [
                {"id": "0000000000000001", "body": "First.", "source": "synthetic fixture"},
                {"id": "0000000000000002", "body": "Second.", "source": "synthetic fixture"},
                {"id": "0000000000000003", "body": "Third.", "source": "synthetic fixture"},
            ],
            "cases": [{"id": "mixed", "category": "arithmetic", "request": "first",
                       "expected_relevant": ["0000000000000001", "0000000000000002"]}],
        }

    def load(self, fixture=None):
        self.path.write_text(json.dumps(fixture or self.fixture), encoding="utf-8")
        return evaluator.load_fixture(self.path)

    def engine(self, rendered):
        def lines(project, scope, **context):
            self.assertEqual(len(context["records"]), 3)
            return ["reference header", *["- " + json.dumps({"id": item}) for item in rendered]]
        return SimpleNamespace(_digest=lambda record: "fixture-digest",
                               _recall=lambda project, scope, **context: context["records"],
                               recall_lines=lines)

    def test_metrics_count_rendered_context_instead_of_all_ranked_candidates(self):
        rendered = ["0000000000000001", "0000000000000003"]
        report = evaluator.evaluate(self.engine(rendered), self.load(), ROOT)
        metrics = report["metrics"]
        self.assertEqual((metrics["precision"], metrics["recall"]), (0.5, 0.5))
        self.assertEqual((metrics["irrelevant_selections"], metrics["misses"]), (1, 1))
        self.assertEqual(metrics["payload_characters"], sum(len(json.dumps({"id": item})) for item in rendered))
        self.assertEqual(report["cases"][0]["missed_ids"], ["0000000000000002"])
        self.assertEqual(len(report["cases"][0]["ranked_ids"]), 3)

    def test_empty_denominators_are_unknown_instead_of_perfect_scores(self):
        fixture = self.load()
        fixture["cases"][0]["expected_relevant"] = []
        report = evaluator.evaluate(self.engine([]), fixture, ROOT)
        self.assertIsNone(report["metrics"]["precision"])
        self.assertIsNone(report["metrics"]["recall"])

    def test_context_free_listing_does_not_inflate_retrieval_metrics(self):
        fixture = self.load()
        fixture["cases"].append({"id": "listing", "category": "listing",
                                  "expected_relevant": ["0000000000000001"]})
        report = evaluator.evaluate(self.engine(["0000000000000001"]), fixture, ROOT)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["retrieval_case_count"], 1)
        self.assertEqual(report["metrics"]["expected"], 2)
        self.assertEqual(report["metrics"]["recall"], 0.5)
        self.assertEqual(report["total_payload_characters"], 2 * report["metrics"]["payload_characters"])

    def test_conditions_and_expiry_are_materialized_without_mutating_fixture(self):
        fixture = self.load()
        fixture["records"][0].update(applies_when="A qualifying symptom.", review_in_days=0)
        original = copy.deepcopy(fixture)
        observed = []
        engine = self.engine([])
        engine._digest = lambda record: observed.append(dict(record)) or "digest"
        evaluator.evaluate(engine, fixture, ROOT)
        self.assertEqual(fixture, original)
        self.assertEqual(observed[0]["applies_when"], "A qualifying symptom.")
        self.assertEqual(observed[0]["review_on"], evaluator.date.today().isoformat())
        self.assertNotIn("review_in_days", observed[0])

    def test_invalid_fixture_fields_are_rejected(self):
        mutations = [
            lambda value: value.update(schema_version=2),
            lambda value: value.update(schema_version=True),
            lambda value: value["records"][1].update(id="0000000000000001"),
            lambda value: value["records"][0].update(source_files=[]),
            lambda value: value["records"][0].update(applies_when="x" * 161),
            lambda value: value["records"][0].update(not_when="two\nlines"),
            lambda value: value["records"][0].update(review_in_days=True),
            lambda value: value["records"][0].update(status=[]),
            lambda value: value["records"][0].update(replaces="ffffffffffffffff"),
            lambda value: value["records"][0].update(replaces=[]),
            lambda value: value["cases"][0].update(expected_relevant=["ffffffffffffffff"]),
            lambda value: value["cases"][0].update(target_paths="not-a-list"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                invalid = copy.deepcopy(self.fixture)
                mutate(invalid)
                with self.assertRaises(ValueError):
                    self.load(invalid)

    def test_unknown_or_duplicate_rendered_ids_are_rejected(self):
        for rendered in [["ffffffffffffffff"], ["0000000000000001"] * 2]:
            with self.subTest(rendered=rendered), self.assertRaises(ValueError):
                evaluator.evaluate(self.engine(rendered), self.load(), ROOT)

    def test_checked_in_fixture_has_explicit_limitations(self):
        fixture = evaluator.load_fixture(evaluator.DEFAULT_FIXTURE)
        self.assertEqual(len(fixture["cases"]), 14)
        limits = [case for case in fixture["cases"] if case["category"] == "known_lexical_limit"]
        self.assertEqual({case["id"] for case in limits}, {"generic_overlap", "zero_overlap_paraphrase"})
        self.assertTrue(all(case.get("applicability_expectation") for case in limits))

    def test_engine_root_loads_the_requested_module(self):
        engine_dir = Path(self.directory.name)
        (engine_dir / "agent_project_memory.py").write_text("MARKER = 'historical fixture'\n", encoding="utf-8")
        self.assertEqual(evaluator.load_engine(engine_dir).MARKER, "historical fixture")

    def test_default_cli_native_metrics_match_python_report_bytes(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        env = environment(base)
        python_output, native_output = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            with redirect_stdout(python_output):
                self.assertEqual(0, evaluator.main([]))
        with patch.dict(os.environ, env, clear=True), redirect_stdout(native_output):
            with (patch.object(evaluator, "_python_metrics", side_effect=AssertionError("native metrics missing")),
                  patch.object(evaluator, "_python_records", side_effect=AssertionError("native records missing")),
                  patch.object(evaluator, "_observe", side_effect=AssertionError("native batch missing")),
                  patch.object(evaluator, "_validate_fixture", side_effect=AssertionError("native validation missing"))):
                self.assertEqual(0, evaluator.main([]))
        self.assertEqual(python_output.getvalue(), native_output.getvalue())

    def test_stable_experience_cli_runs_without_python_and_preserves_reference_fallback(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare, result

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        entry, project = prepare(base)
        empty = base / "empty-path"
        empty.mkdir()
        with_python = base / "python-path"
        with_python.mkdir()
        (with_python / "python3").symlink_to(sys.executable)

        def invoke(args, *, selected_path, zone, backend="auto"):
            env = {**environment(base), "PATH": str(selected_path), "TZ": zone, "MORU_LAUNCHER_BACKEND": backend}
            return result(subprocess.run([str(entry), "experience-eval", *args], input=b"", cwd=project,
                                         env=env, capture_output=True, timeout=10))

        alias = project / "relative fixture.json"
        alias.symlink_to(evaluator.DEFAULT_FIXTURE)
        for zone, args in (("Pacific/Kiritimati", []), ("America/Los_Angeles", ["--fixture", alias.name])):
            with self.subTest(zone=zone, args=args):
                expected = invoke(args, selected_path=with_python, zone=zone, backend="python")
                native = invoke(args, selected_path=empty, zone=zone)
                self.assertEqual(0, native[0], native[2])
                self.assertEqual(expected, native)
                inputs = json.loads(native[1])["inputs"]
                self.assertEqual(str(evaluator.DEFAULT_FIXTURE.resolve()), inputs["fixture"]["path"])
        broken = project / "broken.json"
        broken.symlink_to(project / "missing.json")
        historic = project / "historical"
        historic.mkdir()
        (historic / "agent_project_memory.py").write_text(
            "def _digest(record): return 'historical'\n"
            "def _recall(*args, **kwargs): return []\n"
            "def recall_lines(*args, **kwargs): return []\n", encoding="utf-8")
        historic_args = ["--engine-root", str(historic)]
        historic_report = invoke(historic_args, selected_path=with_python, zone="UTC0")
        self.assertEqual(0, historic_report[0], historic_report[2])
        self.assertEqual([], json.loads(historic_report[1])["cases"][0]["ranked_ids"])
        self.assertEqual(historic_report, invoke(historic_args, selected_path=with_python, zone="UTC0", backend="python"))
        for args in (["--help"], ["--unsupported"], ["--fixture=" + broken.name]):
            with self.subTest(fallback=args):
                expected = invoke(args, selected_path=with_python, zone="UTC0", backend="python")
                self.assertEqual(expected, invoke(args, selected_path=with_python, zone="UTC0"))

    def test_native_records_match_python_order_digest_and_calendar_overflow(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        engine = evaluator.load_engine(evaluator.SCRIPTS)
        items = self.fixture["records"]
        items[0] = {"id": items[0]["id"], "review_in_days": 1,
                    "body": '한글 "quote" \\ 🚀 é', "source": "synthetic fixture",
                    "scope": "all", "status": "approved", "not_when": "예외"}
        items[1]["review_in_days"] = -1
        with patch.dict(os.environ, environment(base), clear=True):
            for today, expected_date in (
                (date(2000, 2, 28), "2000-02-29"),
                (date(2100, 2, 28), "2100-03-01"),
                (date(2024, 12, 31), "2025-01-01"),
                (date(2024, 1, 1), "2024-01-02"),
            ):
                with self.subTest(today=today):
                    expected = evaluator._python_records(engine, items, today)
                    native = evaluator._native_records(items, today)
                    self.assertEqual(json.dumps(expected, ensure_ascii=False),
                                     json.dumps(native, ensure_ascii=False))
                    self.assertEqual(expected_date, native[0]["review_on"])
                    self.assertNotIn("review_in_days", native[0])
                    self.assertEqual("active", native[1]["status"])
                    self.assertEqual("task", native[1]["scope"])
            for today in (date.min, date.max):
                with self.subTest(today=today):
                    self.assertIsNone(evaluator._native_records(items, today))
                    with self.assertRaises(OverflowError):
                        evaluator._evaluation_records(engine, items, today, native=True)

    def test_native_recall_batch_keeps_ranked_ids_when_unicode_budget_skips_rows(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        engine = evaluator.load_engine(evaluator.SCRIPTS)
        items = self.fixture["records"]
        items[0]["body"] = "큰 기록 🚀 " * 12
        items[1]["body"] = "짧은 기록 🚀"
        case = self.fixture["cases"][0]
        case["request"] = ""
        records = evaluator._python_records(engine, items, date.today())
        short = {key: records[1][key] for key in ("id", "body", "source", "review_on")}
        budget = len(json.dumps(short, ensure_ascii=False))

        env = environment(base)
        with patch.object(engine, "MAX_RECALL_ITEMS", 1), patch.object(engine, "MAX_RECALL_CHARS", budget):
            with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                expected = evaluator._python_metrics(evaluator._observe(engine, [case], ROOT, records))
            with patch.dict(os.environ, env, clear=True):
                native = evaluator._native_recall_metrics(engine, [case], records)
                unsupported = dict(case, id="unsupported", scope=None)
                self.assertIsNone(evaluator._native_recall_metrics(engine, [case, unsupported], records))
                self.assertIsNone(evaluator._native_recall_metrics(engine, [case] * 200, records * 100))
                with patch.object(evaluator, "date") as clock:
                    clock.today.side_effect = [date(2024, 1, 1), date(2024, 1, 2)]
                    self.assertIsNone(evaluator._native_recall_metrics(engine, [case], records))
        self.assertEqual(json.dumps(expected), json.dumps(native))
        self.assertEqual([record["id"] for record in records], native["cases"][0]["ranked_ids"])
        self.assertEqual([short["id"]], native["cases"][0]["rendered_ids"])
        self.assertEqual(budget, native["total_payload_characters"])
        self.assertEqual(0.5, native["metrics"]["recall"])

    def test_native_validation_preserves_first_errors_and_unsupported_profile_fallback(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        with patch.dict(os.environ, environment(base), clear=True):
            valid = copy.deepcopy(self.fixture)
            valid["records"][0].update(replaces=valid["records"][1]["id"], review_in_days=-365)
            valid["cases"][0].update(request="", target_summary="한글 🚀 é")
            self.path.write_text(json.dumps(valid), encoding="utf-8")
            with patch.object(evaluator, "_validate_fixture", side_effect=AssertionError("native validation missing")):
                self.assertEqual(valid, evaluator.load_fixture(self.path, native=True))

            def second_record_invalid(fixture):
                fixture["records"][0]["replaces"] = "ffffffffffffffff"
                fixture["records"][1]["id"] = "000000000000000A"

            def reference_before_case(fixture):
                fixture["records"][0]["replaces"] = fixture["records"][0]["id"]
                fixture["cases"][0]["target_paths"] = None

            changes = (
                lambda fixture: fixture.update(schema_version=True, description="\u00a0"),
                lambda fixture: fixture.update(schema_version=1.0),
                lambda fixture: fixture.update(description="\u00a0"),
                lambda fixture: fixture["records"][0].update(status=None),
                lambda fixture: fixture["records"][0].update(review_in_days=366),
                lambda fixture: fixture["records"][0].update(review_in_days=-365.0),
                second_record_invalid,
                reference_before_case,
                lambda fixture: fixture["cases"][0].update(request=None, target_paths=None),
                lambda fixture: fixture["cases"][0].update(target_paths=None),
                lambda fixture: fixture["cases"][0]["expected_relevant"].append(fixture["records"][0]["id"]),
            )
            for mutate in changes:
                fixture = copy.deepcopy(valid)
                mutate(fixture)
                self.path.write_text(json.dumps(fixture), encoding="utf-8")
                with self.subTest(mutation=mutate), self.assertRaises(ValueError) as python:
                    evaluator.load_fixture(self.path)
                with patch.object(evaluator, "_validate_fixture", side_effect=AssertionError("native validation missing")):
                    with self.assertRaises(ValueError) as native:
                        evaluator.load_fixture(self.path, native=True)
                self.assertEqual(str(python.exception), str(native.exception))

            self.path.write_text(json.dumps(valid), encoding="utf-8")
            with (patch.object(evaluator.unicodedata, "unidata_version", "unsupported"),
                  patch.object(evaluator, "_validate_fixture", wraps=evaluator._validate_fixture) as fallback):
                self.assertEqual(valid, evaluator.load_fixture(self.path, native=True))
                fallback.assert_called_once_with(valid)

    def test_native_metrics_count_raw_unicode_and_keep_empty_denominators(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        expected = "0000000000000001"
        rendered = "0000000000000002"
        raw = '{"id": "' + rendered + '", "text": "한국 🚀 é \\u0041"}'
        observations = [
            ({"id": "empty", "category": "retrieval", "expected_relevant": []}, [], [], []),
            ({"id": "listing", "category": "listing", "expected_relevant": [expected]},
             [expected, rendered], [rendered], [raw]),
        ]
        python = evaluator._python_metrics(observations)
        with patch.dict(os.environ, environment(base), clear=True):
            with patch.object(evaluator, "_python_metrics", side_effect=AssertionError("native metrics missing")):
                native = evaluator._native_metrics(iter(observations))
        self.assertEqual(python, native)
        self.assertEqual(len(raw), native["total_payload_characters"])
        self.assertEqual(0, native["metrics"]["payload_characters"])
        self.assertIsNone(native["metrics"]["precision"])
        self.assertIsNone(native["metrics"]["recall"])

    def test_native_loader_preserves_numeric_types_duplicate_order_and_python_file_errors(self):
        from native_launcher_support import NATIVE
        from native_pretool_support import environment, prepare

        if not NATIVE.is_file():
            self.skipTest("source-bound native fixture unavailable")
        base = Path(self.directory.name)
        prepare(base)
        fixture_json = json.dumps(self.fixture, ensure_ascii=False)
        raw = ('{\r\n"extra":{"first":1,"second":-0.0,"first":-0,'
               '"max":18446744073709551615,"float":1.0},\r' + fixture_json[1:]).encode()
        self.path.write_bytes(raw)
        expected = evaluator.load_fixture(self.path)
        with patch.dict(os.environ, environment(base), clear=True):
            with patch.object(type(self.path), "read_text", side_effect=AssertionError("Python read")):
                loaded = evaluator.load_fixture(self.path, native=True)
            self.assertEqual(json.dumps(expected), json.dumps(loaded))
            self.assertEqual(["first", "second", "max", "float"], list(loaded["extra"]))
            self.assertIs(int, type(loaded["extra"]["first"]))
            self.assertIs(float, type(loaded["extra"]["float"]))
            self.assertEqual(-1.0, math.copysign(1.0, loaded["extra"]["second"]))

            fallback_inputs = (
                raw.replace(b"18446744073709551615", b"18446744073709551616"),
                raw.replace(b"1.0", b"NaN"),
                raw + b" " * (512 * 1024),
            )
            read_text = type(self.path).read_text
            for data in fallback_inputs:
                self.path.write_bytes(data)
                expected = evaluator.load_fixture(self.path)
                with patch.object(type(self.path), "read_text", autospec=True, side_effect=read_text) as fallback:
                    loaded = evaluator.load_fixture(self.path, native=True)
                    fallback.assert_called_once_with(self.path, encoding="utf-8")
                self.assertEqual(json.dumps(expected), json.dumps(loaded))

            cases = ((b"{", json.JSONDecodeError), (b"\xff", UnicodeDecodeError),
                     (b"\xef\xbb\xbf" + raw, json.JSONDecodeError), (None, FileNotFoundError))
            for data, error in cases:
                if data is None:
                    self.path.unlink()
                else:
                    self.path.write_bytes(data)
                with self.subTest(error=error), self.assertRaises(error) as legacy:
                    evaluator.load_fixture(self.path)
                with self.assertRaises(error) as native:
                    evaluator.load_fixture(self.path, native=True)
                self.assertEqual(str(legacy.exception), str(native.exception))


if __name__ == "__main__":
    unittest.main()
