"""Observe exact consolidation groups, source normalization and report authority."""
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

import agent_project_memory as memory
import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_consolidation import NativeMemoryConsolidation


class ConsolidationReportGroupsTests(unittest.TestCase):
    def records(self):
        return [{"id":name,"body":"one two","scope":"task","source":"Guide!",
                 "status":"active","review_on":"2099-01-01"} for name in ("b","a")]

    def test_complete_report_uses_one_request_for_dates_groups_and_relations(self):
        records = self.records()
        records[0].update(review_on="2026-11-16",replaces="a")
        marker = object()
        records[1]["applies_when"] = marker
        with patch("support.native_memory_consolidation.NativeProbe.available",return_value=False):
            expected = source.findings(records,2,today=date(2026,11,16))
        def request(flag,operation,payload):
            self.assertEqual("report-text-groups",operation,"date selection is still separate")
            self.assertEqual({"today":"2026-11-16","horizon":"2026-11-30",
                              "statuses":sorted(source.RECALLABLE_STATUSES),"render_days":14},payload["review"])
            return {"review":{"live":[1,0],"expired":[0],"expiring":[]},
                    "date_entries":{"expired":[{"id":"wrong"}],"expiring":[]},
                    "relations":{"duplicates":[[0,1]],"shared_sources":[[0,1]],
                                 "findings":[{"index":0,"replacements":[1]}]}}
        with patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
             patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request) as probe:
            actual = source.findings(records,2,today=date(2026,11,16))
        self.assertEqual(1,probe.call_count)
        self.assertEqual(expected,actual)
        self.assertEqual(list(expected),list(actual))
        self.assertIs(marker,actual["unfinished_replacements"][0]["applies_when"])

    def test_invalid_full_plan_uses_original_report_without_more_native_attempts(self):
        records = self.records()
        records[0].update(review_on="2026-11-16",replaces="a")
        with patch("support.native_memory_consolidation.NativeProbe.available",return_value=False):
            expected = source.findings(records,2,today=date(2026,11,16))
        good = {"review":{"live":[1,0],"expired":[0],"expiring":[]},
                "relations":{"duplicates":[[0,1]],"shared_sources":[[0,1]],
                             "findings":[{"index":0,"replacements":[1]}]}}
        for reply in (None,{}, {**good,"extra":True},
                      {**good,"review":{"live":[True],"expired":[],"expiring":[]}},
                      {**good,"relations":{"duplicates":[],"shared_sources":[],
                                           "findings":[{"index":3,"replacements":[0]}]}}):
            with self.subTest(reply=reply), \
                 patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
                 patch("support.native_memory_consolidation.NativeProbe.request",return_value=reply) as probe:
                self.assertEqual(expected,source.findings(records,2,today=date(2026,11,16)))
                self.assertEqual(1,probe.call_count)
        with patch("support.native_memory_consolidation.NativeProbe.request",side_effect=AssertionError("empty transport")):
            self.assertEqual([],source.findings([],0,today=date(2026,11,16))["expired"])
            with self.assertRaises(OverflowError):source.findings([],0,today=date.max,within_days=1)

    def test_custom_projection_fields_still_run_before_group_classification(self):
        class Fields:
            def __iter__(self): raise RuntimeError("projection first")
        records = self.records()
        records[0]["review_on"] = "2026-11-16"
        def request(flag,operation,payload):
            self.assertEqual("review-findings",operation)
            return {"live":[1,0],"expired":[0],"expiring":[]}
        with patch.object(source,"_DECISION_FIELDS",Fields()), \
             patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request) as probe:
            with self.assertRaisesRegex(RuntimeError,"projection first"):
                source.findings(records,0,today=date(2026,11,16))
        self.assertEqual(1,probe.call_count)

    def test_report_combines_replacements_with_groups_without_another_request(self):
        records = self.records()
        records[0]["replaces"] = "a"
        marker = object()
        records[1]["applies_when"] = marker
        with patch("support.native_memory_review.NativeMemoryReview.findings_inputs",
                   return_value=(records,[],[])):
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=False):
                expected = source.findings(records,0,today=date(2026,11,16))
            def request(flag,operation,payload):
                self.assertEqual("report-text-groups",operation)
                self.assertIs(True,payload.get("relations"),"replacement decision is still separate")
                return {"duplicates":[[1,0]],"shared_sources":[[1,0]],
                        "findings":[{"index":1,"replacements":[0]}]}
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
                 patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request) as probe:
                actual = source.findings(records,0,today=date(2026,11,16))
            self.assertEqual(1,probe.call_count)
        self.assertEqual(expected,actual)
        self.assertEqual(list(expected),list(actual))
        self.assertEqual(["b"],actual["unfinished_replacements"][0]["replaced_by"])
        self.assertIs(marker,actual["unfinished_replacements"][0]["applies_when"])

    def test_invalid_relations_reply_replays_neither_native_operation(self):
        records = self.records()
        records[0]["replaces"] = "a"
        expected = {"duplicate_groups":source._duplicate_groups_reference(records),
                    "shared_source_groups":source._shared_source_groups_reference(records),
                    "unfinished_replacements":source._unfinished_replacements_reference(records)}
        for findings in (None,[{"index":True,"replacements":[0]}],
                         [{"index":1,"replacements":[2]}],
                         [{"index":1,"replacements":[0,0]}],
                         [{"index":1,"replacements":[0],"extra":1}]):
            reply = {"duplicates":[[1,0]],"shared_sources":[[1,0]],"findings":findings}
            with self.subTest(findings=findings), \
                 patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
                 patch("support.native_memory_consolidation.NativeProbe.request",return_value=reply) as probe:
                self.assertEqual(expected,source._report_relations(records))
                self.assertEqual(1,probe.call_count)
        with patch("support.native_memory_consolidation.NativeProbe.request",side_effect=AssertionError("transport")):
            self.assertEqual({key:[] for key in expected},source._report_relations([]))

    def test_custom_replacement_adapter_stays_after_legacy_group_projection(self):
        records = self.records()
        def request(flag,operation,payload):
            self.assertNotIn("relations",payload)
            return {"duplicates":[[1,0]],"shared_sources":[[1,0]]}
        with patch("support.native_memory_upkeep.NativeMemoryUpkeep.replacements",
                   return_value=[(records[1],["custom"])]) as replacements, \
             patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
             patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request):
            result = source._report_relations(records)
        self.assertEqual(["custom"],result["unfinished_replacements"][0]["replaced_by"])
        replacements.assert_called_once_with(records)
        class CustomUpkeep:
            replacements = staticmethod(lambda rows:[(rows[1],["custom class"])])
        with patch("support.native_memory_upkeep.NativeMemoryUpkeep",CustomUpkeep), \
             patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
             patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request):
            result = source._report_relations(records)
        self.assertEqual(["custom class"],result["unfinished_replacements"][0]["replaced_by"])

    def test_report_uses_one_group_request_and_preserves_original_projection(self):
        records = self.records()
        marker = object()
        records[1]["applies_when"] = marker
        with patch("support.native_memory_review.NativeMemoryReview.findings_inputs",
                   return_value=(records,[],[])), \
             patch("support.native_memory_upkeep.NativeMemoryUpkeep.replacements",return_value=[]):
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=False):
                expected = source.findings(records,0,today=date(2026,11,16))
            def request(flag, operation, payload):
                self.assertEqual("report-text-groups",operation,"split group requests")
                return {"duplicates":[[1,0]],"shared_sources":[[1,0]]}
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
                 patch("support.native_memory_consolidation.NativeProbe.request",side_effect=request) as probe:
                actual = source.findings(records,0,today=date(2026,11,16))
            self.assertEqual(1,probe.call_count)
        self.assertEqual(expected,actual)
        self.assertEqual(list(expected),list(actual))
        self.assertIs(marker,actual["shared_source_groups"][0]["records"][0]["applies_when"])

    def test_invalid_combined_reply_falls_back_once_without_partial_groups(self):
        records = self.records()
        expected = source._duplicate_groups_reference(records),source._shared_source_groups_reference(records)
        for reply in (None,{}, {"duplicates":[],"shared_sources":[[0,1]]},
                      {"duplicates":[[True,0]],"shared_sources":[]},
                      {"duplicates":[[1,0]],"shared_sources":[[1,1]]},
                      {"duplicates":[[1,0]],"shared_sources":[],"extra":True}):
            with self.subTest(reply=reply), \
                 patch("support.native_memory_consolidation.NativeProbe.available",return_value=True), \
                 patch("support.native_memory_consolidation.NativeProbe.request",return_value=reply) as probe:
                self.assertEqual(expected,source._report_groups(records))
                self.assertEqual(1,probe.call_count)

    def test_empty_unavailable_and_exceptional_profiles_do_not_submit_combined_work(self):
        with patch("support.native_memory_consolidation.NativeProbe.request",
                   side_effect=AssertionError("transport")):
            self.assertEqual(([],[]),source._report_groups([]))
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=False):
                self.assertEqual((None,False),NativeMemoryConsolidation.report_groups(self.records()))
            with patch("support.native_memory_consolidation.NativeProbe.available",return_value=True):
                for records in ([{}],[{**self.records()[0],"source":None}]):
                    self.assertEqual((None,False),NativeMemoryConsolidation.report_groups(records))
                self.assertEqual((None,False),NativeMemoryConsolidation.report_groups(self.records(),0.5))

    def test_custom_report_callbacks_keep_their_order_and_output(self):
        calls = []
        with patch.object(source,"_duplicate_groups",side_effect=lambda rows:calls.append("duplicate") or [1]), \
             patch.object(source,"_shared_source_groups",side_effect=lambda rows:calls.append("source") or [2]), \
             patch("support.native_memory_consolidation.NativeProbe.request",side_effect=AssertionError("transport")):
            self.assertEqual(([1],[2]),source._report_groups(self.records()))
        self.assertEqual(["duplicate","source"],calls)


class NativeMemoryConsolidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-consolidation-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def record(self, id, body="a b c d", scope="task", source="docs/Guide.md", **fields):
        return {"id": id, "body": body, "scope": scope, "source": source,
                "status": "active", "review_on": "2099-01-01", **fields}

    def groups(self, records, operation="duplicate", backend="auto", required=False):
        name = "_duplicate_groups" if operation == "duplicate" else "_shared_source_groups"
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
            if required:
                with patch.object(source, name + "_reference", side_effect=AssertionError("Python grouping replay")):
                    return getattr(source, name)(records)
            return getattr(source, name)(records)

    def parity(self, records, operation="duplicate"):
        expected = self.groups(records, operation, "python")
        actual = self.groups(records, operation, required=True)
        self.assertEqual(expected, actual)
        return actual

    def test_exact_threshold_and_below_are_not_greedy_similarity(self):
        records = [self.record("a"), self.record("b", "a b c d e"), self.record("c", "a b c x y")]
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity(records)])

    def test_fused_report_matches_seeded_original_without_python_group_replay(self):
        rng = random.Random(261116)
        watched = {getattr(source,name).__code__ for name in
            ("normalize","_tokens","_jaccard","_duplicate_groups_reference","_shared_source_groups_reference",
             "_unfinished_replacements_reference","_live_records_reference","_review_buckets_reference")}
        from support.native_probe_transport import NativeProbe
        for _ in range(16):
            records = [self.record(str(rng.randrange(5)),
                " ".join(rng.sample(list("abcdef"),rng.randrange(7))),
                rng.choice(["task","review","all"]),source=rng.choice(["a","B!","b",""]),
                replaces=rng.choice([None,"","0","1","missing"]),
                status=rng.choice(["active","pending","approved","retired"]),
                review_on=rng.choice(["2026-11-15","2026-11-16","2026-11-17","2099-01-01"]))
                for _ in range(rng.randrange(1,9))]
            with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
                expected = source.findings(records,0,today=date(2026,11,16))
            replay = []
            def profile(frame,event,arg):
                if event == "call" and frame.f_code in watched: replay.append(frame.f_code.co_name)
            original = sys.getprofile()
            with patch.dict(os.environ,self.env,clear=True), \
                 patch.object(NativeProbe,"request",wraps=NativeProbe.request) as probe:
                try:
                    sys.setprofile(profile)
                    actual = source.findings(records,0,today=date(2026,11,16))
                finally: sys.setprofile(original)
            self.assertEqual(expected,actual)
            self.assertEqual([],replay)
            operations = [call.args[1] for call in probe.call_args_list]
            self.assertEqual(1,operations.count("report-text-groups"))
            self.assertFalse({"duplicate-text-groups","shared-source-text-groups"}.intersection(operations))
            self.assertNotIn("upkeep-replacements",operations)
            self.assertNotIn("review-findings",operations)
            self.assertEqual(1,len(operations))

    def test_pre_edit_projection_values_reasons_and_key_order(self):
        # Captured from the unchanged source before extracting the references.
        records = [self.record(name, source="Docs!") for name in ("b", "a")]
        projected = [{"id":name,"scope":"task","body":"a b c d","source":"Docs!",
                      "review_on":"2099-01-01"} for name in ("a", "b")]
        reasons = {"duplicate":"bodies share at least 80% of their words in overlapping scopes; "
                                "merge with `capture --replaces <one>`, then retire the others",
                   "source":"records cite the same source; open it and keep, merge or retire the ones that disagree"}
        for mode, reason in reasons.items():
            expected = [{"ids":["a","b"],"reason":reason,"records":projected}]
            actual = self.groups(records, mode, required=True)
            self.assertEqual(expected, actual)
            self.assertEqual(list(expected[0]), list(actual[0]))
            self.assertEqual([list(row) for row in projected], [list(row) for row in actual[0]["records"]])

    def test_reordered_groups_and_equal_id_ties_defer(self):
        records = [self.record("a"), self.record("b"), self.record("c"), self.record("d")]
        for groups in ([[1,0]], [[2,3],[0,1]]):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":groups}):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", records, source._tokens))
        tied = [self.record("x") for _ in range(4)]
        for groups in ([[1,0]], [[2,3],[0,1]]):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":groups}):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", tied, source._tokens))
        with patch("support.native_memory_consolidation.NativeProbe.request", return_value={"groups":[[0,2],[1,3]]}):
            selected = NativeMemoryConsolidation.groups("duplicate-groups", tied, source._tokens)
        self.assertIs(tied[2], selected[0][1])

    def test_transitive_chain_and_all_scope_bridge_connect_endpoints(self):
        records = [self.record("c", "a b c d e f", "review"), self.record("a", "a b c d", "task"),
                   self.record("b", "a b c d e", "all")]
        self.assertLess(source._jaccard(source._tokens(records[0]["body"]), source._tokens(records[1]["body"])), 0.8)
        self.assertEqual([["a", "b", "c"]], [g["ids"] for g in self.parity(records)])
        records[2]["scope"] = "task"
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity(records)])

    def test_empty_repeated_tokens_and_distinct_scopes_keep_original_decisions(self):
        self.assertEqual([], self.parity([self.record("a", "!!!"), self.record("b", "???")]))
        self.assertEqual([], self.parity([self.record("a", scope="task"), self.record("b", scope="review")]))
        self.assertEqual([["a", "b"]], [g["ids"] for g in self.parity([
            self.record("b", "a b a b c d"), self.record("a")])])

    def test_original_unicode_lower_punctuation_and_whitespace_are_preserved(self):
        for left, right in (("ABC_DEF, 한글\u00a0é", "abc_def 한글 é"), ("ΟΣ", "ος"),
                            ("Straße", "STRASSE"), ("é", "é"), ("İ", "i"), ("\x1ca\tb", "a b")):
            self.parity([self.record("a", left), self.record("b", right)])
            self.parity([self.record("a", source=left), self.record("b", source=right)], "source")

    def test_seeded_unsorted_components_match_original_algorithm(self):
        rng = random.Random(261112)
        for _ in range(24):
            records = [self.record(str(rng.randrange(5)),
                " ".join(rng.sample(list("abcdef"), rng.randrange(7))),
                rng.choice(["task", "review", "all"]), source=rng.choice(["a", "B!", "b", ""]))
                for _ in range(rng.randrange(9))]
            self.parity(records)
            self.parity(records, "source")

    def test_duplicate_id_ties_and_groups_retain_stable_original_values(self):
        marker = object()
        records = [self.record("x", "one", source="z", applies_when=marker),
                   self.record("x", "two", source="a", applies_when="\ud800"),
                   self.record("x", "one", source="z", applies_when=2**100),
                   self.record("x", "two", source="a", not_when=marker)]
        for mode in ("duplicate", "source"):
            groups = self.parity(records, mode)
            self.assertIs(marker, groups[0]["records"][0]["applies_when"])
            self.assertIs(marker, groups[1]["records"][1]["not_when"])

    def test_empty_sources_group_across_scopes_and_output_is_id_sorted(self):
        records = [self.record("z", source=""), self.record("b", scope="review", source="!!!"),
                   self.record("a", source="DOCS/guide.md "), self.record("c", source="docs/Guide.md")]
        self.assertEqual([["a", "c"], ["b", "z"]], [g["ids"] for g in self.parity(records, "source")])

    def test_empty_helpers_keep_no_probe_fast_path(self):
        with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual([], source._duplicate_groups([]))
            self.assertEqual([], source._shared_source_groups([]))

    def test_actual_grouping_wiring_has_negative_controls(self):
        records = [self.record("a"), self.record("b")]
        with patch.object(source, "_jaccard", side_effect=AssertionError("Python pair replay")), \
             patch.object(source, "_scopes_overlap", side_effect=AssertionError("Python scope replay")):
            self.groups(records, required=True)
        for mode in ("duplicate", "source"):
            with patch.object(NativeMemoryConsolidation, "groups", return_value=None):
                with self.assertRaisesRegex(AssertionError, "Python grouping replay"):
                    self.groups(records, mode, required=True)

    def test_malformed_and_custom_profiles_preserve_original_errors(self):
        class Custom(str):
            def lower(self):
                raise RuntimeError("custom lower")
        for records, mode in (([{}], "duplicate"), ([self.record("a", body=None)], "duplicate"),
                              ([self.record("a", body=Custom("a"))], "duplicate"),
                              ([self.record("a", source=Custom("a"))], "source")):
            with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
                try:
                    expected = self.groups(records, mode, "python")
                except Exception as error:
                    with self.assertRaises(type(error)) as actual:
                        self.groups(records, mode)
                    self.assertEqual(error.args, actual.exception.args)
                else:
                    self.assertEqual(expected, self.groups(records, mode))
        with patch.object(source, "DUPLICATE_JACCARD", 0.5), \
             patch("support.native_memory_consolidation.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual(self.groups([self.record("a"), self.record("b", "a b")], backend="python"),
                             self.groups([self.record("a"), self.record("b", "a b")]))

    def test_malformed_packets_and_unavailable_transport_defer(self):
        records = [self.record("a"), self.record("b")]
        for result in (None, {}, {"groups": None}, {"groups": [[True, 1]]}, {"groups": [[0]]},
                       {"groups": [[-1, 1]]}, {"groups": [[0, 2]]}, {"groups": [[0, 0]]},
                       {"groups": [[0, 1], [0, 1]]}, {"groups": [], "extra": 1}):
            with patch("support.native_memory_consolidation.NativeProbe.request", return_value=result):
                self.assertIsNone(NativeMemoryConsolidation.groups("duplicate-groups", records, source._tokens))
        for error in (OSError("transport"), ValueError("transport"), RuntimeError("transport")):
            with patch("support.native_memory_consolidation.NativeProbe.request", side_effect=error):
                self.assertIsNone(NativeMemoryConsolidation.groups("shared-source-groups", records, source.normalize))

    def test_findings_preserves_dates_reasons_and_retired_record_exclusion(self):
        records = [self.record("a", review_on="2026-11-12"), self.record("b", status="pending"),
                   self.record("c", status="approved", review_on="2026-11-26", replaces="a"),
                   self.record("d", status="retired", review_on="2020-01-01")]
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = source.findings(records, 2, today=date(2026, 11, 12))
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_duplicate_groups_reference", side_effect=AssertionError("Python grouping replay")), \
             patch.object(source, "_shared_source_groups_reference", side_effect=AssertionError("Python grouping replay")):
            self.assertEqual(expected, source.findings(records, 2, today=date(2026, 11, 12)))
        self.assertEqual(["a"], [r["id"] for r in expected["expired"]])
        self.assertEqual(["c"], [r["id"] for r in expected["expiring"]])
        self.assertEqual(["c"], expected["unfinished_replacements"][0]["replaced_by"])

    def test_native_date_entries_preserve_order_and_original_metadata_without_entry_replay(self):
        from support.native_probe_transport import NativeProbe

        marker = object()
        records = [
            self.record("a", "alpha", source="First", review_on="2026-11-12", applies_when=marker),
            self.record("b", "beta", source="Second", review_on="2026-11-13", not_when=marker),
        ]
        today = date(2026, 11, 12)
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = source.findings(records, 2, today=today, within_days=2)
        calls = []
        code = source._entry.__code__
        def observe(frame, event, arg):
            if event == "call" and frame.f_code is code:
                calls.append(True)
        previous = sys.getprofile()
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(NativeProbe, "request", wraps=NativeProbe.request) as request:
            try:
                sys.setprofile(observe)
                actual = source.findings(records, 2, today=today, within_days=2)
            finally:
                sys.setprofile(previous)
        self.assertEqual([], calls)
        self.assertEqual(1, request.call_count)
        self.assertEqual(2, request.call_args.args[2]["review"]["render_days"])
        self.assertEqual(expected, actual)
        for bucket, key in (("expired", "applies_when"), ("expiring", "not_when")):
            self.assertEqual(list(expected[bucket][0]), list(actual[bucket][0]))
            self.assertIs(marker, actual[bucket][0][key])

    def test_real_store_cli_is_read_only_and_requires_native_grouping(self):
        directory = self.base / "records"
        directory.mkdir()
        records = [self.record("a" * 16, schema_version=1), self.record("b" * 16, schema_version=1)]
        for record in records:
            record["digest"] = memory._digest(record)
            path = directory / (record["id"] + ".json")
            path.write_text(json.dumps(record), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            for path in directory.iterdir():
                self.assertIsNotNone(memory.read_record(path), "fixture must satisfy original record schema")
            expected = source.findings(records, 0, today=date.today())
        with patch.dict(os.environ, self.env, clear=True), patch.object(memory, "store_dir", return_value=directory), \
             patch.object(source, "_duplicate_groups_reference", side_effect=AssertionError("Python grouping replay")), \
             patch.object(source, "_shared_source_groups_reference", side_effect=AssertionError("Python grouping replay")):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, memory._main(["--project", str(self.project), "consolidate"]))
            self.assertEqual(expected, json.loads(output.getvalue()))
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
