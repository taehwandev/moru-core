"""Raw grouping must replace normalization, not only call a native pair loop."""
import os
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import random
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory_consolidate as source
import agent_project_memory as memory
from native_launcher_support import install
from native_pretool_support import environment
from support.native_memory_consolidation import NativeMemoryConsolidation
from support.native_probe_transport import NativeProbe


def row(name, body="a b c d", scope="task", origin="Docs!", **extra):
    return {"id":name,"body":body,"scope":scope,"source":origin,"status":"active",
            "review_on":"2099-01-01",**extra}


class NativeMemoryGroupTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary=tempfile.TemporaryDirectory(prefix="native-memory-group-text-")
        cls.addClassCleanup(temporary.cleanup)
        cls.base=Path(temporary.name).resolve()
        home=cls.base/"home";home.mkdir()
        cls.project=cls.base/"project space 한글";cls.project.mkdir()
        with patch.dict(os.environ,environment(cls.base),clear=True):
            install(home)
        cls.entry=home/".moru/bin/moru-hook"
        if not cls.entry.with_name("moru-hook-native").is_file():
            raise AssertionError("source-matching debug fixture missing")
        empty=cls.base/"empty";empty.mkdir()
        cls.env={**environment(cls.base),"PATH":str(empty)}

    def call(self, rows, mode="duplicate", backend="auto", legacy=False):
        name="_duplicate_groups" if mode=="duplicate" else "_shared_source_groups"
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            if legacy:
                with patch.object(source,"_raw_grouping",return_value=(None,False)):
                    return getattr(source,name)(rows)
            return getattr(source,name)(rows)

    def observe(self, action):
        codes={getattr(source,n).__code__:n for n in
            ("normalize","_tokens","_jaccard","_scopes_overlap",
             "_duplicate_groups_reference","_shared_source_groups_reference")}
        calls=[]
        def trace(frame,event,value):
            if event=="call" and frame.f_code in codes:
                calls.append(codes[frame.f_code])
        previous=sys.getprofile()
        try:
            sys.setprofile(trace)
            result=action()
        finally:
            sys.setprofile(previous)
        return result,calls

    def test_real_raw_operations_use_one_request_without_python_normalization(self):
        for mode,operation in (("duplicate","duplicate-text-groups"),("source","shared-source-text-groups")):
            rows=[row("b"),row("a")]
            expected=self.call(rows,mode,"python")
            with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
                actual,calls=self.observe(lambda:self.call(rows,mode))
            self.assertEqual(expected,actual)
            self.assertEqual([],calls)
            self.assertEqual(1,requested.call_count)
            self.assertEqual(operation,requested.call_args.args[1])

    def test_negative_control_detects_python_normalization_when_raw_path_is_disabled(self):
        rows=[row("a"),row("b")]
        expected=self.call(rows,backend="python")
        with patch.object(NativeMemoryConsolidation,"raw_groups",return_value=(None,True)):
            actual,calls=self.observe(lambda:self.call(rows))
        self.assertEqual(expected,actual)
        self.assertIn("normalize",calls)
        self.assertIn("_duplicate_groups_reference",calls)

    def test_unicode_lower_punctuation_control_spaces_and_empty_sources_match(self):
        for left,right in (("ΟΣ!","ος"),("ABC_DEF, 한글\u00a0é","abc_def 한글 é"),
                           ("Straße","STRASSE"),("é","é"),("İ","i"),("!!!","???"),("\x1ca\tb","a b")):
            rows=[row("b",left,origin=left),row("a",right,origin=right)]
            for mode in ("duplicate","source"):
                self.assertEqual(self.call(rows,mode,"python"),self.call(rows,mode))

    def test_seeded_unsorted_scope_bridges_and_duplicate_ids_match(self):
        rng=random.Random(71117)
        for _ in range(12):
            rows=[row(str(rng.randrange(5))," ".join(rng.sample(list("abcdef"),rng.randrange(7))),
                rng.choice(["task","review","all"]),rng.choice(["Ος!","ος","B!","b",""])) for _ in range(10)]
            for mode in ("duplicate","source"):
                self.assertEqual(self.call(rows,mode,"python"),self.call(rows,mode))

    def test_original_objects_and_opaque_unused_applicability_values_survive(self):
        marker=object()
        rows=[row("x",applies_when=marker,unused=object()),row("x",not_when=marker)]
        with patch.dict(os.environ,self.env,clear=True):
            groups,attempted=NativeMemoryConsolidation.raw_groups("duplicate-groups",rows)
        self.assertTrue(attempted)
        self.assertIs(rows[0],groups[0][0]);self.assertIs(rows[1],groups[0][1])
        result=self.call(rows)
        self.assertIs(marker,result[0]["records"][0]["applies_when"])
        self.assertIs(marker,result[0]["records"][1]["not_when"])

    def test_custom_normalization_token_callbacks_and_regex_keep_legacy_behavior(self):
        rows=[row("a","A!"),row("b","A?")]
        for name,value in (("normalize",lambda text:"custom"),("_tokens",lambda text:frozenset({"custom"})),
                           ("_PUNCTUATION_RE",re.compile(r"$^"))):
            with patch.object(source,name,value), \
                 patch.object(NativeMemoryConsolidation,"raw_groups",side_effect=AssertionError("custom raw")):
                self.assertEqual(self.call(rows,legacy=True),self.call(rows))
        old_code=source.normalize.__code__
        def altered(text):
            return "custom"
        try:
            source.normalize.__code__=altered.__code__
            self.assertEqual(self.call(rows,legacy=True),self.call(rows))
        finally:
            source.normalize.__code__=old_code
        with patch.object(NativeMemoryConsolidation,"groups",return_value=None):
            self.assertEqual(self.call(rows,legacy=True),self.call(rows))

    def test_malformed_packets_fall_back_after_one_attempt_without_extra_ipc(self):
        rows=[row("a"),row("b")]
        expected=self.call(rows,backend="python")
        for result in (None,{}, {"groups":None},{"groups":[[True,1]]},{"groups":[[1,0]]},
                       {"groups":[[0]]},{"groups":[[0,2]]},{"groups":[[0,1],[0,1]]}):
            with self.subTest(result=result), patch.object(NativeProbe,"request",return_value=result) as requested:
                self.assertEqual(expected,self.call(rows))
                self.assertEqual(1,requested.call_count)
                self.assertEqual("duplicate-text-groups",requested.call_args.args[1])

    def test_missing_callback_bindings_keep_legacy_values_and_error_order(self):
        for name in ("normalize","_tokens","_PUNCTUATION_RE","_duplicate_groups_reference","_shared_source_groups_reference"):
            original=getattr(source,name)
            delattr(source,name)
            try:
                for rows in ([],[row("a"),row("b")]):
                    for mode in ("duplicate","source"):
                        try:
                            expected=self.call(rows,mode,legacy=True)
                        except Exception as error:
                            with self.assertRaises(type(error)) as actual:
                                self.call(rows,mode)
                            self.assertEqual(error.args,actual.exception.args)
                        else:
                            self.assertEqual(expected,self.call(rows,mode))
            finally:
                setattr(source,name,original)

    def test_unsupported_records_preserve_original_errors_and_custom_thresholds(self):
        class Custom(str):
            def lower(self):
                raise RuntimeError("custom lower")
        for rows in ([{}],[row("a",None)],[row("a",Custom("a"))],[row("a","A\ud800B"),row("b","ab")]):
            try:
                expected=self.call(rows,backend="python")
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.call(rows)
                self.assertEqual(error.args,actual.exception.args)
            else:
                self.assertEqual(expected,self.call(rows))
        rows=[row("a","a b"),row("b","a b c d")]
        with patch.object(source,"DUPLICATE_JACCARD",0.5):
            self.assertEqual(self.call(rows,legacy=True),self.call(rows))

    def test_empty_and_unavailable_inputs_do_not_start_native_work(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            self.assertEqual([],self.call([]))
            self.assertEqual([],self.call([],"source"))
        with patch.object(NativeProbe,"available",return_value=False), \
             patch.object(NativeProbe,"request",side_effect=AssertionError("unavailable RPC")):
            self.assertEqual((None,False),NativeMemoryConsolidation.raw_groups("duplicate-groups",[row("a")]))

    def test_full_findings_retain_projection_reason_order_without_normalization_replay(self):
        from datetime import date
        rows=[row("c","a b c d e f","review"),row("a"),row("b","a b c d e","all")]
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=source.findings(rows,0,today=date(2026,11,15))
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            actual,calls=self.observe(lambda:source.findings(rows,0,today=date(2026,11,15)))
        self.assertEqual(expected,actual)
        self.assertEqual([],calls)
        operations=[c.args[1] for c in requested.call_args_list]
        self.assertIn("duplicate-text-groups",operations)
        self.assertIn("shared-source-text-groups",operations)

    def test_real_store_cli_uses_raw_grouping_and_preserves_store_bytes(self):
        from datetime import date
        directory=self.base/"cli-records";directory.mkdir()
        rows=[row("a"*16,"ΟΣ!",schema_version=1),row("b"*16,"ος",schema_version=1)]
        for record in rows:
            record["digest"]=memory._digest(record)
            (directory/(record["id"]+".json")).write_text(json.dumps(record),encoding="utf-8")
        before={p.name:p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=source.findings(rows,0,today=date.today())
        output=io.StringIO()
        def invoke():
            with redirect_stdout(output):
                return memory._main(["--project",str(self.project),"consolidate"])
        with patch.dict(os.environ,self.env,clear=True),patch.object(memory,"store_dir",return_value=directory), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as requested:
            result,calls=self.observe(invoke)
        self.assertEqual(0,result)
        self.assertEqual(expected,json.loads(output.getvalue()))
        self.assertEqual([],calls)
        self.assertIn("duplicate-text-groups",[c.args[1] for c in requested.call_args_list])
        self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
