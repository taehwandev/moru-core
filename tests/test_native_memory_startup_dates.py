"""Startup ISO dates use the Rust counter; Python stays the compatibility oracle."""
from datetime import date
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_project_memory_consolidate as source
from native_pretool_support import environment, prepare
from support.native_memory_upkeep import NativeMemoryUpkeep
from support.native_probe_transport import NativeProbe

TODAY = date(2026, 11, 13)


def record(name="a", **values):
    return {"id": name, "status": "active", "body": "Same, advice", "scope": "task",
            "source": "Docs!", "review_on": "2099-01-01", **values}


class NativeMemoryStartupDatesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-startup-dates-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        empty = self.base / "empty"
        empty.mkdir()
        self.env = {**environment(self.base), "PATH": str(empty)}

    def run_startup(self, rows, today=TODAY):
        with patch.dict(os.environ, self.env, clear=True):
            return source.startup_summary_line(rows, Path("project space"), "moru-hook", today=today)

    def reference(self, rows, today=TODAY):
        return source._startup_summary_line_reference(rows, Path("project space"), "moru-hook", today=today)

    def test_ordinary_public_startup_never_calls_python_date_parser_or_ordinal(self):
        rows = [record("a", review_on="2026-11-13"), record("b", replaces="a")]
        expected = self.reference(rows)
        calls = []
        previous = sys.getprofile()
        def observe(frame, event, function):
            if event == "c_call" and getattr(function, "__name__", "") in ("fromisoformat", "toordinal"):
                calls.append(function.__name__)
        with patch.object(NativeMemoryUpkeep, "_request", wraps=NativeMemoryUpkeep._request) as requested, \
             patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
            try:
                sys.setprofile(observe)
                actual = self.run_startup(rows)
            finally:
                sys.setprofile(previous)
        self.assertEqual(expected, actual)
        self.assertEqual([], calls)
        self.assertEqual(1, requested.call_count)
        self.assertEqual("upkeep-startup-dates", requested.call_args.args[0])
        self.assertEqual([r["review_on"] for r in rows], [r["review"] for r in requested.call_args.args[1]])
        self.assertEqual(TODAY.isoformat(), requested.call_args.kwargs["today"])

    def test_seeded_boundary_calendar_and_scope_counts_match_reference(self):
        rng = random.Random(61113)
        dates = ["0001-01-01", "1900-02-28", "2000-02-29", "2026-11-12",
                 "2026-11-13", "2026-11-14", "9999-12-31"]
        rows = [record(str(i % 7), review_on=rng.choice(dates), status=rng.choice(["active", "pending", "retired"]),
                       body=rng.choice(["Same!", "", "다른 기록", "SAME"]), scope=rng.choice(["all", "task", "review"]),
                       source=rng.choice(["", "Docs!", "docs", "출처"]), replaces=rng.choice([None, "", "1"]))
                for i in range(47)]
        for today in (date.min, date(1900, 2, 28), date(2000, 2, 29), TODAY, date.max):
            expected = self.reference(rows, today)
            with patch.object(source, "_startup_summary_line_reference", side_effect=AssertionError("Python replay")):
                self.assertEqual(expected, self.run_startup(rows, today))

    def test_declining_transport_reuses_normalization_and_parses_each_date_once(self):
        rows = [record("a", review_on="2026-11-13"), record("b", replaces="a")]
        expected = self.reference(rows)
        parsed = []
        previous = sys.getprofile()
        def observe(frame, event, function):
            if event == "c_call" and getattr(function, "__name__", "") == "fromisoformat":
                parsed.append(function)
        with patch.object(NativeProbe, "request", return_value=None), \
             patch.object(source, "normalize", wraps=source.normalize) as normalized:
            try:
                sys.setprofile(observe)
                self.assertEqual(expected, self.run_startup(rows))
            finally:
                sys.setprofile(previous)
        self.assertEqual(2 * len(rows), normalized.call_count)
        self.assertEqual(len(rows), len(parsed))
        with patch.dict(os.environ, self.env, clear=True), patch.object(NativeProbe, "request", return_value=None):
            counts, prepared = NativeMemoryUpkeep.startup(rows, source.normalize, date.fromisoformat,
                TODAY, source.RECALLABLE_STATUSES, strict_dates=True)
        self.assertIsNone(counts)
        self.assertEqual([date.fromisoformat(r["review_on"]).toordinal() for r in rows],
                         [r["review"] for r in prepared])

    def test_extended_and_invalid_date_profiles_preserve_interpreter_values_and_errors(self):
        for text in ("20261113", "2026-W46-5", "", "not-a-date", "1900-02-29", "2000-02-29", "\ud800"):
            rows = [record("a", review_on=text), record("b")]
            try:
                expected = self.reference(rows)
            except Exception as error:
                with self.assertRaises(type(error)) as actual:
                    self.run_startup(rows)
                self.assertEqual(error.args, actual.exception.args)
            else:
                self.assertEqual(expected, self.run_startup(rows))

    def test_normalization_failure_precedes_earlier_invalid_review_date(self):
        rows = [record("a", review_on="invalid"), record("b", body="trip")]
        original = source.normalize
        def normalize(text):
            if text == "trip":
                raise RuntimeError("normalization first")
            return original(text)
        with patch.object(source, "normalize", normalize), \
             patch.object(NativeProbe, "request", side_effect=AssertionError("early transport")):
            with self.assertRaisesRegex(RuntimeError, "normalization first"):
                self.run_startup(rows)

    def test_custom_parser_cannot_opt_into_strict_dates(self):
        rows = [record("a"), record("b")]
        parsed = []
        def custom(text):
            parsed.append(text)
            return date.min
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(NativeMemoryUpkeep, "_request", wraps=NativeMemoryUpkeep._request) as requested:
            counts, _ = NativeMemoryUpkeep.startup(rows, source.normalize, custom, TODAY,
                source.RECALLABLE_STATUSES, strict_dates=True)
        self.assertEqual(2, counts["expired"])
        self.assertEqual([r["review_on"] for r in rows], parsed)
        self.assertEqual("upkeep-startup", requested.call_args.args[0])

    def test_custom_source_calendar_keeps_its_parser_and_ordinal_protocol(self):
        rows = [record("a")]
        parsed = []
        class Calendar:
            @staticmethod
            def fromisoformat(text):
                parsed.append(text)
                return date.min
        with patch.object(source, "date", Calendar), \
             patch.object(NativeMemoryUpkeep, "_request", wraps=NativeMemoryUpkeep._request) as requested:
            result = self.run_startup(rows)
        self.assertIn("expired=1", result)
        self.assertEqual(["2099-01-01"], parsed)
        self.assertEqual("upkeep-startup", requested.call_args.args[0])

    def test_unavailable_binary_and_filtered_empty_input_never_request_transport(self):
        rows = [record("a", review_on="2026-11-13")]
        expected = self.reference(rows)
        with patch.object(NativeProbe, "available", return_value=False), \
             patch.object(NativeProbe, "request", side_effect=AssertionError("unavailable transport")):
            self.assertEqual(expected, self.run_startup(rows))
        with patch.object(NativeProbe, "request", side_effect=AssertionError("empty transport")):
            self.assertEqual("", self.run_startup([]))
            self.assertEqual("", self.run_startup([{"status": "retired", "review_on": "bad"}]))
