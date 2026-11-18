"""Capture admission: normalized input, exact failure order and unchanged writes."""
from datetime import date
from pathlib import Path
from contextlib import redirect_stdout
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import agent_project_memory as source
from native_pretool_support import environment, prepare
from support.native_memory_capture import NativeMemoryCapture
from support.native_probe_transport import NativeProbe
from support.native_memory_analysis import NativeMemoryAnalysis


class CaptureInputContractTests(unittest.TestCase):
    def test_capture_uses_native_normalized_inputs_before_its_existing_writer(self):
        expected_digest = source._digest({"body":"body","source":"note","scope":"task",
                                          "review_on":"2099-01-01","applies_when":"ready"})
        def request(flag, operation, packet):
            self.assertEqual("capture-inputs",operation)
            self.assertEqual("  body  ",packet["body"])
            return {"body":"body","source":"note","conditions":{"applies_when":"ready"},
                    "digest":expected_digest}
        with patch.object(NativeProbe,"available",return_value=True), \
             patch.object(NativeProbe,"request",side_effect=request) as probe, \
             patch.object(source,"_writable_store",return_value=MagicMock()), \
             patch.object(source,"_record_path",return_value=Path("record.json")), \
             patch.object(source,"atomic_write_json") as written:
            record = source._capture(Path("."),body="  body  ",source=" note ",scope="task",
                                     review_on="2099-01-01",applies_when=" ready ")
        self.assertEqual(1,probe.call_count)
        self.assertEqual(("body","note","ready"),
                         (record["body"],record["source"],record["applies_when"]))
        self.assertEqual(1,written.call_count)
        self.assertIs(record,written.call_args.args[1])

    def test_malformed_or_declined_responses_use_reference_without_extra_request(self):
        values = (" body "," note ","task","2099-01-01"," ready ","")
        expected = source._capture_inputs_reference(*values)
        packets = (None,{}, {"invalid":True},{"invalid":"unknown"},
                   {"body":"","source":"note","conditions":{}},
                   {"body":"body","source":"note","conditions":{"unknown":"x"}},
                   {"body":"body","source":"note","conditions":{"not_when":[]}})
        for result in packets:
            with self.subTest(result=result),patch.object(NativeProbe,"available",return_value=True), \
                 patch.object(NativeProbe,"request",return_value=result) as probe:
                self.assertEqual(expected,source._capture_inputs(*values))
                self.assertEqual(1,probe.call_count)


class NativeMemoryCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-capture-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry,self.project = prepare(self.base)
        empty = self.base/"empty";empty.mkdir()
        self.env = {**environment(self.base),"PATH":str(empty)}

    def values(self,**updates):
        fields = {"body":" body ","source":" note ","scope":"task","review_on":"2099-01-01",
                  "applies_when":" ready ","not_when":""}
        fields.update(updates)
        return tuple(fields[key] for key in ("body","source","scope","review_on","applies_when","not_when"))

    def test_analysis_capture_uses_one_request_without_replaying_binding(self):
        calls = []
        codes = (source._analysis_binding.__code__,source._analysis_binding_reference.__code__)
        def observe(frame,event,arg):
            if event == "call" and frame.f_code in codes:calls.append(True)
        previous = sys.getprofile()
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(source,"_source_blob",return_value="a"*40), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            try:
                sys.setprofile(observe)
                row = source._capture(self.project,body="body",source="note",scope="task",
                    review_on="2099-01-01",source_paths=("source.py",),
                    analysis_question=" Why 한글? ",analysis_context=" Keep Case and not X ")
            finally:sys.setprofile(previous)
        self.assertEqual([],calls,"Python analysis binding replay")
        self.assertEqual(["capture-inputs"],[call.args[1] for call in probe.call_args_list])
        self.assertEqual({"question":"Why 한글?","context":"Keep Case and not X","inputs":"b"*64},row["analysis"])
        self.assertEqual(source._digest(row),row["digest"])
        calls.clear()
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(source,"_source_blob",return_value="a"*40), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(source,"_capture_analysis_profile",return_value=False), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            try:
                sys.setprofile(observe)
                self.analysis_capture()
            finally:sys.setprofile(previous)
        self.assertEqual([True],calls)
        self.assertEqual(["capture-inputs","analysis-binding"],[call.args[1] for call in probe.call_args_list])

    def analysis_capture(self,**updates):
        fields = dict(body="body",source="note",scope="task",review_on="2099-01-01",
            source_paths=("source.py",),analysis_question=" Why 한글? ",analysis_context=" Keep NOT X ")
        return source._capture(self.project,**(fields | updates))

    def test_fused_analysis_matches_reference_unicode_and_raw_length_rules(self):
        values = ((" q "," c "),("한"*300,"c"),("한"*301,"c"),(" q"+" "*298,"c"),
                  ("q\n","c"),("\x85q","c"),("","c"),("q",""),(" ","c"))
        for index,(question,context) in enumerate(values):
            with self.subTest(index=index),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(source,"store_dir",return_value=self.base/str(index)), \
                 patch.object(source,"_source_blob",return_value="a"*40), \
                 patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
                try:expected = source._analysis_binding_reference(question,context)
                except ValueError as error:
                    with self.assertRaises(ValueError) as caught:
                        self.analysis_capture(analysis_question=question,analysis_context=context)
                    self.assertEqual(error.args,caught.exception.args)
                    self.assertFalse((self.base/str(index)).exists())
                else:
                    row = self.analysis_capture(analysis_question=question,analysis_context=context)
                    self.assertEqual({**expected,"inputs":"b"*64},row["analysis"])
                    self.assertEqual(source._digest(row),row["digest"])
                self.assertEqual(["capture-inputs"],[call.args[1] for call in probe.call_args_list])

    def test_analysis_error_is_deferred_until_existing_source_checks(self):
        cases = (({"body":""},"memory body",False),({},"source path",True),
                 ({"source_paths":tuple(str(i) for i in range(5))},"at most",False),
                 ({"source_paths":()},"analysis question",False))
        for fields,message,source_checked in cases:
            with self.subTest(fields=fields),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(source,"store_dir",return_value=self.base/"records"), \
                 patch.object(source,"_source_blob",return_value="") as blob:
                with self.assertRaisesRegex(ValueError,message):
                    self.analysis_capture(**(dict(analysis_question="",analysis_context="c") | fields))
                self.assertEqual(source_checked,bool(blob.call_count))
                self.assertFalse((self.base/"records").exists())
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"_existing",side_effect=ValueError("missing old")), \
             patch.object(source,"_source_blob",side_effect=AssertionError("source read before replacement")):
            with self.assertRaisesRegex(ValueError,"missing old"):
                self.analysis_capture(replaces="a"*16,analysis_question="")
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"_source_blob",return_value="a"*40), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(source,"_writable_store",side_effect=ValueError("denied store")):
            with self.assertRaisesRegex(ValueError,"denied store"):self.analysis_capture()
            with self.assertRaisesRegex(ValueError,"requires tracked source evidence"):
                self.analysis_capture(source_paths=())

    def test_malformed_fused_analysis_declines_without_second_analysis_request(self):
        bindings = (None,{}, {"invalid":False},{"invalid":1},{"binding":None},
                    {"binding":{"question":"q"}}, {"binding":{"question":"q","context":True}},
                    {"binding":{"question":"q","context":"c","extra":"x"}})
        for binding in bindings:
            response = {"body":"body","source":"note","conditions":{},"analysis":binding}
            with self.subTest(binding=binding),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(source,"store_dir",return_value=self.base/"records"), \
                 patch.object(source,"_source_blob",return_value="a"*40), \
                 patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
                 patch.object(NativeProbe,"request",return_value=response) as probe:
                row = self.analysis_capture()
                self.assertEqual("Why 한글?",row["analysis"]["question"])
                self.assertEqual(1,probe.call_count)

    def test_analysis_packet_is_not_mutated_when_store_metadata_is_added(self):
        response = {"body":"body","source":"note","conditions":{},
                    "analysis":{"binding":{"question":"q","context":"c"}}}
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(source,"_source_blob",return_value="a"*40), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(NativeProbe,"request",return_value=response):
            row = self.analysis_capture()
        self.assertEqual({"question":"q","context":"c"},response["analysis"]["binding"])
        self.assertEqual("b"*64,row["analysis"]["inputs"])

    def test_custom_analysis_owners_and_late_source_callback_are_respected(self):
        custom = {"question":"custom","context":"binding"}
        owners = ((source,"_analysis_binding"),(source,"_analysis_binding_reference"),
                  (NativeMemoryAnalysis,"binding"),(NativeMemoryAnalysis,"_request"))
        for owner,name in owners:
            result = dict(custom) if owner is source else {"binding":dict(custom)}
            with self.subTest(name=name),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(source,"store_dir",return_value=self.base/"records"), \
                 patch.object(source,"_source_blob",return_value="a"*40), \
                 patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
                 patch.object(owner,name,return_value=result) as changed, \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
                if name == "_analysis_binding_reference":
                    # Force the original native binding to decline, preserving the custom reference.
                    with patch.object(NativeMemoryAnalysis,"binding",return_value=None):row = self.analysis_capture()
                else:row = self.analysis_capture()
                self.assertEqual({**custom,"inputs":"b"*64},row["analysis"])
                self.assertEqual(1,changed.call_count)
                self.assertNotIn("analysis",probe.call_args_list[0].args[2])
        original = source._analysis_binding
        def blob(*args,**kwargs):
            source._analysis_binding = lambda *args:dict(custom)
            return "a"*40
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(source,"_source_blob",side_effect=blob), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            try:row = self.analysis_capture()
            finally:source._analysis_binding = original
        self.assertIn("analysis",probe.call_args_list[0].args[2])
        self.assertEqual({**custom,"inputs":"b"*64},row["analysis"])

    def test_analysis_string_subclass_keeps_its_original_strip_behavior(self):
        class Question(str):
            def strip(self):return "custom question"
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(source,"_source_blob",return_value="a"*40), \
             patch.object(source.EvidenceInputs,"capture",return_value="b"*64), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            row = self.analysis_capture(analysis_question=Question("original"))
            self.assertEqual("custom question",row["analysis"]["question"])
            self.assertNotIn("analysis",probe.call_args_list[0].args[2])

    def test_analysis_customization_before_first_capture_import_is_not_treated_as_canonical(self):
        program = """
import agent_project_memory as memory
from support.native_memory_analysis import NativeMemoryAnalysis
NativeMemoryAnalysis.binding = lambda q,c: {"binding":{"question":"custom","context":"binding"}}
assert not memory._capture_analysis_profile(), "custom binding admitted as canonical on first import"
"""
        done = subprocess.run([sys.executable,"-B","-c",program],capture_output=True,text=True,
            env={**self.env,"PYTHONPATH":str(Path(source.__file__).parent)},cwd=self.base,timeout=8)
        self.assertEqual(0,done.returncode,done.stderr)

    def test_analysis_capture_cli_retains_actual_tracked_source_and_input_evidence(self):
        path = self.project/"source.py";path.write_text("VALUE = 1\n")
        subprocess.run(["git","-C",str(self.project),"add","source.py"],check=True,capture_output=True)
        output = io.StringIO()
        env = {**self.env,"PATH":os.environ.get("PATH","")}
        with patch.dict(os.environ,env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(sys,"stdin",io.StringIO("body")),redirect_stdout(output), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            self.assertEqual(0,source._main(["--project",str(self.project),"capture","--source","note", "--scope","task",
                "--review-on","2099-01-01","--source-path","source.py","--analysis-question"," q ","--analysis-context"," c "]))
            row = source.json.loads(output.getvalue())
            self.assertEqual("q",row["analysis"]["question"])
            self.assertEqual(source.EvidenceInputs.capture(self.project,[]),row["analysis"]["inputs"])
            self.assertEqual(source._source_blob(self.project,"source.py",tracked=True),row["source_files"][0]["blob"])
            operations = [call.args[1] for call in probe.call_args_list]
            self.assertEqual(1,operations.count("capture-inputs"))
            self.assertNotIn("analysis-binding",operations)
            self.assertEqual(row,source.read_record(self.base/"records"/(row["id"]+".json")))

    def test_unsupported_analysis_packets_and_empty_binding_start_no_request(self):
        bad = ((),("q",),("q","c","x"),["q","c"],("q",1),("",""))
        for value in bad:
            with self.subTest(value=value),patch.object(NativeProbe,"request",side_effect=AssertionError("unexpected request")):
                self.assertIsNone(NativeMemoryCapture.inputs(*self.values(),analysis=value))
        with patch.object(NativeProbe,"request",side_effect=AssertionError("unexpected request")):
            self.assertIsNone(NativeMemoryCapture.inputs(*self.values(),analysis=("q","c"),digest=True))

    def call(self,values,required=False):
        calls = []
        code = source._capture_inputs_reference.__code__
        def observe(frame,event,arg):
            if event == "call" and frame.f_code is code:
                calls.append(True)
        previous = sys.getprofile()
        with patch.dict(os.environ,self.env,clear=True):
            try:
                if required:sys.setprofile(observe)
                return source._capture_inputs(*values)
            finally:
                sys.setprofile(previous)
                if required:self.assertEqual([],calls,"Python capture validation replay")

    def parity(self,values,required=True):
        try:expected = source._capture_inputs_reference(*values)
        except Exception as error:
            with self.assertRaises(type(error)) as caught:self.call(values,required)
            self.assertEqual(error.args,caught.exception.args)
        else:self.assertEqual(expected,self.call(values,required))

    def test_ordinary_capture_boundaries_and_unicode_keep_values_and_error_order(self):
        cases = ({}, {"body":"\x1c"+"한"*500+"\x85","source":"é"*200,"not_when":"🚀"*160},
                 {"body":""},{"body":"한"*501},{"source":"x"*201},{"body":"a\nb"},
                 {"source":"a\tb"},{"scope":"bad scope"},{"scope":"a"},{"scope":"a"*42},
                 {"review_on":"0001-01-01"},{"review_on":date.today().isoformat()},
                 {"applies_when":"x"*161},{"not_when":"a\nb"},{"applies_when":"  ","not_when":" stop "},
                 {"body":"","source":"","scope":"","review_on":"bad","not_when":"x"*161})
        for updates in cases:
            with self.subTest(updates=updates):self.parity(self.values(**updates))

    def test_extended_and_invalid_dates_preserve_current_interpreter_errors(self):
        for review in ("20990101","2099-W01-1","1900-02-29","2099-04-31","bad",None):
            with self.subTest(review=review):self.parity(self.values(review_on=review),required=False)

    def test_custom_calendar_scope_conditions_and_string_subclasses_keep_reference(self):
        class Text(str):pass
        class Calendar:
            fromisoformat = staticmethod(date.fromisoformat)
            today = staticmethod(date.today)
        for owner,name,value in ((source,"date",Calendar),(source,"SCOPE_RE",MagicMock(fullmatch=lambda value:True)),
                                 (source,"MAX_CONDITION_CHARS",2),(source,"APPLICABILITY_FIELDS",("not_when","applies_when"))):
            with patch.object(owner,name,value),patch.object(NativeProbe,"request",side_effect=AssertionError("custom RPC")):
                self.parity(self.values(),required=False)
        with patch.object(NativeProbe,"request",side_effect=AssertionError("subclass RPC")):
            self.parity(self.values(body=Text(" body ")),required=False)

    def test_one_real_request_and_disabled_native_negative_control(self):
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            self.call(self.values(),required=True)
        self.assertEqual(1,probe.call_count)
        self.assertEqual("capture-inputs",probe.call_args.args[1])
        with patch.object(NativeMemoryCapture,"inputs",return_value=None):
            with self.assertRaisesRegex(AssertionError,"Python capture validation replay"):
                self.call(self.values(),required=True)

    def test_real_capture_and_replacement_keep_record_digest_and_retirement_order(self):
        directory = self.base/"records"
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=directory):
            first = source._capture(self.project,body=" old ",source=" note ",scope="task",review_on="2099-01-01")
            second = source._capture(self.project,body=" new ",source=" note ",scope="task",review_on="2099-01-01",
                                     replaces=first["id"],applies_when=" ready ")
            stored = [source.read_record(path) for path in sorted(directory.glob("*.json"))]
        self.assertEqual(2,len(stored))
        self.assertTrue(all(row is not None and row["digest"]==source._digest(row) for row in stored))
        by_id = {row["id"]:row for row in stored}
        self.assertEqual("retired",by_id[first["id"]]["status"])
        self.assertEqual(second["id"],by_id[first["id"]]["replaced_by"])
        self.assertEqual(("new","note","ready"),
                         (second["body"],second["source"],second["applies_when"]))

    def test_real_capture_fuses_digest_without_python_replay_or_another_request(self):
        calls = []
        code = source._digest.__code__
        def observe(frame,event,arg):
            if event == "call" and frame.f_code is code:calls.append(True)
        previous = sys.getprofile()
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"store_dir",return_value=self.base/"records"), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            try:
                sys.setprofile(observe)
                record = source._capture(self.project,body=" 한글 body ",source=" note ",scope="task",
                                         review_on="2099-01-01",applies_when=" ready ")
            finally:
                sys.setprofile(previous)
        self.assertEqual([],calls,"Python capture digest replay")
        self.assertEqual(1,probe.call_count)
        self.assertTrue(probe.call_args.args[2]["digest"])
        self.assertEqual(source._digest(record),record["digest"])
        with patch.object(source,"_capture_digest_profile",return_value=False), \
             patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"store_dir",return_value=self.base/"records"):
            calls.clear()
            try:
                sys.setprofile(observe)
                source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01")
            finally:
                sys.setprofile(previous)
        self.assertEqual([True],calls,"Disabled digest fusion must expose Python replay")

    def test_digest_bytes_match_reference_for_printable_unicode_and_conditions(self):
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"):
            for body in ('A "quoted" \\ path /','😀𐐀İΣ','e\u0301','한글 body','foo_bar'):
                row = source._capture(self.project,body="  "+body+"  ",source=" note ",scope="task",
                                      review_on="2099-01-01",applies_when=" ready ",not_when=" except ")
                self.assertEqual(source._digest(row),row["digest"])

    def test_bad_fused_digest_falls_back_once_without_a_second_request(self):
        good = {"body":"body","source":"note","conditions":{}}
        for result in (good,{**good,"digest":True},{**good,"digest":"a"*63},
                       {**good,"digest":"A"*64},{**good,"digest":"a"*64,"extra":True}):
            with self.subTest(result=result),patch.dict(os.environ,self.env,clear=True), \
                 patch.object(source,"store_dir",return_value=self.base/"records"), \
                 patch.object(NativeProbe,"request",return_value=result) as probe:
                row = source._capture(self.project,body=" body ",source=" note ",scope="task",review_on="2099-01-01")
                self.assertEqual(source._digest(row),row["digest"])
                self.assertEqual(1,probe.call_count)

    def test_metadata_and_custom_digest_keep_original_hashing(self):
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"):
            with patch.object(source,"_source_blob",return_value="a"*40), \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
                row = source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01",
                                      source_paths=("source.py",))
                self.assertEqual(source._digest(row),row["digest"])
                self.assertNotIn("digest",probe.call_args.args[2])
            with patch.object(source,"_digest",return_value="custom-digest") as digest:
                row = source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01")
                self.assertEqual("custom-digest",row["digest"])
                self.assertEqual(1,digest.call_count)

    def test_custom_hash_constructor_and_json_encoder_are_not_bypassed(self):
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=self.base/"records"):
            with patch.object(source.hashlib,"sha256",return_value=MagicMock(hexdigest=lambda:"custom-hash")) as hashed:
                row = source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01")
                self.assertEqual("custom-hash",row["digest"])
                self.assertEqual(1,hashed.call_count)
            original = source.json.JSONEncoder
            class Encoder(original):
                def encode(self,value):return super().encode(value)+" "
            with patch.object(source.json,"JSONEncoder",Encoder), \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
                row = source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01")
                self.assertEqual(source._digest(row),row["digest"])
                self.assertNotIn("digest",probe.call_args.args[2])

    def test_store_callback_changes_recheck_digest_before_writing(self):
        original = source._digest
        directory = self.base/"records"
        def admitted(project):
            source._digest = lambda record:"changed-after-validation"
            return directory
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=directory), \
             patch.object(source,"_writable_store",side_effect=admitted), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            try:
                row = source._capture(self.project,body="body",source="note",scope="task",review_on="2099-01-01")
            finally:
                source._digest = original
        self.assertTrue(probe.call_args.args[2]["digest"])
        self.assertEqual("changed-after-validation",row["digest"])

    def test_capture_cli_emits_the_fused_digest_and_a_valid_record(self):
        output = io.StringIO()
        directory = self.base/"records"
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=directory), \
             patch.object(sys,"stdin",io.StringIO(" 한글 body ")),redirect_stdout(output), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
            self.assertEqual(0,source._main(["--project",str(self.project),"capture","--source","note",
                                            "--scope","task","--review-on","2099-01-01"]))
            row = source.json.loads(output.getvalue())
            self.assertEqual(1,probe.call_count)
            self.assertTrue(probe.call_args.args[2]["digest"])
            self.assertEqual(source._digest(row),row["digest"])
            self.assertEqual(row,source.read_record(directory/(row["id"]+".json")))

    def test_invalid_input_and_store_denial_never_create_a_record(self):
        directory = self.base/"records"
        with patch.dict(os.environ,self.env,clear=True),patch.object(source,"store_dir",return_value=directory), \
             patch.object(source,"user_store_write_error",return_value="denied store"):
            for body,message in (("", "memory body"),("valid", "denied store")):
                with self.assertRaisesRegex(ValueError,message):
                    source._capture(self.project,body=body,source="note",scope="task",review_on="2099-01-01")
        self.assertFalse(directory.exists())
