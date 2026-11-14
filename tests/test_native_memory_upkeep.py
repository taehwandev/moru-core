"""Observe three upkeep kernels against pre-edit output and original decisions."""
import io
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "tests"))

import agent_project_memory as memory
import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe

TODAY = date(2026, 11, 13)


class NativeMemoryUpkeepTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-upkeep-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH":str(empty)}

    def record(self, name="a", **values):
        return {"id":name,"status":"active","body":"Same, advice","scope":"task",
                "source":"Docs!","review_on":"2099-01-01", **values}

    def call(self, operation, records, backend="auto", required=False):
        name = {"live":"_live_records", "replacements":"_unfinished_replacements",
                "startup":"startup_summary_line"}[operation]
        reference = {"startup":"_startup_summary_line_reference"}.get(operation, name+"_reference")
        with patch.dict(os.environ, {**self.env,"MORU_LAUNCHER_BACKEND":backend}, clear=True):
            def run():
                return (source.startup_summary_line(records, Path("project space"), "moru-hook", today=TODAY)
                        if operation == "startup" else getattr(source, name)(records))
            if required:
                with patch.object(source, reference, side_effect=AssertionError("Python upkeep replay")):
                    return run()
            return run()

    def parity(self, operation, records):
        expected = self.call(operation, records, "python")
        actual = self.call(operation, records, required=True)
        self.assertEqual(expected, actual)
        return actual

    def test_pre_edit_startup_text_and_replacement_projection_are_exact(self):
        records = [self.record("b",status="pending",scope="review",source="docs"),
                   self.record("a",review_on="2026-11-13"),
                   self.record("c",status="approved",scope="all",source="other",review_on="2026-11-12",replaces="a"),
                   {"id":"d","status":"retired"}]
        expected = "Project memory upkeep: expired=2 exact_duplicates=1 shared_source=1 unfinished=1 -> " \
                   "moru-hook project-memory --project 'project space' consolidate"
        self.assertEqual(expected, self.call("startup", records, required=True))
        actual = self.call("replacements", records[:3], required=True)
        entry = {"id":"a","scope":"task","body":"Same, advice","source":"Docs!",
                 "review_on":"2026-11-13","reason":"a live record replaces this one; `retire` it to finish "
                 "the interrupted replacement","replaced_by":["c"]}
        self.assertEqual([entry], actual)
        self.assertEqual(list(entry), list(actual[0]))

    def test_live_statuses_case_unicode_sort_and_equal_id_stability(self):
        marker = object()
        records = [self.record("𐀀"), self.record("a",status="pending",unused=marker),
                   self.record("a",status="approved"), self.record("0",status="retired"),
                   self.record("\ue000"), self.record("0",status="ACTIVE")]
        actual = self.parity("live", records)
        self.assertEqual([records[i] for i in (1,2,4,0)], actual)
        for expected, row in zip((records[i] for i in (1,2,4,0)), actual):
            self.assertIs(expected, row)
        self.assertIs(marker, actual[0]["unused"])

    def test_startup_all_bridge_disjoint_groups_and_empty_normalized_values(self):
        records = [self.record(str(i),scope=scope) for i,scope in enumerate(("task","task","review","review"))]
        self.assertIn("exact_duplicates=2", self.parity("startup", records))
        records[-1]["scope"] = "all"
        self.assertIn("exact_duplicates=1", self.parity("startup", records))
        records = [self.record("a",body="!!!",source="???"), self.record("b",body="?",source="")]
        result = self.parity("startup", records)
        self.assertIn("exact_duplicates=0 shared_source=1", result)

    def test_unicode_normalization_remains_the_original_python_callback(self):
        for left,right in (("ΟΣ","ος"),("Straße","STRASSE"),("é","é"),("İ","i"),("한글\u00a0abc!","한글 abc")):
            self.parity("startup", [self.record("a",body=left,source=left),self.record("b",body=right,source=right)])

    def test_startup_review_boundaries_and_legacy_live_statuses(self):
        records = [self.record(str(i),review_on=review,status=status,body=str(i),source=str(i))
                   for i,(review,status) in enumerate((("2026-11-12","active"),("2026-11-13","pending"),
                       ("2026-11-14","approved"),("2020-01-01","retired")))]
        self.assertIn("expired=2", self.parity("startup", records))

    def test_replacements_preserve_input_order_forks_duplicate_ids_and_metadata(self):
        marker = object()
        records = [self.record("b",replaces="a"),self.record("a",applies_when=marker),
                   self.record("c",replaces="a"),self.record("a",replaces="b",not_when=marker),
                   self.record("c",replaces="a"),self.record("orphan",replaces="absent")]
        actual = self.parity("replacements", records)
        self.assertEqual(["b","a","a"], [row["id"] for row in actual])
        self.assertEqual(["b","c","c"], actual[1]["replaced_by"])
        self.assertIs(marker, actual[1]["applies_when"])
        self.assertIs(marker, actual[2]["not_when"])

    def test_empty_reference_has_distinct_startup_and_finding_semantics(self):
        records = [self.record("",replaces=""),self.record("a",replaces=None)]
        self.assertEqual([], self.parity("replacements", records))
        self.assertIn("unfinished=1", self.parity("startup", records))

    def test_seeded_corpora_match_all_three_original_decisions(self):
        rng = random.Random(261113)
        for _ in range(24):
            records = [self.record(str(rng.randrange(4)),status=rng.choice(["active","pending","approved","retired"]),
                scope=rng.choice(["task","review","all"]),body=rng.choice(["a","A!","","b"]),
                source=rng.choice(["a","A!","","b"]),replaces=rng.choice([None,"","0","1","absent"]),
                review_on=rng.choice(["2026-11-12","2026-11-13","2099-01-01"])) for _ in range(rng.randrange(8))]
            for operation in ("live","replacements","startup"):
                self.parity(operation, records)

    def test_opaque_untransported_metadata_is_never_serialized(self):
        records = [self.record("a",unused=object(),applies_when="\ud800"),self.record("b",replaces="a")]
        for operation in ("live","replacements","startup"):
            self.parity(operation, records)

    def test_empty_inputs_start_no_native_requests(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty transport")):
            self.assertEqual([], self.call("live", [], required=True))
            self.assertEqual([], self.call("replacements", [], required=True))
            self.assertEqual("", self.call("startup", [], required=True))
            self.assertEqual("", self.call("startup", [{"status":"retired"}], required=True))

    def test_each_native_wiring_has_a_negative_control(self):
        records = [self.record("a"),self.record("b",replaces="a")]
        for operation, method in (("live","live"),("replacements","replacements"),("startup","startup")):
            self.call(operation, records, required=True)
            with patch.object(NativeMemoryUpkeep,method,return_value=None):
                with self.assertRaisesRegex(AssertionError,"Python upkeep replay"):
                    self.call(operation, records, required=True)

    def test_unavailable_startup_reuses_normalized_and_parsed_inputs_once(self):
        records = [self.record("a"),self.record("b",replaces="a")]
        expected = self.call("startup", records, "python")
        real_normalize = source.normalize
        real_date = date.fromisoformat
        with patch.dict(os.environ,self.env,clear=True), patch.object(NativeProbe,"request",return_value=None), \
             patch.object(source,"normalize",wraps=real_normalize) as normalized:
            class DateProbe:
                fromisoformat = staticmethod(real_date)
            with patch.object(source,"date",DateProbe):
                self.assertEqual(expected,source.startup_summary_line(records,Path("project space"),"moru-hook",today=TODAY))
        self.assertEqual(2*len(records), normalized.call_count)

    def test_missing_or_unreadable_native_binary_defers_before_preparation(self):
        records = [self.record("a"),self.record("b",replaces="a")]
        expected = self.call("startup",records,"python")
        for unavailable in (False,OSError("unreadable binary"),ValueError("unavailable profile"),RuntimeError("unavailable")):
            effect = {"side_effect":unavailable} if isinstance(unavailable,Exception) else {"return_value":False}
            with patch.object(NativeProbe,"available",**effect), \
                 patch.object(NativeProbe,"request",side_effect=AssertionError("unavailable request")), \
                 patch.object(source,"normalize",wraps=source.normalize) as normalized, \
                 patch.object(source,"date",wraps=date) as dates:
                self.assertEqual(expected,self.call("startup",records))
            self.assertEqual(2*len(records),normalized.call_count)
            self.assertEqual(len(records),dates.fromisoformat.call_count)

    def test_invalid_dates_keep_original_errors_after_native_validation_declines(self):
        for review in ("", "not-a-date", "2026-02-30"):
            records = [self.record(review_on=review)]
            try:
                self.call("startup",records,"python")
            except ValueError as expected:
                with self.assertRaises(ValueError) as actual:
                    self.call("startup",records)
                self.assertEqual(expected.args, actual.exception.args)

    def test_custom_and_malformed_profiles_keep_reference_errors(self):
        class Custom(str):
            def lower(self):
                raise RuntimeError("custom lower")
        for operation,records in (("live",[{}]),("live",[self.record(status=[])]),
                                  ("replacements",[self.record(replaces=["a"])]),
                                  ("replacements",[{}]),("startup",[self.record(body=Custom("x"))]),
                                  ("startup",[self.record(review_on=None)])):
            try:
                expected = self.call(operation, records, "python")
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.call(operation, records)
                self.assertEqual(error.args, actual.exception.args)
            else:
                self.assertEqual(expected,self.call(operation, records))

    def test_malformed_live_and_relation_packets_defer(self):
        records = [self.record("a"),self.record("b")]
        with patch.dict(os.environ,self.env,clear=True):
            for result in ({}, {"indices":[True]}, {"indices":[-1]}, {"indices":[2]},
                           {"indices":[0,0]}, {"indices":[1,0]}, {"indices":[],"extra":1}):
                with patch.object(NativeProbe,"request",return_value=result):
                    self.assertIsNone(NativeMemoryUpkeep.live(records,source.RECALLABLE_STATUSES))
            for items in (None,[{}],[{"index":True,"replacements":[1]}],[{"index":-1,"replacements":[1]}],
                          [{"index":0,"replacements":[]}],[{"index":0,"replacements":[1,1]}],
                          [{"index":1,"replacements":[0]},{"index":0,"replacements":[1]}]):
                with patch.object(NativeProbe,"request",return_value={"findings":items}):
                    self.assertIsNone(NativeMemoryUpkeep.replacements(records))

    def test_malformed_startup_counts_and_transport_errors_keep_original_output(self):
        records = [self.record("a")]
        expected = self.call("startup",records,"python")
        counts = dict.fromkeys(("expired","exact_duplicates","shared_source","unfinished"),0)
        for result in ({}, {"counts":None},{"counts":{**counts,"unfinished":True}},
                       {"counts":{**counts,"unfinished":2}},{"counts":{**counts,"extra":0}}):
            with patch.object(NativeProbe,"request",return_value=result):
                self.assertEqual(expected,self.call("startup",records))
        for error in (OSError("transport"),ValueError("transport"),RuntimeError("transport")):
            with patch.object(NativeProbe,"request",side_effect=error):
                self.assertEqual(expected,self.call("startup",records))

    def test_full_findings_preserve_date_decisions_projection_and_unreadable_count(self):
        records = [self.record("b",replaces="a"),self.record("a",review_on="2026-11-13"),
                   self.record("c",review_on="2026-11-20"),self.record("d",status="retired")]
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected = source.findings(records,2,today=TODAY)
        with patch.dict(os.environ,self.env,clear=True), \
             patch.object(source,"_live_records_reference",side_effect=AssertionError("Python live replay")), \
             patch.object(source,"_unfinished_replacements_reference",side_effect=AssertionError("Python link replay")):
            self.assertEqual(expected,source.findings(records,2,today=TODAY))

    def test_real_temporary_store_cli_and_startup_preserve_record_bytes(self):
        directory = self.base / "records"
        directory.mkdir()
        records = [self.record("a"*16,schema_version=1),self.record("b"*16,replaces="a"*16,schema_version=1)]
        for record in records:
            record["digest"] = memory._digest(record)
            path = directory/(record["id"]+".json")
            path.write_text(json.dumps(record),encoding="utf-8")
        before = {p.name:p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected = source.findings(records,0,today=date.today())
            for path in directory.iterdir():
                self.assertIsNotNone(memory.read_record(path))
        with patch.dict(os.environ,self.env,clear=True),patch.object(memory,"store_dir",return_value=directory), \
             patch.object(source,"_live_records_reference",side_effect=AssertionError("CLI live replay")), \
             patch.object(source,"_unfinished_replacements_reference",side_effect=AssertionError("CLI link replay")), \
             patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("startup replay")):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0,memory._main(["--project",str(self.project),"consolidate"]))
            self.assertEqual(expected,json.loads(output.getvalue()))
            self.assertIn("unfinished=1",source.startup_summary_line(records,self.project,"moru-hook",today=TODAY))
        self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
