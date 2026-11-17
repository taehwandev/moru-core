"""Observe fused normalization against the original Python startup contract."""
from datetime import date
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_startup import NativeMemoryStartup
from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe

TODAY = date(2026, 11, 13)


def record(name="a", **values):
    return {"id": name, "status": "active", "body": "한글! Body", "scope": "task",
            "source": "Docs!", "review_on": "2099-01-01", **values}


class StartupSelectionContractTests(unittest.TestCase):
    def test_full_status_packet_omits_inactive_values_and_preserves_input(self):
        marker = object()
        rows = [record("a"), {"status":"retired","body":marker,"replaces":marker},
                record("b",status="pending")]
        counts = {"expired":0,"exact_duplicates":1,"shared_source":1,"unfinished":0}
        def request(operation, packet, **fields):
            self.assertEqual("upkeep-startup-text",operation)
            self.assertEqual(sorted(source.RECALLABLE_STATUSES),fields["statuses"])
            self.assertEqual(["active","retired","pending"],[r["status"] for r in packet])
            self.assertEqual({"id":None,"status":"retired","body":None,"scope":None,
                              "source":None,"review":None,"replaces":None},packet[1])
            return {"counts":counts}
        with patch.object(NativeProbe,"available",return_value=True), \
             patch.object(NativeMemoryUpkeep,"_request",side_effect=request) as probe:
            self.assertEqual(counts,NativeMemoryStartup.hints(rows,TODAY,source.RECALLABLE_STATUSES))
        self.assertIs(marker,rows[1]["body"])
        self.assertEqual(1,probe.call_count)

    def test_counts_remain_bounded_by_live_admission_not_total_rows(self):
        rows = [record("a"),{"status":"retired"},{"status":"retired"}]
        with patch.object(NativeProbe,"available",return_value=True), \
             patch.object(NativeMemoryUpkeep,"_request",return_value={"counts":{
                 "expired":2,"exact_duplicates":0,"shared_source":0,"unfinished":0}}) as probe:
            self.assertIsNone(NativeMemoryStartup.hints(rows,TODAY,source.RECALLABLE_STATUSES))
        self.assertEqual(1,probe.call_count)


class NativeMemoryStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-startup-text-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def run_startup(self, rows):
        with patch.dict(os.environ, self.env, clear=True):
            return source.startup_summary_line(rows, self.project, "moru-hook", today=TODAY)

    def reference(self, rows):
        return source._startup_summary_line_reference(rows, self.project, "moru-hook", today=TODAY)

    def test_fused_request_skips_python_normalization_and_date_parsing(self):
        marker = object()
        rows = [record("a", review_on="2026-11-13", opaque=marker), record("b", replaces="a")]
        before = [dict(r) for r in rows]
        expected = self.reference(rows)
        normalizer = source.normalize.__code__
        calls = []
        def observe(frame, event, function):
            if event == "call" and frame.f_code is normalizer:
                calls.append("normalize")
            if event == "c_call" and getattr(function, "__name__", "") in ("fromisoformat", "toordinal"):
                calls.append(function.__name__)
        previous = sys.getprofile()
        with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")), \
             patch.object(NativeMemoryUpkeep, "_request", wraps=NativeMemoryUpkeep._request) as requested:
            try:
                sys.setprofile(observe)
                actual = self.run_startup(rows)
            finally:
                sys.setprofile(previous)
        self.assertEqual(expected, actual)
        self.assertEqual([], calls)
        self.assertEqual(1, requested.call_count)
        self.assertEqual("upkeep-startup-text", requested.call_args.args[0])
        self.assertEqual(rows[0]["body"], requested.call_args.args[1][0]["body"])
        self.assertEqual(before, rows)
        self.assertIs(marker, rows[0]["opaque"])

    def test_unicode_case_punctuation_and_whitespace_notices_match_reference(self):
        texts = ["Straße", "STRASSE", "İ", "I", "ΟΣ", "ΟΣΑ", "Σ", "AΣ\u0301", "AΣ\u0301B",
                 "AΣ'B", "AΣ\u200dB", "ᵃΣ", "AᵃΣ", "A\u001cB\u0085C", "A-B", "A B",
                 "foo_bar", "e\u0301", "É", "!!!", "Ⅰ²０", "한글! 본문?", "\0", "𐐀𐐁"]
        for text in texts:
            rows = [record("a", body=text, source=text),
                    record("b", body=source.normalize(text), source=source.normalize(text), scope="all")]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows), repr(text))
        for first, second in (("Straße", "STRASSE"), ("A-B", "A B"), ("foo_bar", "foobar")):
            rows = [record("a", body=first), record("b", body=second)]
            self.assertEqual(self.reference(rows), self.run_startup(rows))

    def test_sampled_lowercase_and_sigma_contexts_match_builder_interpreter(self):
        rng = random.Random(61114)
        candidates = [chr(cp) for cp in range(0x110000)
                      if chr(cp).lower() != chr(cp) or chr(cp).isspace()]
        texts = ["A" + c + "Σ" for c in rng.sample(candidates, 128)]
        texts += ["AΣ" + c + "B" for c in ("\u0301", "\u0345", "\u200d", "ᵃ", "'", ".", "\u001c")]
        for start in range(0, len(texts), 32):
            rows = [record(str(i), body=text, source=text) for i, text in enumerate(texts[start:start+32])]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows))

    def test_seeded_scope_status_and_link_groups_match_reference(self):
        rng = random.Random(214)
        for _ in range(8):
            rows = [record(str(i % 5), body=rng.choice(["Same!", "SAME", "", "Ος", "ΟΣ", "한글"]),
                source=rng.choice(["Docs!", " docs ", "", "!?", "출처"]), scope=rng.choice(["task", "review", "all"]),
                status=rng.choice(["active", "pending", "approved", "retired", "ACTIVE"]), replaces=rng.choice([None, "", "1"]),
                review_on=rng.choice(["0001-01-01", "2026-11-13", "9999-12-31"])) for i in range(37)]
            expected = self.reference(rows)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows))

    def test_mixed_statuses_use_one_native_request_and_detect_missing_selection(self):
        rows = [record("a",review_on="2026-11-13"),record("b",replaces="a"),
                {"status":"retired","body":object(),"review_on":object(),"replaces":object()}]
        expected = self.reference(rows)
        with patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("Python selection replay")), \
             patch.object(NativeMemoryUpkeep,"_request",wraps=NativeMemoryUpkeep._request) as probe:
            self.assertEqual(expected,self.run_startup(rows))
        self.assertEqual(1,probe.call_count)
        self.assertEqual(3,len(probe.call_args.args[1]))
        self.assertEqual(sorted(source.RECALLABLE_STATUSES),probe.call_args.kwargs["statuses"])
        request = NativeMemoryUpkeep._request
        def without_selection(operation, packet, **fields):
            fields.pop("statuses",None)
            return request(operation,packet,**fields)
        with patch.object(NativeMemoryUpkeep,"_request",side_effect=without_selection), \
             patch.object(source,"_startup_summary_line_reference",side_effect=AssertionError("Python selection replay")):
            with self.assertRaisesRegex(AssertionError,"Python selection replay"):
                self.run_startup(rows)

    def test_decline_and_invalid_packets_normalize_each_field_once(self):
        rows = [record("a"), record("b", replaces="a")]
        expected = self.reference(rows)
        code = source.normalize.__code__
        for packet in (None, {}, {"counts":None}, {"counts":{"expired":True}},
                       {"counts":dict.fromkeys(("expired","exact_duplicates","shared_source","unfinished"),3)}):
            calls = []
            def observe(frame, event, function):
                if event == "call" and frame.f_code is code:
                    calls.append(1)
            previous = sys.getprofile()
            with patch.object(NativeProbe, "request", return_value=packet):
                try:
                    sys.setprofile(observe)
                    self.assertEqual(expected, self.run_startup(rows))
                finally:
                    sys.setprofile(previous)
            self.assertEqual(2 * len(rows), len(calls))

    def test_custom_normalizer_and_regex_bindings_keep_python_callbacks(self):
        rows = [record("a", body="Alpha1"), record("b", body="Alpha2")]
        with patch.object(source, "normalize", wraps=source.normalize) as normalized, \
             patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("custom bypass")):
            expected = self.reference(rows)
            normalized.reset_mock()
            self.assertEqual(expected, self.run_startup(rows))
            self.assertEqual(2 * len(rows), normalized.call_count)
        with patch.object(source, "_PUNCTUATION_RE", re.compile("[^a-z]")), \
             patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("regex bypass")):
            self.assertEqual(self.reference(rows), self.run_startup(rows))

    def test_in_place_normalizer_code_override_is_not_bypassed(self):
        rows = [record("a", body="first"), record("b", body="second")]
        def altered(text):
            return "same"
        original_code = source.normalize.__code__
        try:
            source.normalize.__code__ = altered.__code__
            with patch.object(NativeMemoryStartup, "hints", side_effect=AssertionError("code bypass")):
                self.assertEqual(self.reference(rows), self.run_startup(rows))
        finally:
            source.normalize.__code__ = original_code

    def test_unavailable_empty_and_retired_profiles_do_not_request_transport(self):
        rows = [record("a")]
        expected = self.reference(rows)
        with patch.object(NativeProbe, "available", return_value=False), \
             patch.object(NativeProbe, "request", side_effect=AssertionError("unavailable request")):
            self.assertEqual(expected, self.run_startup(rows))
        with patch.object(NativeProbe, "request", side_effect=AssertionError("empty request")):
            self.assertEqual("", self.run_startup([]))
            self.assertEqual("", self.run_startup([{"status":"retired","body":None,"review_on":"bad"}]))

    def test_surrogates_malformed_profiles_and_date_errors_keep_reference(self):
        for rows in ([record(body="A\ud800B")], [record(review_on="1900-02-29")],
                     [record(replaces=[])], [{}], [record(status=[])]):
            try:
                expected = self.reference(rows)
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.run_startup(rows)
                self.assertEqual(error.args, actual.exception.args)
            else:
                self.assertEqual(expected, self.run_startup(rows))

    def test_public_native_wiring_has_a_negative_control(self):
        rows = [record("a"), record("b")]
        expected = self.reference(rows)
        with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
            self.assertEqual(expected, self.run_startup(rows))
            with patch.object(NativeMemoryStartup, "hints", return_value=None):
                with self.assertRaisesRegex(AssertionError, "Python replay"):
                    self.run_startup(rows)
