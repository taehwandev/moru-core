"""Source oracles for memory lexical analysis, ranking and negative authority."""
from datetime import date
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unicodedata
import unittest
from unittest.mock import patch
import agent_project_memory as source
from native_pretool_support import environment, prepare, result
from support.native_memory import NativeMemory


class NativeMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="native-memory-")
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.entry,self.project=prepare(self.base)
        empty=self.base/"empty"; empty.mkdir()
        self.env={**environment(self.base),"PATH":str(empty)}
        self.today=date(2026,11,9)

    def raw(self, operation, payload, **env):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
            "--memory-probe",operation],input=json.dumps(payload).encode(),cwd=self.project,
            env={**self.env,**env},capture_output=True,timeout=8)

    def terms(self,text):
        done=self.raw("terms",{"unicode":unicodedata.unidata_version,"text":text})
        self.assertEqual((0,b""),(done.returncode,done.stderr),done)
        value=json.loads(done.stdout)["result"]
        return tuple(set(value[key]) for key in ("words","paths","modules"))

    def record(self,id="a",body="retry_queue guidance",**fields):
        return {"id":id,"body":body,"source":"checked source","status":"active",
                "scope":"task","review_on":"2027-01-01",**fields}

    def parity(self,records,request="",scope="task",**kwargs):
        before=copy.deepcopy(records)
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=source._recall(self.project,scope,today=self.today,records=records,request=request,**kwargs)
        with patch.dict(os.environ,self.env,clear=True):
            actual=NativeMemory.recall(scope,self.today,records,request,
                kwargs.get("target_summary",""),kwargs.get("target_paths",()))
        self.assertIsNotNone(actual); self.assertEqual(expected,actual)
        for a,b in zip(actual,expected): self.assertIs(a,b)
        self.assertEqual(before,records)
        return actual

    def test_source_terms_paths_identifiers_korean_and_casefold(self):
        for text in (""," ","src/main/kotlin/ProfileScreen.kt","../src/./queue.py.",
            "/root/repo/src/retry_queue.py","././a/b.py...","../..","foo.py.json",
            "---foo-bar--- _private camelCase lowerUPPER","foo///bar.py","a.b-c.py",
            "아이 아이랑 차이랑 프로필에서는 화면으로는 프로필을","straße İ ı ΣςΣ ẞ K",
            "Ⅳ ² ¼ 𐐀𐐨 e\u0301 é hello\x1fworld","src/.hidden src/..x foo/.."):
            with self.subTest(text=text): self.assertEqual(source._terms(text),self.terms(text))

    def test_seeded_mixed_script_lexical_corpus(self):
        rng=random.Random(92061)
        alphabet=list("abcDEF09_./- ßİΣς가프로필은랑")+["\u0301","²","Ⅳ","𐐀","\x1c"]
        for _ in range(80):
            text="".join(rng.choice(alphabet) for _ in range(rng.randrange(1,100)))
            self.assertEqual(source._terms(text),self.terms(text),repr(text))

    def test_scope_expiry_replacement_and_stable_ties(self):
        records=[self.record("general",scope="all"),self.record("a"),self.record("b"),
            self.record("expired",review_on="2026-11-09"),self.record("foreign",scope="review"),
            self.record("old"),self.record("retired",status="retired",replaces="old"),
            self.record("pending",status="pending"),self.record("approved",status="approved")]
        for context in (""," \t\x1c","retry_queue","nothing useful"): self.parity(records,context)

    def test_weighted_paths_modules_context_and_korean(self):
        records=[self.record("generic","Fix dispatcher worker errors failed slow"),
            self.record("queue","Check src/dispatch/retry_queue.py.",scope="all"),
            self.record("korean","프로필 화면에서 닉네임 null 크래시",scope="all"),
            self.record("other","Keep app/src/main/java/com/example/shop/data/dto/FeedData.kt nullable"),
            self.record("profile","Profile screen crash; guard ProfileScreen",scope="all")]
        for context in ("Fix dispatcher worker errors failed slow retry_queue","프로필에서는 왜 죽나",
            "Fix crash app/src/main/java/com/example/shop/ui/profile/ProfileScreen.kt"): self.parity(records,context)
        for kwargs in ({"target_summary":"dispatch"},{"target_paths":("/absolute/src/dispatch/retry_queue.py",)},
            {"target_paths":(Path("src/dispatch/retry_queue.py"),)}): self.parity(records,**kwargs)

    def test_exceptions_and_superseded_bodies_are_not_positive_matches(self):
        records=[self.record("a","primary",not_when="retry_queue"),
            self.record("b","primary",applies_when="retry_queue"),self.record("old","retry_queue"),
            self.record("new","different",replaces="old"),
            self.record("file","different",source_files=[{"path":"src/retry_queue.py","blob":"x"}])]
        self.assertEqual(["b","file"],[r["id"] for r in self.parity(records,"retry_queue")])

    def test_duplicate_ids_keep_final_dictionary_score_and_original_objects(self):
        for records in ([self.record("same","retry_queue"),self.record("same","other")],
            [self.record("same","other"),self.record("same","retry_queue")]): self.parity(records,"retry_queue")

    def test_real_caller_does_not_replay_python_lexical_or_ranking(self):
        records=[self.record("a"),self.record("b","other")]
        with patch.dict(os.environ,self.env,clear=True), \
            patch.object(source,"_terms",side_effect=AssertionError("Python terms replay")), \
            patch.object(source,"_relevance",side_effect=AssertionError("Python score replay")):
            selected=source._recall(self.project,"task",today=self.today,records=records,request="retry_queue")
        self.assertEqual([records[0]],selected); self.assertIs(records[0],selected[0])

    def test_malformed_values_keep_original_errors_and_short_circuit_order(self):
        for fields in ({"review_on":"2026-02-30"},{"body":None},{"replaces":[]},
                       {"source_files":None},{"applies_when":None}):
            records=[self.record(**fields)]
            with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
                with self.assertRaises(Exception) as expected:
                    source._recall(self.project,"task",today=self.today,records=records,request="x")
            with patch.dict(os.environ,self.env,clear=True):
                with self.assertRaises(type(expected.exception)) as actual:
                    source._recall(self.project,"task",today=self.today,records=records,request="x")
            self.assertEqual(str(expected.exception),str(actual.exception))
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual([],source._recall(self.project,"task",today=self.today,
                records=[self.record(status="retired",review_on="bad",body=None)]))

    def test_invalid_responses_and_optional_availability_failure_defer(self):
        records=[self.record()]
        for response in (None,{}, {"indices":[],"extra":0},{"indices":[True]},
            {"indices":[-1]},{"indices":[1]},{"indices":[0,0]},{"indices":"0"}):
            with patch("support.native_memory.NativeProbe.request",return_value=response):
                self.assertIsNone(NativeMemory.recall("task",self.today,records,"","",()))
        for error in (PermissionError("home"),RuntimeError("home"),ValueError("home")):
            with patch("support.native_memory.NativeProbe.available",side_effect=error):
                self.assertEqual(records,source._recall(self.project,"task",today=self.today,records=records))

    def test_protocol_refusals_are_quiet_and_create_no_local_state(self):
        before=sorted(p.relative_to(self.base).as_posix() for p in self.base.rglob("*"))
        for operation,payload,env in (("terms",{"unicode":"unknown","text":"x"},{}),
            ("capture",{},{}),("terms",{"unicode":unicodedata.unidata_version,"text":"x","extra":1},{}),
            ("terms",{"unicode":unicodedata.unidata_version,"text":"x"},{"PYTHONPATH":"custom"})):
            self.assertEqual((125,b"",b""),result(self.raw(operation,payload,**env)))
        self.assertEqual(before,sorted(p.relative_to(self.base).as_posix() for p in self.base.rglob("*")))

    def test_other_unicode_profiles_custom_objects_and_deep_unused_data_fall_back(self):
        records=[self.record()]
        with patch.dict(os.environ,self.env,clear=True), \
            patch("support.native_memory.unicodedata.unidata_version","unsupported"):
            self.assertIsNone(NativeMemory.recall("task",self.today,records,"retry_queue","",()))
            self.assertEqual(records,source._recall(self.project,"task",today=self.today,records=records,
                                                  request="retry_queue"))
        class Custom:
            def __str__(self): raise AssertionError("unused object coerced")
        for unused in (Custom(),"\ud800",float("inf")):
            records=[self.record(unused=unused)]
            with patch.dict(os.environ,self.env,clear=True):
                self.assertEqual(records,source._recall(self.project,"task",today=self.today,records=records))
        deep=[]
        for _ in range(100): deep=[deep]
        records=[self.record(unused=deep)]
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(records,source._recall(self.project,"task",today=self.today,records=records))


if __name__=="__main__": unittest.main()
