"""Conditional lessons remain bounded references rather than automatic instructions."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_project_memory as memory
from agent_project_memory_consolidate import consolidate


class ProjectMemoryApplicabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        patch = mock.patch.dict(os.environ, {"MORU_STATE_HOME": str(self.project / "state")})
        patch.start()
        self.addCleanup(patch.stop)
        self.review_on = (date.today() + timedelta(days=30)).isoformat()

    def capture(self, body="Inspect the narrow producer first.", **kwargs):
        return memory._capture(self.project, body=body, source="verified fixture",
                               scope="task", review_on=self.review_on, **kwargs)

    def rendered(self, **kwargs):
        return [json.loads(line[2:]) for line in
                memory.recall_lines(self.project, "task", **kwargs)[1:]]

    def path(self, record):
        return memory.store_dir(self.project) / f'{record["id"]}.json'

    def test_conditions_survive_capture_read_recall_history_and_consolidation(self):
        record = self.capture(applies_when="Duplicate delivery after reconnect.",
                              not_when="The upstream feed is immutable.")
        saved = memory.read_record(self.path(record))
        recalled = self.rendered(request="Duplicate delivery in a differently named module")[0]
        history = memory._history(self.project, record["id"])[0]
        # Expiring entries are also the decision surface for consolidation.
        report = consolidate(self.project, within_days=60)
        expiring = report["expiring"][0]
        for shown in (saved, recalled, history, expiring):
            self.assertEqual(record["applies_when"], shown["applies_when"])
            self.assertEqual(record["not_when"], shown["not_when"])

    def test_legacy_and_empty_conditions_keep_the_existing_digest(self):
        record = self.capture(applies_when="  ", not_when="")
        self.assertNotIn("applies_when", record)
        self.assertNotIn("not_when", record)
        self.assertIsNotNone(memory.read_record(self.path(record)))
        self.assertNotIn("applies_when", self.rendered()[0])

    def test_capture_trims_conditions_and_accepts_the_exact_limit(self):
        record = self.capture(applies_when="  " + "a" * 160 + "  ", not_when=" x ")
        self.assertEqual("a" * 160, record["applies_when"])
        self.assertEqual("x", record["not_when"])

    def test_capture_rejects_oversized_or_multiline_conditions_without_a_record(self):
        for field in memory.APPLICABILITY_FIELDS:
            for value in ("x" * 161, "first\nsecond", "first\tsecond", "a\x00b"):
                with self.subTest(field=field, value=repr(value)), self.assertRaises(ValueError):
                    self.capture(**{field: value})
        self.assertEqual([], memory.scan_records(self.project)[0])

    def test_condition_tampering_is_detected(self):
        for field in memory.APPLICABILITY_FIELDS:
            record = self.capture(**{field: "verified condition"})
            record[field] = "altered condition"
            self.path(record).write_text(json.dumps(record))
            self.assertIsNone(memory.read_record(self.path(record)))

    def test_malformed_conditions_are_rejected_even_with_a_matching_digest(self):
        for field in memory.APPLICABILITY_FIELDS:
            for value in (None, 3, [], {}, "", "x" * 161, "a\nb"):
                with self.subTest(field=field, value=value):
                    record = self.capture()
                    record[field] = value
                    record["digest"] = memory._digest(record)
                    self.path(record).write_text(json.dumps(record))
                    self.assertIsNone(memory.read_record(self.path(record)))

    def test_positive_condition_retrieves_across_file_names(self):
        self.capture("Keep InvoiceTotals values rounded.")
        lesson = self.capture("Inspect src/legacy/Subscriber.kt before changing its consumer.",
                              applies_when="Repeated delivery after reconnect causes duplicate events.")
        shown = self.rendered(request="Fix duplicate events after reconnect in src/new/Inbox.py")
        self.assertEqual([lesson["id"]], [item["id"] for item in shown])

    def test_negative_condition_alone_does_not_attract_a_lesson(self):
        self.capture("Retain the existing projection.", not_when="billing invoices")
        self.assertEqual([], self.rendered(request="billing invoices"))

    def test_reversed_condition_is_visible_for_agent_judgment(self):
        self.capture("Reuse cached account data.", applies_when="Same account and complete cache.",
                     not_when="Account changed or cache incomplete.")
        shown = self.rendered(request="Account changed; cached data is incomplete")
        self.assertEqual(1, len(shown))
        self.assertEqual("Account changed or cache incomplete.", shown[0]["not_when"])
        # Retrieval deliberately does not pretend to evaluate natural language.
        self.assertIn("check applicability before use", memory.recall_lines(self.project, "task")[0])

    def test_all_unrelated_notes_are_withheld_but_context_free_listing_remains(self):
        for body in ("Billing invoices use monthly totals.", "Typography uses rounded fonts."):
            self.capture(body)
        self.assertEqual([], self.rendered(request="retry_queue dispatcher"))
        self.assertEqual([], self.rendered(request="the and of"))
        self.assertEqual(2, len(self.rendered()))

    def test_zero_overlap_paraphrase_is_an_explicit_lexical_limit(self):
        self.capture("Debounce keystrokes.", applies_when="Rapid typing floods suggestions.")
        self.assertEqual([], self.rendered(request="Batch bursts from the keyboard autocomplete widget"))

    def test_superseded_text_is_not_indexed_and_unaffected_lesson_survives(self):
        old = self.capture("Always reuse cached identity.", not_when="old exception")
        unaffected = self.capture("Preserve locale formatting.", applies_when="Currency display.")
        new = self.capture("Require a fresh principal before retaining usage data.",
                           applies_when="Authentication boundary changes.",
                           not_when="Authorization has not succeeded.", replaces=old["id"])
        self.assertEqual([], self.rendered(request="cached identity"))
        shown = {r["id"]: r for r in self.rendered()}
        self.assertEqual({new["id"], unaffected["id"]}, set(shown))
        self.assertEqual(old["body"], shown[new["id"]]["previously"])
        self.assertEqual(unaffected["body"], shown[unaffected["id"]]["body"])
        self.assertIn("superseded history, never current advice",
                      memory.recall_lines(self.project, "task")[0])
        self.assertEqual("old exception", memory._history(self.project, new["id"])[1]["not_when"])

    def test_conditions_and_source_warning_share_the_existing_budget(self):
        record = self.capture("adapter " + "x" * 470, applies_when="a" * 160, not_when="b" * 160)
        record["source_files"] = [{"path": "src/adapter.py", "blob": "a" * 40}]
        short = self.capture("adapter check")
        with mock.patch.object(memory, "_source_blob", return_value="b" * 40):
            lines = memory.recall_lines(self.project, "task", records=[record, short], request="adapter")
        self.assertLessEqual(sum(len(line[2:]) for line in lines[1:]), 1200)
        shown = [json.loads(line[2:]) for line in lines[1:]]
        self.assertIn(short["id"], [r["id"] for r in shown])
        self.assertLessEqual(len(shown), 3)
        if any(r["id"] == record["id"] for r in shown):
            self.assertEqual("changed", shown[0]["source_status"])

    def test_changed_and_missing_sources_still_warn_with_conditions(self):
        record = self.capture("Verify adapter evidence.", applies_when="adapter dispatch")
        record["source_files"] = [{"path": "src/adapter.py", "blob": "a" * 40}]
        for blob, status in (("b" * 40, "changed"), ("", "unavailable"), ("a" * 40, "unchanged")):
            with self.subTest(status=status), mock.patch.object(memory, "_source_blob", return_value=blob):
                shown = self.rendered(records=[record], request="adapter")[0]
                self.assertEqual(status, shown["source_status"])
                self.assertEqual(record["applies_when"], shown["applies_when"])
                if status != "unchanged":
                    self.assertIn("verify before use", shown["warning"])

    def test_cli_condition_flags_round_trip(self):
        output = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("Check the producer.")), redirect_stdout(output):
            result = memory._main(["--project", str(self.project), "capture", "--source", "fixture",
                                   "--scope", "task", "--review-on", self.review_on,
                                   "--applies-when", "Duplicate notifications.",
                                   "--not-when", "Notification delivery is unique."])
        self.assertEqual(0, result)
        record = json.loads(output.getvalue())
        self.assertEqual("Duplicate notifications.", record["applies_when"])
        self.assertEqual("Notification delivery is unique.", record["not_when"])


if __name__ == "__main__":
    unittest.main()
