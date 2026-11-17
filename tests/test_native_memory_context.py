"""Native recall projection/budget against the unmodified rendering contract."""
from datetime import date
import functools
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory as source
from native_pretool_support import environment
from native_launcher_support import install
from support.native_memory_context import NativeMemoryContext
from support.native_memory_status import NativeMemoryStatus
from support.native_probe_transport import NativeProbe


def row(name="a", **values):
    return {"id":name, "status":"active", "scope":"task", "body":"한글 body",
            "source":"checked", "review_on":"9999-12-31", **values}


class NativeMemoryContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-context-")
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        home = cls.base / "home"
        home.mkdir()
        cls.project = cls.base / "project space 한글"
        cls.project.mkdir()
        with patch.dict(os.environ,environment(cls.base),clear=True):
            install(home)
        cls.entry = home / ".moru/bin/moru-hook"
        if not cls.entry.with_name("moru-hook-native").is_file():
            raise AssertionError("source-matching debug fixture missing")
        if (cls.project / ".git").exists():
            raise AssertionError("pure context fixture unexpectedly has Git state")
        empty = cls.base / "empty"
        empty.mkdir()
        cls.env = {**environment(cls.base), "PATH":str(empty)}

    def reference(self, rows, **kwargs):
        with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":"python"}, clear=True):
            return source._recall_lines_reference(self.project,"task",records=rows,**kwargs)

    def actual(self, rows, **kwargs):
        with patch.dict(os.environ,self.env,clear=True):
            return source.recall_lines(self.project,"task",records=rows,**kwargs)

    def test_native_selection_projection_budget_use_one_request_without_python_replay(self):
        rows = [row("a", body="first"), row("b", body="second", applies_when="when", not_when="unless")]
        expected = self.reference(rows)
        codes = {getattr(source,name).__code__:name for name in ("_recall","_previously","_source_status")}
        calls = []
        def observe(frame,event,value):
            if event == "call" and frame.f_code in codes:
                calls.append(codes[frame.f_code])
        previous = sys.getprofile()
        with patch.object(source,"_recall_lines_reference",side_effect=AssertionError("Python replay")), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            try:
                sys.setprofile(observe)
                actual = self.actual(rows)
            finally:
                sys.setprofile(previous)
        self.assertEqual(expected,actual)
        self.assertEqual([],calls)
        self.assertEqual(1,requested.call_count)
        self.assertEqual("recall-context",requested.call_args.args[1])

    def test_unicode_json_spacing_escape_and_exact_character_budget_match_reference(self):
        texts = ["한글😀", "quotes\" slash\\\n\t", "\u007f\u0085\u2028", "é e\u0301", "", "\0"]
        for text in texts:
            rows = [row("a",body="x"*2000),row("b",body=text),row("c",body=text)]
            fields = {k:rows[1][k] for k in ("id","body","source","review_on")}
            size = len(json.dumps(fields,ensure_ascii=False))
            for budget in (size-1,size,2*size):
                with self.subTest(text=repr(text),budget=budget), patch.object(source,"MAX_RECALL_CHARS",budget):
                    expected = self.reference(rows)
                    with patch.object(source,"_recall_lines_reference",side_effect=AssertionError("Python replay")):
                        self.assertEqual(expected,self.actual(rows))

    def test_previous_body_uses_last_duplicate_and_unicode_scalar_truncation(self):
        rows = [row("old",body="first",status="retired"),
                row("old",body="😀😀😀😀",status="retired"),row("new",replaces="old")]
        for limit in (1,3,160):
            with patch.object(source,"MAX_PREVIOUS_CHARS",limit):
                expected = self.reference(rows)
                with patch.object(source,"_recall_lines_reference",side_effect=AssertionError("Python replay")):
                    self.assertEqual(expected,self.actual(rows))
        rows = [row("",body="empty predecessor",status="retired"),row("new",applies_when="")]
        self.assertEqual(self.reference(rows),self.actual(rows))

    def test_seeded_status_scope_replacement_order_and_context_match(self):
        rng = random.Random(61115)
        for _ in range(8):
            rows = [row(str(i%7),body=rng.choice(["프로필에서는", "src/queue.py", "unrelated", ""]),
                status=rng.choice(["active","pending","approved","retired"]),
                scope=rng.choice(["all","task","review"]),replaces=rng.choice([None,"old",""]),
                review_on=rng.choice(["0001-01-01","9999-12-31"])) for i in range(24)]
            for kwargs in ({},{"request":"프로필"},{"target_paths":(Path("src/queue.py"),)}):
                expected = self.reference(rows,**kwargs)
                with patch.object(source,"_recall_lines_reference",side_effect=AssertionError("Python replay")):
                    self.assertEqual(expected,self.actual(rows,**kwargs))

    def test_declined_or_malformed_packet_uses_reference_without_second_ranking_request(self):
        rows = [row("a"),row("b")]
        expected = self.reference(rows)
        for packet in (None,{}, {"items":None}, {"items":[{}]},
                       {"items":[{"id":"unknown","body":"x","source":"y","review_on":"2099-01-01"}]},
                       {"items":[{"id":"a","body":True,"source":"y","review_on":"2099-01-01"}]}):
            with self.subTest(packet=packet), patch.object(NativeProbe,"request",return_value=packet) as requested:
                self.assertEqual(expected,self.actual(rows))
                self.assertEqual(1,requested.call_count)
                self.assertEqual("recall-context",requested.call_args.args[1])

    def test_source_backed_records_keep_existing_ranking_cache_and_warning_order(self):
        files = [{"path":"a","blob":"old"},{"path":"b","blob":"old"},{"path":"a","blob":"new"}]
        rows = [row("a",source_files=files),row("b",source_files=files)]
        with patch.object(NativeMemoryStatus,"evaluate",return_value=None), \
             patch.object(source,"_source_blob",side_effect=lambda project,path: "new" if path=="a" else "") as blob:
            expected = self.reference(rows)
            blob.reset_mock()
            with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
                self.assertEqual(expected,self.actual(rows))
                self.assertEqual(["recall"],[c.args[1] for c in requested.call_args_list])
            self.assertEqual(2,blob.call_count)
        self.assertEqual(["a","b"],json.loads(expected[1][2:])["unverified_sources"])

    def test_fully_cached_sources_never_start_a_process_and_preserve_duplicate_statuses(self):
        files = [{"path":"a","blob":"old"},{"path":"b","blob":"old"},{"path":"a","blob":"old"}]
        with patch.object(NativeProbe,"request",side_effect=AssertionError("cached RPC")), \
             patch.object(source,"_source_blob",side_effect=AssertionError("cached hash")):
            actual = source._source_status(self.project,{"source_files":files},{"a":"new","b":""})
        self.assertEqual("changed",actual["source_status"])
        self.assertEqual(["a","b","a"],actual["unverified_sources"])

    def test_source_backed_oversize_is_skipped_before_any_hashing(self):
        rows = [row("a",body="x"*2000,source_files=[{"path":"never","blob":"old"}]),row("b")]
        with patch.object(source,"_source_blob",side_effect=AssertionError("oversize hash")), \
             patch.object(NativeMemoryStatus,"evaluate",side_effect=AssertionError("oversize status")):
            self.assertEqual(self.reference(rows),self.actual(rows))

    def test_custom_projection_json_and_in_place_code_bindings_keep_original_callbacks(self):
        rows = [row("a")]
        with patch.object(source,"_previously",return_value={"previously":"custom"}), \
             patch.object(NativeMemoryContext,"render",side_effect=AssertionError("custom bypass")):
            self.assertEqual(self.reference(rows),self.actual(rows))
        original = source.json.dumps
        with patch.object(source.json,"dumps",wraps=original), \
             patch.object(NativeMemoryContext,"render",side_effect=AssertionError("encoder bypass")):
            self.assertEqual(self.reference(rows),self.actual(rows))
        original_code = source._recall.__code__
        def altered(*args,**kwargs):
            return []
        try:
            source._recall.__code__ = altered.__code__
            with patch.object(NativeMemoryContext,"render",side_effect=AssertionError("code bypass")):
                self.assertEqual(self.reference(rows),self.actual(rows))
        finally:
            source._recall.__code__ = original_code

    def test_encoder_method_separator_and_keyword_default_overrides_keep_reference(self):
        rows = [row("a"),row("b")]
        original_encode = source.json.JSONEncoder.encode
        def compact(encoder,value):
            return original_encode(encoder,value).replace(", ",",")
        for name,value in (("encode",compact),("item_separator",",")):
            with patch.object(source.json.JSONEncoder,name,value), \
                 patch.object(NativeMemoryContext,"render",side_effect=AssertionError("encoder bypass")):
                self.assertEqual(self.reference(rows),self.actual(rows))
        keywords = dict(source.json.dumps.__kwdefaults__)
        try:
            source.json.dumps.__kwdefaults__["separators"] = (",",":")
            with patch.object(NativeMemoryContext,"render",side_effect=AssertionError("defaults bypass")):
                self.assertEqual(self.reference(rows),self.actual(rows))
        finally:
            source.json.dumps.__kwdefaults__.clear()
            source.json.dumps.__kwdefaults__.update(keywords)

    def test_preimport_wrapped_json_binding_loads_and_keeps_reference(self):
        original = source.json.dumps
        with patch.object(source.json,"dumps",functools.partial(original,sort_keys=True)):
            spec = importlib.util.spec_from_file_location("memory_context_custom_json",source.__file__)
            custom = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(custom)
            rows = [row("a")]
            with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
                expected = custom._recall_lines_reference(self.project,"task",records=rows)
            with patch.dict(os.environ,self.env,clear=True), \
                 patch.object(NativeMemoryContext,"render",side_effect=AssertionError("preimport bypass")):
                self.assertEqual(expected,custom.recall_lines(self.project,"task",records=rows))

    def test_opaque_metadata_malformed_records_and_surrogates_keep_reference_values_or_errors(self):
        cases = ([row("a",opaque=object())],[row("a",body="A\ud800B")],[{}],
                 [row("a",review_on="invalid")],[row("a",not_when=[])])
        for rows in cases:
            try:
                expected = self.reference(rows)
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.actual(rows)
                self.assertEqual(error.args,actual.exception.args)
            else:
                self.assertEqual(expected,self.actual(rows))
        with patch.dict(os.environ,self.env,clear=True):
            with self.assertRaises(KeyError):
                source.recall_lines(self.project,"!",records=[{}])

    def test_empty_zero_and_unsupported_budgets_preserve_reference_behavior(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            self.assertEqual([],self.actual([]))
        rows = [row("a",replaces="old"),row("old",status="retired")]
        for name,value in (("MAX_RECALL_ITEMS",0),("MAX_RECALL_CHARS",0),
                           ("MAX_RECALL_CHARS",-1),("MAX_PREVIOUS_CHARS",0)):
            with patch.object(source,name,value):
                self.assertEqual(self.reference(rows),self.actual(rows))

    def test_native_wiring_negative_control_detects_python_replay(self):
        rows = [row("a")]
        expected = self.reference(rows)
        with patch.object(source,"_recall_lines_reference",side_effect=AssertionError("Python replay")):
            self.assertEqual(expected,self.actual(rows))
            with patch.object(NativeMemoryContext,"render",return_value=(None,True)):
                with self.assertRaisesRegex(AssertionError,"Python replay"):
                    self.actual(rows)
