"""Exact analysis identity stays separate from freshness, budgets and authority."""
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import agent_project_memory as source
from native_pretool_support import environment, prepare
from support.native_memory_analysis import NativeMemoryAnalysis


class NativeMemoryAnalysisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-analysis-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def binding(self, question, context, backend="auto", native_required=False):
        with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":backend}, clear=True):
            if native_required:
                with patch.object(source, "_analysis_binding_reference", side_effect=AssertionError("Python binding replay")):
                    return source._analysis_binding(question, context)
            return source._analysis_binding(question, context)

    def binding_parity(self, question, context):
        try:
            expected = self.binding(question, context, "python")
        except ValueError as error:
            with self.assertRaises(ValueError) as actual:
                self.binding(question, context, native_required=True)
            self.assertEqual(error.args, actual.exception.args)
            return None
        actual = self.binding(question, context, native_required=True)
        self.assertEqual(expected, actual)
        if actual is not None:
            self.assertEqual(["question","context"], list(actual))
        return actual

    def record(self, id="a", scope="analysis", question="Can check raise?", context="Local only", **fields):
        return {"id":id,"scope":scope,"status":"active","body":"checked conclusion","source":"source",
                "digest":"b"*64,"analysis":{"question":question,"context":context,"inputs":"a"*64}, **fields}

    def candidates(self, records, binding=None, scope="analysis", backend="auto", native_required=False):
        binding = {"question":"Can check raise?","context":"Local only"} if binding is None else binding
        with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":backend}, clear=True):
            if native_required:
                with patch.object(source, "_analysis_candidates_reference", side_effect=AssertionError("Python filter replay")):
                    return source._analysis_candidates(scope, binding, records)
            return source._analysis_candidates(scope, binding, records)

    def candidate_parity(self, records, binding=None, scope="analysis"):
        expected = self.candidates(records, binding, scope, "python")
        actual = self.candidates(records, binding, scope, native_required=True)
        self.assertEqual(expected, actual)
        for a, b in zip(expected, actual):
            self.assertIs(a, b)
        return actual

    def test_binding_empty_and_edge_spaces_preserve_text_identity(self):
        self.assertIsNone(self.binding_parity("", ""))
        for question, context in ((" Can check raise? ", " Local only "), ("Straße Σς", "한글 é é 😀"),
                                  ("Can CHECK not raise?", "  Internal  spaces  stay  ")):
            self.binding_parity(question, context)

    def test_original_length_boundaries_count_unicode_characters_before_trimming(self):
        for value in ("x"*300, "😀"*300, "x"*301, "😀"*301, " "*300+"x", "x"+" "*300):
            self.binding_parity(value, "context")
            self.binding_parity("question", value)

    def test_nonprintable_edges_are_not_normalized_away(self):
        for value in ("", " ", "\tq", "q\n", "\x1cq", "q\x00", "q\x7f", "\u00a0q", "q\u2028"):
            self.binding_parity(value, "context")
            self.binding_parity("question", value)

    def test_seeded_unicode_binding_corpus_matches_original(self):
        rng = random.Random(261111)
        alphabet = list(" aB0가한글😀éΣς") + ["\t", "\n", "\u0301", "\u00a0", "\x1c"]
        for _ in range(35):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(12)))
            self.binding_parity(value, "fixed context")

    def test_nonordinary_binding_inputs_keep_original_falsey_and_error_behavior(self):
        class Custom(str):
            def strip(self):
                raise RuntimeError("custom strip")
        for question, context in ((None, None), (False, 0), ([], {}), (1, "context"), ("q", []), (Custom("q"), "c")):
            with patch("support.native_memory_analysis.NativeProbe.request", side_effect=AssertionError("transport")):
                try:
                    expected = self.binding(question, context, "python")
                except Exception as error:
                    with self.assertRaises(type(error)) as actual:
                        self.binding(question, context)
                    self.assertEqual(error.args, actual.exception.args)
                else:
                    self.assertEqual(expected, self.binding(question, context))

    def test_candidates_require_exact_scope_case_negation_context_and_spacing(self):
        records = [self.record("exact"), self.record("all", scope="all"),
                   self.record("case", question="Can CHECK raise?"), self.record("not", question="Can check not raise?"),
                   self.record("spacing", question="Can  check raise?"), self.record("context", context="production"),
                   {"scope":"analysis"}, self.record("null", question=None)]
        self.assertEqual([records[0]], self.candidate_parity(records))
        self.assertEqual([], self.candidate_parity([]))
        self.assertEqual([], self.candidate_parity(records, scope="review"))

    def test_duplicate_records_and_unserialized_metadata_keep_original_objects(self):
        marker = object()
        record = self.record(created_at=marker, unused="\ud800", extra=2**100)
        records = [record, record, self.record("b")]
        self.assertEqual(3, len(self.candidate_parity(records)))
        self.assertIs(marker, self.candidate_parity(records)[0]["created_at"])

    def test_binding_and_candidate_wiring_have_negative_controls(self):
        self.binding("q", "c", native_required=True)
        self.candidates([self.record()], native_required=True)
        with patch.object(NativeMemoryAnalysis, "binding", return_value=None):
            with self.assertRaisesRegex(AssertionError, "Python binding replay"):
                self.binding("q", "c", native_required=True)
        with patch.object(NativeMemoryAnalysis, "candidates", return_value=None):
            with self.assertRaisesRegex(AssertionError, "Python filter replay"):
                self.candidates([self.record()], native_required=True)

    def test_original_binding_and_recall_baseline_values_and_order(self):
        self.assertEqual({"question":"Q","context":"C"}, self.binding(" Q ", " C ", native_required=True))
        records = [{"id":name,"scope":scope,"body":name,"source":"checked","digest":"d"*64,
                    "analysis":{"question":question,"context":"C","inputs":"a"*64}}
                   for name,scope,question in (("A","analysis","Q"),("B","all","Q"),
                                               ("C","analysis","q"),("D","analysis","Q"))]
        # Captured from _analysis_recall before extracting its candidate filter.
        expected = [{"id":name,"digest":"d"*64,"body":name,"source":"checked","analysis_status":"candidate_only"}
                    for name in ("A","D")]
        with patch.dict(os.environ, self.env, clear=True), patch.object(source,"_recall",return_value=records), \
             patch.object(source.EvidenceInputs,"capture",return_value="a"*64), \
             patch.object(source,"_source_status",return_value={"source_status":"unchanged"}), \
             patch.object(source,"_analysis_binding_reference",side_effect=AssertionError("binding replay")), \
             patch.object(source,"_analysis_candidates_reference",side_effect=AssertionError("filter replay")):
            actual = source._analysis_recall(self.project,"analysis"," Q "," C ")
        self.assertEqual(expected, actual)
        self.assertEqual([list(row) for row in expected], [list(row) for row in actual])

    def test_custom_binding_keys_defer_before_lookups_or_transport(self):
        class CustomKey:
            def __hash__(self):
                return hash("question")

            def __eq__(self, other):
                raise AssertionError("custom binding key")

        binding = {CustomKey():"q", "context":"c"}
        records = [self.record()]
        with patch("support.native_memory_analysis.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertIsNone(NativeMemoryAnalysis.candidates("analysis", binding, records))
        for backend in ("python", "auto"):
            with self.assertRaisesRegex(AssertionError, "custom binding key"):
                self.candidates(records, binding=binding, backend=backend)

    def test_absent_binding_and_empty_candidates_need_no_transport(self):
        with patch("support.native_memory_analysis.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual({"binding":None}, NativeMemoryAnalysis.binding("", ""))
            self.assertEqual([], NativeMemoryAnalysis.candidates("analysis", {"question":"q","context":"c"}, []))
            self.assertIsNone(source._analysis_binding("", ""))
            self.assertEqual([], source._analysis_candidates("analysis", {}, []))

    def test_invalid_binding_stops_before_recall_and_nonmatches_do_not_hash_inputs(self):
        with patch("support.native_memory_analysis.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertIsNone(source._analysis_binding("", ""))
            self.assertEqual([], source._analysis_candidates("analysis", {}, []))
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_recall", side_effect=AssertionError("recall")):
            with self.assertRaisesRegex(ValueError, "analysis question and context"):
                source._analysis_recall(self.project, "analysis", "q\n", "c")
            with self.assertRaisesRegex(ValueError, "requires a question and context"):
                source._analysis_recall(self.project, "analysis", "", "")
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_recall", return_value=[self.record(question="other")]), \
             patch.object(source.EvidenceInputs, "capture", side_effect=AssertionError("snapshot")):
            self.assertEqual([], source._analysis_recall(self.project, "analysis", "Can check raise?", "Local only"))

    def test_freshness_and_result_budgets_remain_after_exact_candidate_selection(self):
        records = [self.record(str(i), body="x"*500) for i in range(7)]
        records[0]["analysis"]["inputs"] = "c"*64
        def lookup(backend):
            with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":backend}, clear=True), \
                 patch.object(source, "_recall", return_value=records), \
                 patch.object(source.EvidenceInputs, "capture", return_value="a"*64), \
                 patch.object(source, "_source_status", return_value={"source_status":"unchanged"}):
                return source._analysis_recall(self.project, "analysis", "Can check raise?", "Local only")
        expected, actual = lookup("python"), lookup("auto")
        self.assertEqual(expected, actual)
        self.assertNotIn("0", [r["id"] for r in actual])
        self.assertLessEqual(len(actual), source.MAX_RECALL_ITEMS)
        self.assertLessEqual(len(json.dumps(actual, ensure_ascii=False)), source.MAX_RECALL_CHARS)

    def test_malformed_candidate_values_keep_original_errors_and_short_circuit(self):
        for records in ([{}], [self.record(analysis=None)], [self.record(analysis=[])],
                        [self.record(scope="foreign", analysis=object())]):
            try:
                expected = self.candidates(records, backend="python")
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.candidates(records)
                self.assertEqual(error.args, actual.exception.args)
            else:
                self.assertEqual(expected, self.candidates(records))

    def test_malformed_responses_and_optional_transport_failures_defer(self):
        for result in (None, {}, {"invalid":False}, {"invalid":1}, {"binding":{}}, {"binding":None},
                       {"binding":{"question":"","context":"c"}},
                       {"binding":{"question":"q","context":1}}, {"binding":None,"extra":1}):
            with patch("support.native_memory_analysis.NativeProbe.request", return_value=result):
                self.assertIsNone(NativeMemoryAnalysis.binding("q", "c"))
        records = [self.record(), self.record("b")]
        for result in ({}, {"indices":[True]}, {"indices":[-1]}, {"indices":[2]},
                       {"indices":[1,0]}, {"indices":[0,0]}, {"indices":[],"extra":1}):
            with patch("support.native_memory_analysis.NativeProbe.request", return_value=result):
                self.assertIsNone(NativeMemoryAnalysis.candidates("analysis", {"question":"q","context":"c"}, records))
        for error in (OSError("transport"), ValueError("transport"), RuntimeError("transport")):
            with patch("support.native_memory_analysis.NativeProbe.request", side_effect=error):
                self.assertIsNone(NativeMemoryAnalysis.binding("q", "c"))

    def test_real_store_cli_reuses_only_exact_and_fresh_analysis_without_python_filtering(self):
        tools = self.base / "tools"
        tools.mkdir()
        (tools/"git").symlink_to(shutil.which("git"))
        env = {**self.env,"PATH":str(tools)}
        target = self.project / "a.py"
        target.write_text("original\n")
        for args in (("add", "a.py"), ("-c","user.name=Test","-c","user.email=test@example.invalid","commit","-qm","fixture")):
            subprocess.run(["git","-C",str(self.project),*args], env=env, check=True, capture_output=True, timeout=5)
        directory = self.base / "records"
        directory.mkdir()
        with patch.dict(os.environ, env, clear=True):
            inputs = source.EvidenceInputs.capture(self.project.resolve(), [])
            blob = source._source_blob(self.project, "a.py")
        record = self.record("a"*16, schema_version=1, review_on="2099-01-01",
                             source_files=[{"path":"a.py","blob":blob}])
        record["analysis"]["inputs"] = inputs
        record["digest"] = source._digest(record)
        path = directory / (record["id"]+".json")
        path.write_text(json.dumps(record), encoding="utf-8")
        before = path.read_bytes()
        with patch.dict(os.environ, {**env,"MORU_LAUNCHER_BACKEND":"python"}, clear=True):
            self.assertIsNotNone(source.read_record(path), "CLI fixture must satisfy the original record schema")
        with patch.dict(os.environ, env, clear=True), patch.object(source,"store_dir",return_value=directory), \
             patch.object(source,"_analysis_binding_reference",side_effect=AssertionError("Python binding replay")), \
             patch.object(source,"_analysis_candidates_reference",side_effect=AssertionError("Python filter replay")):
            def query(question="Can check raise?", context="Local only"):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, source._main(["--project",str(self.project),"recall","--scope","analysis",
                        "--analysis-question",question,"--analysis-context",context]))
                return json.loads(output.getvalue())
            self.assertEqual([record["id"]], [r["id"] for r in query(" Can check raise? ")])
            self.assertEqual([], query("Can CHECK raise?"))
            target.write_text("changed\n")
            self.assertEqual([], query())
        self.assertEqual(before, path.read_bytes())
