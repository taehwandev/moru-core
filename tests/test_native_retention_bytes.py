"""Exact batched size accounting through real native metadata-only requests."""
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

BASELINE="c8919ff2f60e553e76ba45518c9f906437c3d910"


class NativeRetentionBytesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory(prefix="native-retention-bytes-");cls.addClassCleanup(temp.cleanup)
        cls.base=Path(temp.name).resolve();cls.entry,cls.project=prepare(cls.base)
        empty=cls.base/"empty";empty.mkdir();cls.env={**environment(cls.base),"PATH":str(empty)}
        original=subprocess.run(["git","show",BASELINE+":scripts/agent_run_evidence.py"],
            capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1]).stdout
        cls.oracle=types.ModuleType("original_bytes")
        exec(compile(original,"original_bytes.py","exec"),cls.oracle.__dict__)

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);(self.root/"nested").mkdir()
        (self.root/"nested/data").write_bytes(b"12345");(self.root/"한글").write_bytes(b"abc")
        (self.root/".hidden").write_bytes(b"x")

    def call(self,paths,backend="auto"):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            return source.directory_bytes(paths)

    def profile(self,action):
        calls=[]
        def observe(frame,event,arg):
            if event!="call":return
            if frame.f_code is source._directory_bytes_reference.__code__:calls.append("reference")
            if frame.f_code in {Path.rglob.__code__,Path.stat.__code__}:
                path=frame.f_locals.get("self")
                if path==self.root or self.root in getattr(path,"parents",()):calls.append(frame.f_code.co_name)
        previous=sys.getprofile()
        try:
            sys.setprofile(observe);result=action()
        finally:sys.setprofile(previous)
        return result,calls

    def test_one_real_request_covers_multiple_roots_without_python_scan(self):
        paths=[self.root,self.root/"nested",self.root]
        expected=self.oracle.directory_bytes(paths)
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.profile(lambda:self.call(paths))
        self.assertEqual(expected,actual);self.assertEqual([],calls);self.assertEqual(1,request.call_count)
        self.assertEqual("retention-bytes",request.call_args.args[1]);self.assertEqual(3,len(request.call_args.args[2]["paths"]))

    def test_negative_control_detects_original_size_scan(self):
        result,calls=self.profile(lambda:self.call([self.root],"python"))
        self.assertEqual(self.oracle.directory_bytes([self.root]),result)
        self.assertIn("reference",calls);self.assertIn("rglob",calls);self.assertIn("stat",calls)

    def test_file_root_links_broken_links_directories_and_fifo_match_original(self):
        (self.root/"file-link").symlink_to("nested/data")
        (self.root/"dir-link").symlink_to("nested",target_is_directory=True)
        (self.root/"broken").symlink_to("absent");os.mkfifo(self.root/"fifo")
        for paths in ([self.root],[self.root/"nested/data"],[self.root/"dir-link"],[self.root/"absent"],[]):
            self.assertEqual(self.oracle.directory_bytes(paths),self.call(paths))

    def test_typed_removal_preview_and_opaque_observations_remain_local(self):
        with patch.dict(os.environ,self.env,clear=True):
            paths=source._RemovalCandidates([self.root,self.root/"nested"],self.project,{"opaque":object()})
        marker=object();paths.identities={self.root:marker}
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.profile(lambda:self.call(paths))
        self.assertEqual(self.oracle.directory_bytes(paths),actual);self.assertEqual([],calls)
        self.assertEqual(1,request.call_count);self.assertEqual({"paths"},set(request.call_args.args[2]))
        self.assertIs(marker,paths.identities[self.root])

    def test_empty_plain_and_typed_inputs_start_no_process(self):
        paths=source._RemovalCandidates([],self.project,{})
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            self.assertEqual(0,self.call([]));self.assertEqual(0,self.call(paths))

    def test_custom_path_methods_and_iterables_keep_reference_behavior(self):
        for name,value in (("rglob",lambda *args:iter(())),("is_file",lambda *args:False)):
            with patch.object(Path,name,value),patch.object(NativeProbe,"request",side_effect=AssertionError("custom RPC")):
                self.assertEqual(self.oracle.directory_bytes([self.root]),self.call([self.root]))
        seen=[]
        class Roots:
            def __iter__(inner):seen.append("iter");yield self.root
        self.assertEqual(self.oracle.directory_bytes([self.root]),self.call(Roots()))
        self.assertEqual(["iter"],seen)
        paths=source._RemovalCandidates([self.root],self.project,{})
        with patch.object(source._RemovalCandidates,"__iter__",lambda inner:iter([self.root/"nested"])), \
             patch.object(NativeProbe,"request",side_effect=AssertionError("custom list RPC")):
            self.assertEqual(self.oracle.directory_bytes(paths),self.call(paths))

    def test_original_errors_and_malformed_or_oversized_totals_do_not_return_partial_values(self):
        with patch.object(Path,"rglob",side_effect=PermissionError("synthetic denial")):
            for action in (lambda:self.oracle.directory_bytes([self.root]),lambda:self.call([self.root])):
                with self.assertRaisesRegex(PermissionError,"synthetic denial"):action()
        expected=self.oracle.directory_bytes([self.root])
        for value in (None,{}, {"value":True},{"value":-1},{"value":"-1"},{"value":"00"},
                      {"value":""},{"value":"1"*25},{"value":"१२"}):
            with patch.object(NativeProbe,"request",return_value=value) as request:
                self.assertEqual(expected,self.call([self.root]));self.assertEqual(1,request.call_count)
        with patch.object(NativeProbe,"request",return_value={"value":str(2**70)}):
            self.assertEqual(2**70,self.call([self.root]))

    def test_report_counts_match_original_and_stay_read_only(self):
        project=self.root/"report project";runs=project/".moru/runs";runs.mkdir(parents=True)
        for name in ("a"*32,"b"*32):
            folder=runs/name;folder.mkdir();(folder/"continuation.json").write_text('{"phase":"done"}')
            (folder/"data").write_bytes(b"content")
        before={str(p.relative_to(project)):p.read_bytes() for p in project.rglob("*") if p.is_file()}
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=self.oracle.prune_run_evidence(project,keep=0,apply=False)
        with patch.dict(os.environ,self.env,clear=True),patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.profile(lambda:source.prune_run_evidence(project,keep=0,apply=False))
        self.assertEqual(expected,actual);self.assertNotIn("reference",calls)
        self.assertEqual(1,sum(call.args[1]=="retention-bytes" for call in request.call_args_list))
        self.assertEqual(before,{str(p.relative_to(project)):p.read_bytes() for p in project.rglob("*") if p.is_file()})


if __name__=="__main__":unittest.main()
