"""Exact metadata snapshots and existing deletion revalidation on owned fixtures."""
import json
import errno
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

BASELINE="bd675de72eacc55607dbfe1fb8b0bd948097ae8b"


class NativeRetentionIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory(prefix="moru-identity-");cls.addClassCleanup(temp.cleanup)
        cls.base=Path(temp.name).resolve();cls.entry,cls.project=prepare(cls.base)
        empty=cls.base/"empty";empty.mkdir();cls.env={**environment(cls.base),"PATH":str(empty)}
        original=subprocess.run(["git","show",BASELINE+":scripts/agent_run_evidence.py"],
            capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1]).stdout
        cls.oracle=types.ModuleType("original_identity")
        exec(compile(original,"original_identity.py","exec"),cls.oracle.__dict__)

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        (self.root/"a").mkdir();(self.root/"a/x").write_text("first")
        (self.root/"a-b").write_text("hyphen");(self.root/"한글").write_text("data")
        (self.root/".hidden").write_text("")

    def call(self,path=None,backend="auto"):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            path=self.root if path is None else path
            return source._identities([path])[path]

    def profile(self,action):
        calls=[]
        codes={Path.rglob.__code__,Path.lstat.__code__,source._identity.__code__}
        def observe(frame,event,arg):
            if event=="call" and frame.f_code in codes:
                calls.append(frame.f_code.co_name)
        previous=sys.getprofile()
        try:
            sys.setprofile(observe);result=action()
        finally:
            sys.setprofile(previous)
        return result,calls

    def test_real_identity_matches_original_without_python_metadata_replay(self):
        expected=self.oracle._identity(self.root)
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.profile(self.call)
        self.assertEqual(expected,actual);self.assertEqual([],calls)
        self.assertEqual(1,request.call_count);self.assertEqual("retention-identities",request.call_args.args[1])
        self.assertLess([row[0] for row in actual].index("a/x"),[row[0] for row in actual].index("a-b"))
        self.assertIs(type(actual),tuple);self.assertTrue(all(type(row) is tuple for row in actual))

    def test_negative_control_detects_python_scan_and_stat(self):
        actual,calls=self.profile(lambda:self.call(backend="python"))
        self.assertEqual(self.oracle._identity(self.root),actual)
        for name in ("_identity","rglob","lstat"):
            self.assertIn(name,calls)

    def test_symlinks_broken_links_empty_directories_and_fifo_are_metadata_only(self):
        (self.root/"empty dir").mkdir()
        (self.root/"dir-link").symlink_to("a",target_is_directory=True)
        (self.root/"file-link").symlink_to("a/x")
        (self.root/"broken").symlink_to("absent")
        os.mkfifo(self.root/"fifo")
        actual,calls=self.profile(self.call)
        self.assertEqual(self.oracle._identity(self.root),actual);self.assertEqual([],calls)
        self.assertNotIn("dir-link/x",[row[0] for row in actual])

    def test_integer_nanoseconds_permissions_and_in_place_changes_match(self):
        target=self.root/"a/x";os.utime(target,ns=(-1234567890,-1234567890))
        os.chmod(target,0o640)
        before=self.call();self.assertEqual(self.oracle._identity(self.root),before)
        self.assertEqual(target.lstat().st_mtime_ns,next(row[5] for row in before if row[0]=="a/x"))
        root_time=self.root.stat().st_mtime_ns
        target.write_text("changed and longer")
        self.assertEqual(root_time,self.root.stat().st_mtime_ns)
        after=self.call();self.assertEqual(self.oracle._identity(self.root),after);self.assertNotEqual(before,after)

    def test_file_root_missing_and_noncanonical_paths_keep_reference_behavior(self):
        for path in (self.root/"a/x",self.root/"absent",Path(os.path.relpath(self.root))):
            self.assertEqual(self.oracle._identity(path),self.call(path))

    def test_custom_and_missing_path_methods_preserve_original_error_order(self):
        with patch.object(Path,"rglob",return_value=[]),patch.object(NativeProbe,"request",side_effect=AssertionError("custom native")):
            self.assertEqual(self.oracle._identity(self.root),self.call())
        with patch.object(Path,"lstat",side_effect=PermissionError("denied")),patch.object(NativeProbe,"request",side_effect=AssertionError("custom native")):
            self.assertIsNone(self.call())
        owner=next(cls for cls in Path.__mro__ if "relative_to" in cls.__dict__)
        original=owner.__dict__["relative_to"];delattr(owner,"relative_to")
        try:
            self.assertEqual(self.oracle._identity(self.root/"absent"),self.call(self.root/"absent"))
        finally:
            setattr(owner,"relative_to",original)

    def test_root_symlink_declines_without_losing_metadata(self):
        link=self.root/"root-link";link.symlink_to("a",target_is_directory=True)
        for path in (link,):
            actual,calls=self.profile(lambda:self.call(path))
            self.assertEqual(self.oracle._identity(path),actual);self.assertIn("_identity",calls)

    def test_non_utf8_child_names_preserve_reference_metadata_when_supported(self):
        try:
            descriptor=os.open(os.fsencode(self.root)+b"/bad-\xff",os.O_CREAT|os.O_WRONLY,0o600)
        except OSError as error:
            if error.errno in (errno.EPERM,errno.EILSEQ,errno.EINVAL):
                self.skipTest("local filesystem or sandbox rejects non-UTF-8 filenames")
            raise
        os.close(descriptor)
        actual,calls=self.profile(self.call)
        self.assertEqual(self.oracle._identity(self.root),actual);self.assertIn("_identity",calls)

    def test_private_schema_and_unrepresentable_root_decline_quietly(self):
        for payload in ({},{"paths":False},{"paths":["\udcff"]},{"paths":[str(self.root)],"extra":1},
                        {"paths":[str(self.root)]*257}):
            done=subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                "--registry-read-probe","retention-identities"],input=json.dumps(payload).encode(),
                env={**self.env,"MORU_HOOK_SOFT_FAIL":"1"},cwd=self.project,capture_output=True,timeout=8)
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))

    def test_malformed_metadata_packets_fall_back_once(self):
        expected=self.oracle._identity(self.root)
        root=list(expected[0]);valid=list(expected[1])
        for packet in (None,{}, {"value":[]},{"value":[[root,valid,valid]]},
            {"value":[[["../escape",*root[1:]]]]},{"value":[[[".",True,*root[2:]]]]},{"value":[[root[:-1]]]}):
            with patch.object(NativeProbe,"request",return_value=packet) as request:
                self.assertEqual(expected,self.call());self.assertEqual(1,request.call_count)

    def test_apply_rechecks_native_identity_and_keeps_changed_evidence(self):
        project=self.root/"owned project";runs=project/".moru/runs";runs.mkdir(parents=True)
        for name in ("a"*32,"b"*32):
            folder=runs/name;folder.mkdir();(folder/"continuation.json").write_text('{"phase":"done"}')
            (folder/"evidence.json").write_text("old")
        with patch.dict(os.environ,self.env,clear=True),patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            preview=source.plan(project,keep=0)
            changed=runs/("a"*32);old_time=changed.stat().st_mtime_ns
            (changed/"evidence.json").write_text("changed evidence")
            self.assertEqual(old_time,changed.stat().st_mtime_ns)
            self.assertEqual(1,source.apply_plan(preview["removable"]))
        batches=[call for call in request.call_args_list if call.args[1]=="retention-identities"]
        self.assertEqual(2,len(batches));self.assertTrue(all(len(call.args[2]["paths"])==2 for call in batches))
        self.assertTrue(changed.is_dir());self.assertFalse((runs/("b"*32)).exists())

    def test_multiple_roots_share_one_request_without_python_scan(self):
        paths=[self.root,self.root/"a",self.root/"a-b"]
        expected={path:self.oracle._identity(path) for path in paths}
        def invoke():
            with patch.dict(os.environ,self.env,clear=True):
                return source._identities(paths)
        with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
            actual,calls=self.profile(invoke)
        self.assertEqual(expected,actual);self.assertEqual([],calls);self.assertEqual(1,request.call_count)
        self.assertEqual(3,len(request.call_args.args[2]["paths"]))

    def test_empty_batch_starts_no_process(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty RPC")):
            self.assertEqual({},source._identities([]))

    def test_change_after_prior_deletion_is_still_checked_immediately(self):
        project=self.root/"late project";runs=project/".moru/runs";runs.mkdir(parents=True)
        for name in ("c"*32,"d"*32):
            folder=runs/name;folder.mkdir();(folder/"continuation.json").write_text('{"phase":"done"}')
            (folder/"evidence.json").write_text("old")
        with patch.dict(os.environ,self.env,clear=True):
            preview=source.plan(project,keep=0)
            first,second=preview["removable"]
            original=source.shutil.rmtree
            def delete_then_change(path,**options):
                original(path,**options)
                if path==first:
                    (second/"evidence.json").write_text("changed after the first deletion")
            with patch.object(source.shutil,"rmtree",side_effect=delete_then_change):
                self.assertEqual(1,source.apply_plan(preview["removable"]))
        self.assertFalse(first.exists());self.assertTrue(second.is_dir())


if __name__=="__main__":
    unittest.main()
