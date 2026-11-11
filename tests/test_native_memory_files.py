"""Real native memory files/scans against the original reader; synthetic data only."""
from datetime import date
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unicodedata
import unittest
from unittest.mock import patch
import agent_project_memory as source
from native_pretool_support import environment,prepare,result
from support.native_memory import NativeMemory


class NativeMemoryFilesTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="native-memory-files-")
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.entry,self.project=prepare(self.base)
        empty=self.base/"empty"; empty.mkdir()
        self.env={**environment(self.base),"PATH":str(empty)}
        self.directory=self.base/"records"; self.directory.mkdir()
        self.path=self.directory/"0123456789abcdef.json"

    def record(self,**fields):
        value={"schema_version":1,"id":"0123456789abcdef","status":"active","scope":"task",
               "body":"프로필 화면; src/ui/ProfileScreen.kt","source":"checked source",
               "review_on":"2099-01-01",**fields}
        value["digest"]=source._digest(value)
        return value

    def write(self,value,path=None):
        path=path or self.path
        path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
        return path

    def native(self,operation,path=None):
        with patch.dict(os.environ,self.env,clear=True):
            return NativeMemory.files(operation,path or self.path)

    def original(self,path=None):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            return source.read_record(path or self.path)

    def parity(self,value):
        self.write(value)
        before=self.path.read_bytes()
        expected=self.original()
        actual=self.native("record")
        self.assertIsNotNone(actual)
        self.assertEqual(expected,actual["record"])
        if expected is not None:
            self.assertEqual(list(expected),list(actual["record"]))
        self.assertEqual(before,self.path.read_bytes())
        return actual["record"]

    def raw(self,operation,path,**options):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
            "--memory-probe",operation],input=json.dumps({"unicode":unicodedata.unidata_version,
            "path":str(path)}).encode(),capture_output=True,cwd=self.project,env=self.env,timeout=8,**options)

    def test_valid_fields_metadata_types_and_python_schema_equality(self):
        for schema in (1,True,1.0):
            value=self.record(schema_version=schema,created_at="unchanged",unknown={"z":[],"a":-0.0},
                extra=[None,False,1,1.0,2**63,2**64-1])
            actual=self.parity(value)
            self.assertIs(type(actual["schema_version"]),type(schema))
            for a,b in zip(value["extra"],actual["extra"]): self.assertIs(type(a),type(b))
        for replaces in (None,False,0,0.0,"",[],{},"a"*16): self.parity(self.record(replaces=replaces))

    def test_conditions_sources_analysis_and_canonical_digest_match(self):
        files=[{"blob":"b"*64,"path":"src/프로필.py"},{"path":"docs/schema.json","blob":"a"*40}]
        value=self.record(source_files=files,applies_when="when queue changes",not_when="not billing",
            analysis={"inputs":"c"*64,"context":"Exact Case != identity","question":"Can check fail?"})
        self.assertEqual(value,self.parity(value))
        for body in ('quotes " and \\ and tab words','한글 é e\u0301 😀 \u007f','line separator \u2028'):
            # Unprintable characters make a record invalid even with a valid digest.
            self.parity(self.record(body=body))

    def test_invalid_schema_fields_dates_names_and_integrity_are_rejected(self):
        variants=[{"schema_version":v} for v in (None,False,0,2,"1",[],{})]
        variants += [{key:value} for key,values in {
            "id":["A"*16,"a"*15,None],"status":["unknown",None,[]],"scope":["a","UPPER",None],
            "body":[None,"","x"*501,"line\nbreak"],"source":["","x"*201,None],
            "review_on":["1999-12-31","2000-02-30","2026-13-01"],
            "replaces":["bad",True,1,["x"]],"source_files":[[],None,[{"path":"a.py","blob":"A"*40}]],
            "applies_when":["",None,"x"*161],"not_when":["bad\nline"]}.items() for value in values]
        for fields in variants:
            with self.subTest(fields=fields): self.assertIsNone(self.parity(self.record(**fields)))
        for key in ("id","status","scope","body","source","review_on","digest"):
            value=self.record(); del value[key]
            self.assertIsNone(self.parity(value))
        value=self.record(); value["body"]="tampered"
        self.assertIsNone(self.parity(value))
        self.write(self.record(),self.directory/"wrong.json")
        self.assertEqual({"record":None},self.native("record",self.directory/"wrong.json"))

    def test_source_paths_analysis_and_duplicate_sources_preserve_validation(self):
        for path in ("../a.py",".git/config","a//b.py","./a.py","a/./b.py","a\\b.py","/a.py","a.py/","."):
            self.assertIsNone(self.parity(self.record(source_files=[{"path":path,"blob":"a"*40}])))
        files=[{"path":"src/a.py","blob":"a"*40}]
        self.assertIsNone(self.parity(self.record(source_files=files*2)))
        self.assertIsNone(self.parity(self.record(source_files=files*5)))
        for analysis in (None,{}, {"question":" q","context":"c","inputs":"a"*64},
            {"question":"q","context":"c ","inputs":"a"*64},
            {"question":"q","context":"c","inputs":"bad"},
            {"question":"q","context":"c","inputs":"a"*64,"extra":1}):
            self.assertIsNone(self.parity(self.record(source_files=files,analysis=analysis)))
        self.assertIsNone(self.parity(self.record(analysis={"question":"q","context":"c","inputs":"a"*64})))

    def test_byte_decoder_invalid_rows_bom_newlines_duplicates_and_unknown_types(self):
        for raw in (b"",b"\xff",b"\xef\xbb\xbf{}",b"[]",b"null",b"{bad}",b'{"x":1,}'):
            self.path.write_bytes(raw)
            self.assertEqual({"record":self.original()},self.native("record"))
        text=json.dumps(self.record(),ensure_ascii=False)
        self.path.write_bytes((text.replace(', ',',\r\n')+'\r\n').encode())
        self.assertEqual({"record":self.original()},self.native("record"))
        self.path.write_text(text[:-1]+',"status":"retired","schema_version":true}',encoding="utf-8")
        expected=self.original(); actual=self.native("record")["record"]
        self.assertEqual(expected,actual); self.assertEqual(list(expected),list(actual))
        self.assertIs(type(actual["schema_version"]),bool)

    def test_sorted_directory_scan_counts_bad_hidden_directory_and_symlink_entries(self):
        a=self.record(id="a"*16); b=self.record(id="b"*16)
        self.write(b,self.directory/("b"*16+".json")); self.write(a,self.directory/("a"*16+".json"))
        for name in ("broken.json",".hidden.json"): (self.directory/name).write_text("bad")
        self.write(a,self.directory/"mismatch.json")
        (self.directory/"directory.json").mkdir()
        (self.directory/"linked.json").symlink_to(self.directory/("a"*16+".json"))
        (self.directory/"ignored.JSON").write_text("bad")
        before={p.name:p.lstat().st_ino for p in self.directory.iterdir()}
        with patch.object(source,"store_dir",return_value=self.directory), \
             patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=source.scan_records(self.project)
        self.assertEqual(([a,b],5),expected)
        self.assertEqual({"records":expected[0],"unreadable":expected[1]},self.native("scan",self.directory))
        self.assertEqual(before,{p.name:p.lstat().st_ino for p in self.directory.iterdir()})

    def test_actual_helpers_do_not_replay_python_file_read_digest_or_scan(self):
        value=self.record(); self.write(value)
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(Path,"read_text",side_effect=AssertionError("Python file read")), \
             patch.object(source,"_digest",side_effect=AssertionError("Python digest replay")):
            self.assertEqual(value,source.read_record(self.path))
            with patch.object(source,"store_dir",return_value=self.directory), \
                 patch.object(source,"read_record",side_effect=AssertionError("Python record loop")):
                self.assertEqual(([value],0),source.scan_records(self.project))

    def test_missing_directory_and_final_symlinks_preserve_empty_results(self):
        self.assertEqual({"record":None},self.native("record"))
        self.assertEqual({"records":[],"unreadable":0},self.native("scan",self.directory/"missing"))
        self.assertEqual({"records":[],"unreadable":0},self.native("scan",self.path))
        self.write(self.record()); link=self.base/"alias.json"; link.symlink_to(self.path)
        self.assertEqual({"record":None},self.native("record",link))
        directory_link=self.base/"directory-link"; directory_link.symlink_to(self.directory)
        self.assertEqual({"records":[],"unreadable":0},self.native("scan",directory_link))

    def test_ancestor_symlink_search_only_directory_and_large_record_defer(self):
        value=self.record(); self.write(value)
        alias=self.base/"ancestor"; alias.symlink_to(self.directory)
        self.assertIsNone(self.native("record",alias/self.path.name))
        with patch.dict(os.environ,self.env,clear=True): self.assertEqual(value,source.read_record(alias/self.path.name))
        try:
            self.directory.chmod(0o111)
            expected=self.original()
            with patch.dict(os.environ,self.env,clear=True): self.assertEqual(expected,source.read_record(self.path))
        finally: self.directory.chmod(0o700)
        value=self.record(unused="x"*(1024*1024)); self.write(value)
        self.assertIsNone(self.native("record"))
        with patch.dict(os.environ,self.env,clear=True): self.assertEqual(value,source.read_record(self.path))

    def test_fifo_and_inherited_descriptor_queries_decline_without_consumption(self):
        fifo=self.directory/"fifo.json"; os.mkfifo(fifo)
        self.assertEqual((125,b"",b""),result(self.raw("record",fifo)))
        self.assertEqual((125,b"",b""),result(self.raw("scan",self.directory)))
        self.write(self.record())
        with self.path.open("rb",buffering=0) as handle:
            handle.read(3)
            for prefix in ("/dev/fd","/proc/self/fd"):
                if not Path(prefix).exists(): continue
                done=self.raw("record",Path(prefix)/str(handle.fileno()),pass_fds=(handle.fileno(),))
                self.assertIn(result(done),((125,b"",b""),(0,b'{"schema_version":1,"result":{"record":null}}\n',b"")))
                self.assertEqual(3,os.lseek(handle.fileno(),0,os.SEEK_CUR))

    def test_unsupported_values_and_profile_preserve_original_fallback(self):
        for extra in (float("nan"),float("inf"),2**100,"\ud800"):
            value=self.record(unused=extra)
            self.path.write_text(json.dumps(value),encoding="utf-8")
            self.assertIsNone(self.native("record"))
            with patch.dict(os.environ,self.env,clear=True):
                actual=source.read_record(self.path)
            self.assertEqual(list(value),list(actual)); self.assertEqual(value["digest"],actual["digest"])
        value=self.record(review_on="20990101"); self.write(value)
        self.assertIsNone(self.native("record"))
        expected=self.original()
        with patch.dict(os.environ,self.env,clear=True): self.assertEqual(expected,source.read_record(self.path))

    def test_bridge_malformed_packets_and_optional_availability_failures(self):
        for response in (None,{}, {"record":[]},{"record":None,"extra":0}):
            with patch("support.native_memory.NativeProbe.request",return_value=response):
                self.assertIsNone(NativeMemory.files("record",self.path))
        for response in ({"records":[],"unreadable":True},{"records":[None],"unreadable":0},
                         {"records":[],"unreadable":-1},{"records":[],"unreadable":0,"extra":0}):
            with patch("support.native_memory.NativeProbe.request",return_value=response):
                self.assertIsNone(NativeMemory.files("scan",self.directory))
        value=self.record(); self.write(value)
        for error in (PermissionError("home"),RuntimeError("home"),ValueError("home")):
            with patch("support.native_memory.NativeProbe.available",side_effect=error):
                self.assertEqual(value,source.read_record(self.path))


if __name__=="__main__": unittest.main()
