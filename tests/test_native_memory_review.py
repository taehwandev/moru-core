"""Observe strict date buckets, fused inputs and original calendar compatibility."""
import io
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest.mock import patch

# Also allow the fixed repair verifier's dotted selector from the repo root.
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "tests"))

import agent_project_memory as memory
import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_review import NativeMemoryReview
from support.native_probe_transport import NativeProbe

TODAY = date(2026,11,13)
HORIZON = TODAY + timedelta(days=14)


class NativeMemoryReviewTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="native-memory-review-")
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.entry,self.project=prepare(self.base)
        empty=self.base/"empty";empty.mkdir()
        self.env={**environment(self.base),"PATH":str(empty)}

    def record(self,name="a",**values):
        return {"id":name,"status":"active","body":"body "+str(name),"source":"source "+str(name),
                "scope":"task","review_on":"2099-01-01",**values}

    def buckets(self,records,backend="auto",required=False,today=TODAY,horizon=HORIZON):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            if required:
                with patch.object(source,"_review_buckets_reference",side_effect=AssertionError("Python date replay")):
                    return tuple(list(bucket) for bucket in source._review_buckets(records,today,horizon))
            return tuple(list(bucket) for bucket in source._review_buckets(records,today,horizon))

    def report(self,records,backend="auto",required=False,today=TODAY,days=14):
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":backend},clear=True):
            if required:
                with patch.object(source,"_live_records",side_effect=AssertionError("Python live prefix replay")), \
                     patch.object(source,"_review_buckets_reference",side_effect=AssertionError("Python date replay")):
                    return source.findings(records,2,today=today,within_days=days)
            return source.findings(records,2,today=today,within_days=days)

    def test_captured_pre_edit_full_report_boundaries_and_key_order(self):
        records=[self.record(name,status=status,review_on=review,body="body"+str(i),source="source"+str(i))
                 for i,(name,status,review) in enumerate((("b","pending","2026-11-13"),
                    ("a","active","2026-11-12"),("e","approved","2026-11-28"),
                    ("d","active","2026-11-27"),("a","active","2026-12-01"),
                    ("c","active","2026-11-14"),("retired","retired","invalid")))]
        actual=self.report(records,required=True)
        self.assertEqual(["b"],[r["id"] for r in actual["expired"]])
        self.assertEqual(["c","d"],[r["id"] for r in actual["expiring"]])
        expected={"id":"b","scope":"task","body":"body0","source":"source0",
                  "review_on":"2026-11-13","reason":"review date reached; recheck the source, then renew with "
                  "`capture --replaces` and a new date, or `retire`"}
        self.assertEqual(expected,actual["expired"][0])
        self.assertEqual(list(expected),list(actual["expired"][0]))
        self.assertEqual(["today","within_days","expired","expiring","duplicate_groups", "shared_source_groups",
                          "unfinished_replacements","unreadable"],list(actual))
        self.assertEqual(self.report(records,"python"),actual)

    def test_partition_preserves_unsorted_order_original_objects_and_duplicate_last_date(self):
        marker=object()
        records=[self.record("z",review_on="2026-11-13",applies_when=marker),
                 self.record("a",review_on="2026-11-12"),self.record("b",review_on="2026-11-27"),
                 self.record("a",review_on="2026-12-01")]
        expected=self.buckets(records,"python")
        actual=self.buckets(records,required=True)
        self.assertEqual(expected,actual)
        self.assertIs(records[0],actual[0][0]);self.assertIs(records[2],actual[1][0])
        self.assertIs(marker,actual[0][0]["applies_when"])

    def test_fused_inputs_use_one_native_request_without_live_or_date_replay(self):
        records=[self.record("b",review_on="2026-11-13"),self.record("a",review_on="2026-11-27")]
        real_request=NativeProbe.request
        with patch.dict(os.environ,self.env,clear=True),patch.object(NativeProbe,"request",wraps=real_request) as requested:
            actual=NativeMemoryReview.findings_inputs(records,TODAY,14,source.RECALLABLE_STATUSES)
        self.assertEqual(1,requested.call_count)
        self.assertEqual("review-findings",requested.call_args.args[1])
        self.assertIs(records[1],actual[0][0]);self.assertIs(records[0],actual[1][0])
        self.assertEqual(self.report(records,"python"),self.report(records,required=True))

    def test_fused_statuses_keep_legacy_values_case_and_retired_invalid_dates(self):
        records=[self.record(str(i),status=status,review_on="2026-11-13" if status!="retired" else None)
                 for i,status in enumerate(("active","pending","approved","retired","ACTIVE"))]
        self.assertEqual(self.report(records,"python"),self.report(records,required=True))
        self.assertEqual(["0","1","2"],[r["id"] for r in self.report(records,required=True)["expired"]])

    def test_equal_id_ties_and_untransported_metadata_survive_fused_selection(self):
        marker=object()
        records=[self.record("x",review_on="2026-11-13",applies_when=marker,unused="\ud800"),
                 self.record("x",review_on="2026-11-13",not_when=marker)]
        actual=self.report(records,required=True)
        self.assertIs(marker,actual["expired"][0]["applies_when"])
        self.assertIs(marker,actual["expired"][1]["not_when"])

    def test_seeded_full_report_and_partition_match_original_date_rules(self):
        rng=random.Random(261114)
        for _ in range(24):
            records=[self.record(str(rng.randrange(4)),status=rng.choice(["active","pending","approved","retired"]),
                review_on=rng.choice(["2026-11-12","2026-11-13","2026-11-14","2026-11-27","2099-01-01"]))
                for _ in range(rng.randrange(8))]
            self.assertEqual(self.report(records,"python"),self.report(records,required=True))
            self.assertEqual(self.buckets(records,"python"),self.buckets(records,required=True))

    def test_leap_centuries_and_supported_calendar_limits(self):
        for review in ("0001-01-01","2000-02-29","2024-02-29","9999-12-31"):
            records=[self.record(review_on=review)]
            self.assertEqual(self.buckets(records,"python"),self.buckets(records,required=True))
        records=[self.record(review_on="9999-12-31")]
        self.assertEqual(self.report(records,"python",today=date.max,days=0),
                         self.report(records,required=True,today=date.max,days=0))

    def test_zero_and_reverse_private_horizons_keep_original_buckets(self):
        records=[self.record("a",review_on="2026-11-13"),self.record("b",review_on="2026-11-14")]
        for horizon in (TODAY,TODAY-timedelta(days=1)):
            self.assertEqual(self.buckets(records,"python",horizon=horizon),self.buckets(records,required=True,horizon=horizon))

    def test_empty_reports_and_partitions_start_no_native_requests(self):
        with patch.object(NativeProbe,"request",side_effect=AssertionError("empty transport")):
            self.assertEqual(([],[]),self.buckets([],required=True))
            self.assertEqual([],self.report([],required=True)["expired"])

    def test_pre_edit_error_priority_is_preserved(self):
        cases=[([{}],date.max,1,KeyError,("status",)),([],date.max,1,OverflowError,("date value out of range",)),
               ([self.record()],date.max,1,OverflowError,("date value out of range",)),
               ([{}],TODAY,-1,ValueError,("--within-days must not be negative",))]
        for records,today,days,kind,args in cases:
            for backend in ("python","auto"):
                with self.assertRaises(kind) as caught:self.report(records,backend,today=today,days=days)
                self.assertEqual(args,caught.exception.args)

    def test_invalid_and_extended_date_formats_keep_current_interpreter_behavior(self):
        for review in ("1900-02-29","2100-02-29","2026-04-31","20261113","2026-W46-5", "٢٠٢٦-11-13","",None,13):
            records=[self.record(review_on=review)]
            try: expected=self.report(records,"python")
            except Exception as error:
                with self.assertRaises(type(error)) as caught:self.report(records)
                self.assertEqual(error.args,caught.exception.args)
            else:self.assertEqual(expected,self.report(records))

    def test_custom_calendar_parser_is_not_bypassed(self):
        records=[self.record("b",review_on="2026-11-13"),self.record("a",review_on="2026-11-27")]
        class Calendar:
            fromisoformat=staticmethod(date.fromisoformat)
        with patch.object(source,"date",Calendar),patch.object(Calendar,"fromisoformat",wraps=date.fromisoformat) as parsed, \
             patch.object(NativeMemoryReview,"findings_inputs",side_effect=AssertionError("custom fused calendar")), \
             patch.object(NativeMemoryReview,"partition",side_effect=AssertionError("custom partition calendar")):
            actual=self.report(records)
        self.assertEqual(len(records),parsed.call_count)
        self.assertEqual(self.report(records,"python"),actual)

    def test_custom_delta_keeps_live_validation_before_horizon_failure(self):
        def rejected_delta(**fields):raise RuntimeError("custom calendar delta")
        with patch.object(source,"timedelta",rejected_delta):
            with self.assertRaisesRegex(KeyError,"status"):self.report([{}])
            with self.assertRaisesRegex(RuntimeError,"custom calendar delta"):self.report([self.record()])

    def test_custom_projection_still_precedes_later_expiring_comparisons(self):
        # Confirmed against the pre-edit implementation at dc61c7c7.
        class Record(dict):
            def __getitem__(self,key):
                if key=="body":raise RuntimeError("projection first")
                return super().__getitem__(key)
        class Day(date):
            def __lt__(self,other):raise AssertionError("expiring comparison first")
        records=[Record(self.record(review_on="2026-11-13"))]
        for backend in ("python","auto"):
            with self.assertRaisesRegex(RuntimeError,"projection first"):
                self.report(records,backend,today=Day(2026,11,13))

    def test_noninteger_windows_keep_original_projection_and_errors(self):
        records=[self.record("a",review_on="2026-11-14")]
        for days in (True,0.5,1.5):
            self.assertEqual(self.report(records,"python",days=days),self.report(records,days=days))

    def test_custom_and_malformed_record_profiles_keep_reference_errors(self):
        for records in ([{}],[self.record(status=[])],[self.record(id=[])],
                        [self.record("a"),self.record(1)],[{"status":"retired","review_on":object()}]):
            try:expected=self.report(records,"python")
            except Exception as error:
                with self.assertRaises(type(error)) as caught:self.report(records)
                self.assertEqual(error.args,caught.exception.args)
            else:self.assertEqual(expected,self.report(records))

    def test_bad_index_packets_defer_without_replacing_original_objects(self):
        records=[self.record("a"),self.record("b")]
        packets=[{}, {"live":[0,1],"expired":[True],"expiring":[]},
                 {"live":[0,1],"expired":[-1],"expiring":[]},{"live":[0,1],"expired":[2],"expiring":[]},
                 {"live":[0,1],"expired":[0,0],"expiring":[]},{"live":[0,1],"expired":[1,0],"expiring":[]},
                 {"live":[0,1],"expired":[0],"expiring":[0]},{"live":[True,1],"expired":[],"expiring":[]},
                 {"live":[0,0],"expired":[],"expiring":[]},{"live":[1,0],"expired":[],"expiring":[]}]
        with patch.dict(os.environ,self.env,clear=True):
            for packet in packets:
                with patch.object(NativeProbe,"request",return_value=packet):
                    self.assertIsNone(NativeMemoryReview.partition(records,TODAY,HORIZON))
                    self.assertIsNone(NativeMemoryReview.findings_inputs(records,TODAY,14,source.RECALLABLE_STATUSES))

    def test_transport_failures_keep_original_full_report(self):
        records=[self.record(review_on="2026-11-13")]
        expected=self.report(records,"python")
        with patch.object(NativeMemoryReview,"_request",return_value=None):
            self.assertEqual(expected,self.report(records))
        for error in (OSError("transport"),ValueError("transport"),RuntimeError("transport")):
            with patch.object(NativeProbe,"request",side_effect=error):
                self.assertEqual(expected,self.report(records))

    def test_both_new_callers_have_negative_wiring_controls(self):
        records=[self.record(review_on="2026-11-13")]
        self.buckets(records,required=True);self.report(records,required=True)
        with patch.object(NativeMemoryReview,"partition",return_value=None):
            with self.assertRaisesRegex(AssertionError,"Python date replay"):self.buckets(records,required=True)
        with patch.object(NativeMemoryReview,"findings_inputs",return_value=None):
            with self.assertRaisesRegex(AssertionError,"Python live prefix replay"):self.report(records,required=True)

    def test_real_temporary_store_cli_preserves_full_report_and_record_bytes(self):
        directory=self.base/"records";directory.mkdir()
        rows=[self.record("a"*16,review_on="2026-11-13",schema_version=1),
              self.record("b"*16,review_on="2099-01-01",schema_version=1,replaces="a"*16)]
        for record in rows:
            record["digest"]=memory._digest(record)
            (directory/(record["id"]+".json")).write_text(json.dumps(record),encoding="utf-8")
        before={p.name:p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            expected=source.findings(rows,0,today=date.today())
            for path in directory.iterdir():self.assertIsNotNone(memory.read_record(path))
        with patch.dict(os.environ,self.env,clear=True),patch.object(memory,"store_dir",return_value=directory), \
             patch.object(source,"_live_records",side_effect=AssertionError("CLI live prefix replay")), \
             patch.object(source,"_review_buckets_reference",side_effect=AssertionError("CLI date replay")):
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(0,memory._main(["--project",str(self.project),"consolidate"]))
            self.assertEqual(expected,json.loads(output.getvalue()))
        self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
