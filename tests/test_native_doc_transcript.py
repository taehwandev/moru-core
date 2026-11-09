"""Source parity for native doc-delivery file scans and read-only boundaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import agent_required_doc_delivery as reference
import test_agent_required_doc_delivery as delivery_fixtures
import test_agy_required_docs_hook as agy_fixtures
from native_pretool_support import environment, prepare, result
from support.native_doc_transcript import NativeDocTranscript


class NativeDocTranscriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-doc-transcript-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(self.empty)}
        self.path = self.base / "synthetic-transcript.jsonl"

    def raw(self, operation, payload=None, **env):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--doc-transcript-probe", operation], input=json.dumps(payload or {"path":str(self.path)}).encode(),
            capture_output=True, cwd=self.project, env={**self.env, **env}, timeout=8)

    def native(self, name, *args):
        with patch.dict(os.environ, self.env, clear=True):
            return getattr(NativeDocTranscript, name)(*args)

    def original(self, name, *args):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND":"python"}, clear=True):
            return getattr(reference, "_" + name)(*args)

    def parity(self, raw, fallback=0, offset=0, count=0, limit=3):
        self.path.write_bytes(raw)
        state = {"transcript_bytes":offset, "redeliveries":count}
        before = self.path.read_bytes()
        calls = (("compacted", "compacted_before", (self.path,)),
                 ("aligned", "aligned_size", (self.path,fallback)),
                 ("due", "due_after_compaction", (state,self.path,limit)))
        for native, source, args in calls:
            with self.subTest(operation=native, raw=raw[:60], offset=offset):
                expected = self.original(source, *args)
                actual = self.native(native, *args)
                self.assertIsNotNone(actual)
                self.assertEqual(expected,actual)
                self.assertIs(type(expected),type(actual))
        self.assertEqual(before,self.path.read_bytes())

    def test_three_runtime_boundaries_and_partial_rows(self):
        for row in ({"type":"compacted"}, {"type":"system","subtype":"compact_boundary"},
                    {"type":"CHECKPOINT","content":"# Resuming from a compaction\nsummary"}):
            encoded=json.dumps(row).encode()
            self.parity(encoded)
            self.parity(encoded+b"\n")
            self.parity(b"ordinary row\n"+encoded+b"\n")

    def test_raw_prefilter_invalid_rows_bom_and_unused_nonfinite_values(self):
        for raw in (b"", b"\xff\n", b"{bad \"compacted\"}\n", b"[\"compacted\"]\n",
                    b'{"type":"comp\\u0061cted"}\n',
                    b'{"type":"comp\\u0061cted","unused":"compacted"}\n',
                    b'{"type":"compacted","unused":[NaN,Infinity,-Infinity,900719925474099312345678901]}\n',
                    b'{"type":"compacted","type":"assistant"}\n',
                    b'{"type":"assistant","type":"compacted"}\n',
                    b'\xef\xbb\xbf{"type":"compacted"}\n',
                    b'\xff\n{"type":"compacted"}\n',
                    b'{"type":"compacted","unused":"\xff"}\n',
                    b'{"type":"CHECKPOINT","content":123}\n'):
            self.parity(raw)

    def test_alignment_tail_window_fallback_and_unfinished_long_line(self):
        for length in (65535,65536,65537,70000):
            raw=b"header\n"+b"x"*length
            for fallback in (-1,0,7,8): self.parity(raw,fallback=fallback)
        self.parity(b"x"*70000+b"\n")
        self.parity(b"x"*70000+b"\npartial",fallback=4)

    def test_due_rewrite_equal_size_limit_and_offset_boundaries(self):
        row=b'{"type":"compacted"}\n'
        for offset in (0,1,len(row),len(row)+100):
            for count,limit in ((0,3),(3,3),(4,3),(0,0),(-1,0)):
                self.parity(row,offset=offset,count=count,limit=limit)
        self.path.write_bytes(row)
        self.assertIsNone(self.native("due",{"transcript_bytes":-1},self.path,3))
        with self.assertRaises((OSError,ValueError)) as expected:
            self.original("due_after_compaction",{"transcript_bytes":-1},self.path,3)
        with patch.dict(os.environ,self.env,clear=True), self.assertRaises(type(expected.exception)) as actual:
            reference._due_after_compaction({"transcript_bytes":-1},self.path,3)
        self.assertEqual(str(expected.exception),str(actual.exception))
        self.assertFalse(self.native("due",{"transcript_bytes":-1},self.path,0))

    def test_supported_bridge_executes_no_original_size_or_line_scan(self):
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(reference,"_size",side_effect=AssertionError("Python file scan")):
            self.assertTrue(reference._compacted_before(self.path))
            self.assertEqual(self.path.stat().st_size,reference._aligned_size(self.path))
            self.assertTrue(reference._due_after_compaction({"transcript_bytes":0},self.path))

    def test_missing_directory_and_regular_symlink_match_original(self):
        for path in (self.path,self.base):
            self.assertEqual(self.original("compacted_before",path),self.native("compacted",path))
            self.assertEqual(self.original("aligned_size",path),self.native("aligned",path,0))
            self.assertFalse(self.native("due",{"transcript_bytes":0},path,3))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        link=self.base/"regular-link"; link.symlink_to(self.path)
        self.assertTrue(self.native("compacted",link))
        self.assertEqual(self.path.stat().st_size,self.native("aligned",link,0))

    def test_source_or_environment_refusal_is_quiet_and_read_only(self):
        self.path.write_bytes(b'{"type":"compacted"}\n')
        before=self.path.read_bytes()
        for env in ({"PYTHONVERBOSE":"1"},{"MORU_HOME":str(self.project)}):
            self.assertEqual((125,b"",b""),result(self.raw("compacted",**env)))
        for operation,payload in (("unknown",{}),("aligned",{"path":str(self.path),"fallback":True}),
                                  ("due",{"path":str(self.path),"offset":0,"redeliveries":0,"limit":3,"extra":1})):
            self.assertEqual((125,b"",b""),result(self.raw(operation,payload)))
        self.assertEqual(before,self.path.read_bytes())

    def test_unsupported_byte_encoding_and_surrogate_use_original_fallback(self):
        special = b'"compacted"x'.decode("utf-16-be")
        raw=(json.dumps({"type":"compacted","content":special},ensure_ascii=False)+"\n").encode("utf-16-be")
        self.assertIn(b'"compacted"',raw)
        for data in (raw,b'{"type":"compacted","unused":"\\ud800"}\n',
                     b'{"type":"compacted","unused":"\xed\xa0\x80"}\n',
                     b'{"type":"compacted","unused":"\xed\xbf\xbf"}\n'):
            self.path.write_bytes(data)
            before=self.path.read_bytes()
            self.assertEqual((125,b"",b""),result(self.raw("compacted")))
            self.assertEqual((125,b"",b""),result(self.raw("due",{"path":str(self.path),
                "offset":0,"redeliveries":0,"limit":3})))
            with patch.dict(os.environ,self.env,clear=True):
                self.assertTrue(reference._compacted_before(self.path))
                self.assertTrue(reference._due_after_compaction({"transcript_bytes":0},self.path))
            self.assertEqual(before,self.path.read_bytes())

    def test_stream_refusal_does_not_consume_owned_pipe_or_inherited_file(self):
        fifo=self.base/"fifo"; os.mkfifo(fifo)
        for operation,fields in (("compacted",{}),("aligned",{"fallback":0}),
                                 ("due",{"offset":1,"redeliveries":0,"limit":3})):
            done=self.raw(operation,{"path":str(fifo),**fields})
            if operation=="due": self.assertEqual((125,b"",b""),result(done))
            else:
                # Source size0 can answer without opening a special file.
                if done.returncode==0:
                    self.assertEqual(b"",done.stderr)
                    value=json.loads(done.stdout)["result"]["value"]
                    self.assertIs(type(value),bool if operation=="compacted" else int)
                    self.assertEqual(False if operation=="compacted" else 0,value)
                else: self.assertEqual((125,b"",b""),result(done))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with self.path.open("rb",buffering=0) as handle:
            handle.read(3)
            for prefix in ("/dev/fd","/proc/self/fd"):
                if not Path(prefix).exists(): continue
                payload={"path":f"{prefix}/{handle.fileno()}"}
                done=subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                    "--doc-transcript-probe","compacted"], input=json.dumps(payload).encode(),
                    env=self.env,cwd=self.project,capture_output=True,pass_fds=(handle.fileno(),),timeout=8)
                self.assertEqual((125,b"",b""),result(done))
                self.assertEqual(3,os.lseek(handle.fileno(),0,os.SEEK_CUR))

    def test_bridge_rejects_malformed_packets_and_preserves_noninteger_profiles(self):
        self.path.write_bytes(b"a\n"+b"x"*70000)
        for value in (None,{}, {"value":1,"extra":0},{"value":True},{"value":-1}):
            with patch("support.native_doc_transcript.NativeProbe.request",return_value=value):
                self.assertIsNone(NativeDocTranscript.aligned(self.path,0))
        for fallback in (True,1.0,10**100):
            expected=self.original("aligned_size",self.path,fallback)
            with patch.dict(os.environ,self.env,clear=True):
                actual=reference._aligned_size(self.path,fallback)
            self.assertEqual(expected,actual); self.assertIs(type(expected),type(actual))

    def test_optional_availability_failures_preserve_original_results_and_order(self):
        for error in (PermissionError("unsearchable home"),RuntimeError("no home"),ValueError("bad home")):
            with patch("support.native_doc_transcript.NativeProbe.available",side_effect=error):
                self.assertFalse(reference._compacted_before(self.path))
                self.assertEqual(0,reference._aligned_size(self.path))
                self.assertFalse(reference._due_after_compaction({"transcript_bytes":0},self.path))
                # An invalid offset suppresses even invalid redelivery coercion.
                self.assertFalse(reference._due_after_compaction({"transcript_bytes":None,"redeliveries":"bad"},self.path))
        self.path.write_bytes(b'{"type":"compacted"}\n')
        with patch("support.native_doc_transcript.NativeProbe.available",side_effect=PermissionError("home")):
            self.assertTrue(reference._compacted_before(self.path))
            with self.assertRaises(ValueError):
                reference._due_after_compaction({"transcript_bytes":0,"redeliveries":"bad"},self.path)

    def test_search_only_ancestor_does_not_advance_partial_line_offset(self):
        directory=self.base/"search-only"; directory.mkdir()
        path=directory/"partial.jsonl"; path.write_bytes(b'partial compaction row')
        try:
            directory.chmod(0o111)
            expected=self.original("aligned_size",path,0)
            self.assertEqual(0,expected)
            with patch.dict(os.environ,self.env,clear=True):
                self.assertEqual(expected,reference._aligned_size(path,0))
            try: list(directory.iterdir())
            except PermissionError:
                self.assertIsNone(self.native("aligned",path,0))
            else:
                self.assertEqual(expected,self.native("aligned",path,0))
        finally: directory.chmod(0o700)

    def test_actual_native_scan_preserves_shared_delivery_markers_and_budgets(self):
        outcomes=[]
        for native in (False,True):
            fixture=delivery_fixtures.DeliveryTests(); fixture.setUp()
            try:
                env={**self.env,"MORU_LAUNCHER_BACKEND":"auto" if native else "python"}
                with patch.dict(os.environ,env,clear=True):
                    texts=[fixture._deliver(),fixture._deliver()]
                    for _ in range(reference.MAX_REDELIVERIES+1):
                        fixture._append({"type":"system","subtype":"compact_boundary"})
                        texts.extend((fixture._deliver(),fixture._deliver()))
                    marker=json.loads((fixture.evidence.parent/reference.MARKER).read_text())
                self.assertEqual(reference.MAX_REDELIVERIES,marker["redeliveries"])
                self.assertTrue(texts[0]); self.assertFalse(texts[1]); self.assertFalse(texts[-1])
                outcomes.append((texts,marker))
            finally: fixture.doCleanups()
        self.assertEqual(outcomes[0],outcomes[1])

    def test_actual_native_scan_preserves_agy_checkpoint_delivery(self):
        outcomes=[]
        for native in (False,True):
            fixture=agy_fixtures.AgyHookTests(); fixture.setUp()
            try:
                env={**self.env,"MORU_LAUNCHER_BACKEND":"auto" if native else "python"}
                with patch.dict(os.environ,env,clear=True):
                    first=fixture._hook(); self.assertTrue(first)
                    self.assertEqual({},fixture._hook())
                    fixture._append(agy_fixtures.CHECKPOINT,fixture._read_call(agy_fixtures.CORE))
                    after=fixture._hook(); self.assertTrue(after)
                    self.assertEqual({},fixture._hook())
                    marker=json.loads((fixture.evidence.parent/reference.MARKER).read_text())
                    outcomes.append((first,after,marker))
            finally: fixture.doCleanups()
        self.assertEqual(outcomes[0],outcomes[1])


if __name__=="__main__": unittest.main()
