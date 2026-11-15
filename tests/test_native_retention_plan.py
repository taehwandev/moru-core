"""Actual retention previews preserve reference policy without Python scanning."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import agent_run_evidence as source
from native_pretool_support import environment, prepare
from support.native_probe_transport import NativeProbe

BASELINE="0424ec5d81517f79773e7f90538550914acf7be5"


class NativeRetentionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory(prefix="native-retention-plan-");cls.addClassCleanup(temp.cleanup)
        cls.base=Path(temp.name).resolve();cls.entry,cls.launch_project=prepare(cls.base)
        empty=cls.base/"empty";empty.mkdir();cls.env={**environment(cls.base),"PATH":str(empty)}
        original=subprocess.run(["git","show",BASELINE+":scripts/agent_run_evidence.py"],
            capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1]).stdout
        cls.oracle=types.ModuleType("original_retention_plan")
        exec(compile(original,"original_retention_plan.py","exec"),cls.oracle.__dict__)

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(temp.cleanup)
        self.project=Path(temp.name);self.runs=self.project/".moru/runs";self.runs.mkdir(parents=True)
        for index in range(3):
            folder=self.runs/f"{index:032x}";folder.mkdir()
            (folder/"continuation.json").write_text('{"phase":"done"}')
            (folder/"evidence").write_text("synthetic")
            os.utime(folder,(100+index,100+index))

    def call(self,backend="auto",**options):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            return source.plan(self.project,**{"keep":1,"use_registry":False,"now":1000,**options})

    def expected(self,**options):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            return self.oracle.plan(self.project,**{"keep":1,"use_registry":False,"now":1000,**options})

    def same(self,**options):
        expected=self.expected(**options);actual=self.call(**options)
        self.assertEqual(expected,actual)
        self.assertEqual(expected["removable"].options,actual["removable"].options)
        self.assertEqual(expected["removable"].identities,actual["removable"].identities)
        return actual

    def observe(self,action):
        calls=[];codes={source.phase_of.__code__,source.is_run_directory.__code__}
        def trace(frame,event,arg):
            if event=="call" and frame.f_code in codes:calls.append(frame.f_code.co_name)
        previous=sys.getprofile()
        try:
            sys.setprofile(trace);result=action()
        finally:sys.setprofile(previous)
        return result,calls

    def test_ordinary_preview_uses_one_batch_without_python_phase_or_directory_scan(self):
        expected=self.expected()
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.observe(self.call)
        self.assertEqual(expected,actual);self.assertEqual([],calls)
        self.assertEqual(1,request.call_count);self.assertEqual("retention-plan",request.call_args.args[1])
        self.assertIs(type(actual["removable"]),source._RemovalCandidates)
        self.assertEqual(expected["removable"].identities,actual["removable"].identities)
        self.assertEqual(expected["removable"].options,actual["removable"].options)

    def test_negative_control_observes_original_scan(self):
        expected=self.expected()
        actual,calls=self.observe(lambda:self.call("python"))
        self.assertEqual(expected,actual)
        self.assertIn("phase_of",calls);self.assertIn("is_run_directory",calls)

    def test_unsearchable_run_directory_preserves_reference_permission_error(self):
        os.chmod(self.runs,0o400)
        try:
            try:
                next(self.runs.iterdir()).is_dir()
            except PermissionError:
                pass
            else:
                self.skipTest("filesystem does not enforce directory search permissions")
            with self.assertRaises(PermissionError):
                self.oracle.plan(self.project,keep=1,use_registry=False,now=1000)
            with self.assertRaises(PermissionError):
                self.call()
        finally:
            os.chmod(self.runs,0o700)

    def test_registry_protection_orphan_windows_and_unknown_states_match_original(self):
        ids=[f"{index:032x}" for index in range(3)]
        for options in (
            {"registry_states":{},"orphan_after_seconds":200},
            {"registry_states":{},"orphan_after_seconds":10000},
            {"registry_states":{ids[0]:"completed",ids[1]:"completed",ids[2]:"running"},"protected":[ids[1]],"keep":0},
            {"registry_states":{ids[0]:"future",ids[1]:"unknown"}},
            {"registry_states":{key:"cancelled" for key in ids},"keep":0}):
            with self.subTest(options=options):self.same(**options)

    def test_equal_mtimes_and_exact_age_boundaries_preserve_order(self):
        for folder in self.runs.iterdir():os.utime(folder,ns=(100_123456789,100_123456789))
        actual=self.same();self.assertEqual([f"{index:032x}" for index in range(3)],[p.name for p in actual["finished"]])
        for folder in self.runs.iterdir():(folder/"continuation.json").write_text('{"phase":"acting"}')
        for cutoff in (100.123456788,100.123456789,100.123456790):
            with self.subTest(cutoff=cutoff):self.same(now=cutoff,abandoned_after_seconds=0)

    def test_json_phase_truthiness_and_invalid_bytes_match_original(self):
        path=self.runs/("0"*32)/"continuation.json"
        for phase in (None,False,0,[],{},"",True,7,3.5,[False],{"x":0},"done ",float("nan")):
            with self.subTest(phase=phase):
                path.write_text(json.dumps({"phase":phase}));self.same(abandoned_after_seconds=0)
        for raw in (b"{",b"[1]",b"\xff",b'\xef\xbb\xbf{"phase":"done"}',b'{"phase":"acting","phase":"done"}'):
            with self.subTest(raw=raw):path.write_bytes(raw);self.same(abandoned_after_seconds=0)

    def test_human_names_files_and_directory_links_are_named_and_preserved(self):
        (self.runs/"notes 한글").mkdir();(self.runs/"readme").write_text("kept")
        (self.runs/("f"*32)).symlink_to("0"*32,target_is_directory=True)
        (self.runs/("e"*32)).symlink_to("absent",target_is_directory=True)
        actual=self.same()
        self.assertEqual({"notes 한글","readme","f"*32,"e"*32},{p.name for p in actual["unclassified"]})

    def test_unreadable_registry_keeps_every_run_and_writes_nothing(self):
        registry=self.project/".moru/run-registry.json";registry.write_text("{")
        before={str(p.relative_to(self.project)):p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        actual=self.same(use_registry=True,keep=0)
        self.assertEqual(3,len(actual["unfinished"]));self.assertEqual([],actual["removable"])
        self.assertEqual(before,{str(p.relative_to(self.project)):p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
        self.assertFalse(list((self.project/".moru").glob("*.lock*")))

    def test_empty_preview_starts_no_native_process(self):
        project=self.project/"empty project";(project/".moru/runs").mkdir(parents=True)
        with patch.dict(os.environ,self.env,clear=True),patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            actual=source.plan(project,use_registry=False)
        self.assertTrue(all(not value for value in actual.values()))

    def test_custom_phase_and_opaque_thresholds_preserve_original_callbacks(self):
        def phase(path):return "acting"
        with patch.object(source,"phase_of",phase),patch.object(self.oracle,"phase_of",phase), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            self.same(abandoned_after_seconds=0)
        self.assertFalse(any(call.args[1]=="retention-plan" for call in request.call_args_list))
        seen=[]
        class Threshold:
            def __int__(inner):seen.append("converted");return 0
        threshold=Threshold();actual=self.call(abandoned_after_seconds=threshold)
        self.assertEqual(["converted"],seen)
        self.assertIs(threshold,actual["removable"].options["abandoned_after_seconds"])

    def test_legacy_three_argument_candidate_constructor_keeps_reference_call_shape(self):
        expected=self.expected();original=source._RemovalCandidates.__init__;seen=[]
        def legacy(instance,paths,project,options):
            seen.append("legacy");original(instance,paths,project,options)
        with patch.object(source._RemovalCandidates,"__init__",legacy), \
             patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual=self.call()
        self.assertEqual(expected,actual);self.assertEqual(["legacy"],seen)
        self.assertEqual(expected["removable"].identities,actual["removable"].identities)
        self.assertFalse(any(call.args[1]=="retention-plan" for call in request.call_args_list))

    def test_large_or_symlink_phase_decline_reuses_preparation_without_second_rpc(self):
        packet=self.runs/("0"*32)/"continuation.json"
        packet.write_text(json.dumps({"phase":"done","padding":"x"*(1024*1024)}))
        expected=self.expected()
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.observe(self.call)
        self.assertEqual(expected,actual);self.assertIn("phase_of",calls)
        self.assertEqual(1,request.call_count);self.assertEqual("retention-plan",request.call_args.args[1])
        target=self.project/"owned packet.json";target.write_text('{"phase":"done"}')
        packet.unlink();packet.symlink_to(target)
        self.same()

    def test_decline_does_not_repeat_registry_or_protected_iterator(self):
        ids=[f"{index:032x}" for index in range(3)];seen=[]
        def protected():seen.append("iterated");yield ids[0]
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"read_registry_states",return_value={key:"completed" for key in ids}) as read, \
             patch.object(NativeProbe,"request",return_value=None) as transport:
            actual=source.plan(self.project,keep=0,protected=protected(),now=1000)
        self.assertEqual(1,read.call_count);self.assertEqual(["iterated"],seen)
        self.assertEqual(1,transport.call_count);self.assertEqual({ids[1],ids[2]},{p.name for p in actual["removable"]})

    def test_malformed_projection_cannot_create_deletion_candidates(self):
        expected=self.expected()
        for result in (None,{}, {"value":{}},{"value":{"removable":["../escape"]}}):
            with self.subTest(result=result),patch.object(NativeProbe,"request",return_value=result) as request:
                actual=self.call()
                self.assertEqual(expected,actual);self.assertEqual(expected["removable"].identities,actual["removable"].identities)
                self.assertEqual(1,request.call_count)

    def test_valid_looking_projection_cannot_remove_held_runs_or_escape_metadata_root(self):
        captured=[];original=NativeProbe.request
        def observe(protocol,operation,payload):
            value=original(protocol,operation,payload)
            if operation=="retention-plan":captured.append(copy.deepcopy(value))
            return value
        with patch.object(NativeProbe,"request",side_effect=observe):self.call()
        self.assertEqual(1,len(captured));packet=captured[0]
        self.assertIs(type(packet["value"]),dict)
        ids=[f"{index:032x}" for index in range(3)]
        for options in ({"protected":[ids[0]]},
                        {"registry_states":{ids[0]:"running",ids[1]:"completed",ids[2]:"completed"}}):
            expected=self.expected(**options)
            with patch.object(NativeProbe,"request",return_value=copy.deepcopy(packet)) as request:
                actual=self.call(**options)
            self.assertEqual(expected,actual);self.assertEqual(1,request.call_count)
            self.assertNotIn(self.runs/ids[0],actual["removable"])
        packet["value"]["identities"][0][1][0][0]="../escape"
        expected=self.expected()
        with patch.object(NativeProbe,"request",return_value=packet) as request:
            self.assertEqual(expected,self.call());self.assertEqual(1,request.call_count)


if __name__=="__main__":unittest.main()
