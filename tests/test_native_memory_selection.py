"""Fused analysis selection against the existing two-stage public caller."""
from datetime import date
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory as source
from native_launcher_support import install
from native_pretool_support import environment
from support.native_memory import NativeMemory
from support.native_memory_analysis import NativeMemoryAnalysis
from support.native_probe_transport import NativeProbe


def row(name="a", **values):
    return {"id":name,"status":"active","scope":"analysis","body":"한글 conclusion",
        "source":"checked","review_on":"9999-12-31","digest":"d"*64,
        "analysis":{"question":"Q","context":"C","inputs":"current"}, **values}


class NativeMemorySelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-selection-")
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        home = cls.base / "home"; home.mkdir()
        cls.project = cls.base / "project space 한글"; cls.project.mkdir()
        with patch.dict(os.environ,environment(cls.base),clear=True):
            install(home)
        cls.entry = home / ".moru/bin/moru-hook"
        if not cls.entry.with_name("moru-hook-native").is_file():
            raise AssertionError("source-matching debug fixture missing")
        empty = cls.base / "empty"; empty.mkdir()
        cls.env = {**environment(cls.base),"PATH":str(empty)}

    def reference(self, rows, scope="analysis", binding=None):
        binding = {"question":"Q","context":"C"} if binding is None else binding
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True), \
             patch.object(source,"scan_records",return_value=(rows,0)):
            return source._analysis_candidates(scope,binding,source._recall(self.project,scope))

    def actual(self, rows, scope="analysis", binding=None):
        binding = {"question":"Q","context":"C"} if binding is None else binding
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"scan_records",return_value=(rows,0)):
            return source._analysis_selection(self.project,scope,binding)

    def observe(self, action):
        codes = {getattr(source,n).__code__:n for n in
            ("_recall","_recall_reference","_analysis_candidates","_analysis_candidates_reference")}
        calls = []
        def capture(frame,event,value):
            if event == "call" and frame.f_code in codes:
                calls.append(codes[frame.f_code])
        previous = sys.getprofile()
        try:
            sys.setprofile(capture)
            result = action()
        finally:
            sys.setprofile(previous)
        return result,calls

    def test_real_fusion_uses_one_request_no_python_replay_and_original_objects(self):
        rows = [row("z"),row("a"),row("b")]
        expected = self.reference(rows)
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            actual,calls = self.observe(lambda:self.actual(rows))
        self.assertEqual(expected,actual)
        self.assertEqual(["a","b","z"],[r["id"] for r in actual])
        for old,new in zip(expected,actual):
            self.assertIs(old,new)
        self.assertEqual([],calls)
        self.assertEqual(1,requested.call_count)
        self.assertEqual("analysis-recall",requested.call_args.args[1])

    def test_observer_negative_control_detects_disabled_native_selection(self):
        rows = [row("a")]
        expected = self.reference(rows)
        actual,calls = self.observe(lambda:self.actual(rows))
        self.assertEqual((expected,[]),(actual,calls))
        with patch.object(NativeMemoryAnalysis,"shortlist",return_value=(None,True)):
            actual,calls = self.observe(lambda:self.actual(rows))
        self.assertEqual(expected,actual)
        self.assertIn("_recall_reference",calls)
        self.assertIn("_analysis_candidates_reference",calls)

    def test_duplicate_ids_and_exact_scope_case_context_preserve_ranked_index_order(self):
        rows = [row("b"),row("a"),row("a"),row("all",scope="all"),
            row("case",analysis={"question":"q","context":"C"}),
            row("context",analysis={"question":"Q","context":"c"}),row("retired",status="retired")]
        expected = self.reference(rows)
        actual = self.actual(rows)
        self.assertEqual(expected,actual)
        self.assertEqual([rows[1],rows[2],rows[0]],actual)
        self.assertIs(rows[1],actual[0]); self.assertIs(rows[2],actual[1])

    def test_seeded_eligibility_replacement_dates_and_scopes_match_reference(self):
        rng = random.Random(71116)
        for _ in range(12):
            rows = [row(str(i%9),status=rng.choice(["active","pending","approved","retired"]),
                scope=rng.choice(["analysis","all","task"]),
                replaces=rng.choice([None,"old",""]),review_on=rng.choice(["0001-01-01","9999-12-31"]),
                analysis={"question":rng.choice(["Q","q",None]),"context":"C"}) for i in range(24)]
            self.assertEqual(self.reference(rows),self.actual(rows))

    def test_decline_and_malformed_packets_use_one_attempt_then_pure_reference(self):
        rows = [row("a"),row("b")]
        expected = self.reference(rows)
        for result in (None,{}, {"indices":True},{"indices":[True]},{"indices":[-1]},
                       {"indices":[2]},{"indices":[0,0]},{"indices":[],"extra":1}):
            with self.subTest(result=result), patch.object(NativeProbe,"request",return_value=result) as requested:
                self.assertEqual(expected,self.actual(rows))
                self.assertEqual(1,requested.call_count)
                self.assertEqual("analysis-recall",requested.call_args.args[1])

    def test_custom_python_and_native_callbacks_retain_legacy_dispatch(self):
        rows = [row("a")]
        with patch.object(source,"_recall",return_value=rows), \
             patch.object(NativeMemoryAnalysis,"shortlist",side_effect=AssertionError("fused custom callback")):
            self.assertEqual(self.reference(rows),self.actual(rows))
        for target,name,result in ((NativeMemory,"recall",rows),(NativeMemoryAnalysis,"candidates",[])):
            with patch.object(target,name,return_value=result):
                self.assertEqual(self.reference(rows),self.actual(rows))
        original = source._analysis_candidates.__code__
        def custom(*args,**kwargs):
            return []
        try:
            source._analysis_candidates.__code__ = custom.__code__
            with patch.object(NativeMemoryAnalysis,"shortlist",side_effect=AssertionError("code bypass")):
                self.assertEqual([],self.actual(rows))
        finally:
            source._analysis_candidates.__code__ = original

    def test_opaque_values_and_malformed_metadata_keep_identity_values_or_errors(self):
        marker = object()
        for rows in ([row("a",unused=marker)],[row("a",body="A\ud800B")],
                     [row("a",analysis=None)],[row("a",analysis={"question":[],"context":"C"})],
                     [row("a",review_on="invalid")],[{}]):
            try:
                expected = self.reference(rows)
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.actual(rows)
                self.assertEqual(error.args,actual.exception.args)
            else:
                self.assertEqual(expected,self.actual(rows))
                for a,b in zip(expected,self.actual(rows)):
                    self.assertIs(a,b)

    def test_empty_selection_and_invalid_scope_do_not_scan_or_start_extra_requests(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            self.assertEqual([],self.actual([]))
        with patch.object(source,"scan_records",side_effect=AssertionError("invalid scope scan")):
            with self.assertRaisesRegex(ValueError,"invalid recall scope"):
                source._analysis_selection(self.project,"!",{"question":"Q","context":"C"})

    def test_no_matching_candidates_never_capture_workspace_inputs(self):
        rows = [row("other",analysis={"question":"not Q","context":"C"})]
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"scan_records",return_value=(rows,0)), \
             patch.object(source.EvidenceInputs,"capture",side_effect=AssertionError("unneeded capture")), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            self.assertEqual([],source._analysis_recall(self.project,"analysis","Q","C"))
        self.assertEqual(["analysis-binding","analysis-recall"],[c.args[1] for c in requested.call_args_list])

    def test_unavailable_fusion_skips_record_preparation(self):
        with patch.object(NativeProbe,"available",return_value=False), \
             patch.object(NativeMemory,"_ordinary",side_effect=AssertionError("unavailable preparation")):
            self.assertEqual((None,False),NativeMemoryAnalysis.shortlist(
                "analysis",date.today(),[row()],{"question":"Q","context":"C"}))

    def test_freshness_source_checks_and_budget_order_are_unchanged(self):
        rows = [row("a",analysis={"question":"Q","context":"C","inputs":"old"}),
                row("b",body="x"*2000),row("c"),row("d")]
        def run(backend):
            events = []
            def status(project,record,blobs):
                events.append(record["id"])
                return {"source_status":"unchanged"}
            with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True), \
                 patch.object(source,"scan_records",return_value=(rows,0)), \
                 patch.object(source.EvidenceInputs,"capture",return_value="current") as capture, \
                 patch.object(source,"_source_status",side_effect=status):
                result = source._analysis_recall(self.project,"analysis","Q","C")
            self.assertEqual(1,capture.call_count)
            return result,events
        expected = run("python")
        self.assertEqual(expected,run("auto"))
        self.assertEqual(["b","c","d"],expected[1])
        self.assertEqual(["c","d"],[r["id"] for r in expected[0]])


if __name__ == "__main__":
    unittest.main()
