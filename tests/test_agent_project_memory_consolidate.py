"""Consolidate reports records that need an agent decision and changes nothing."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_project_memory import SCHEMA_VERSION, _digest, store_dir  # noqa: E402
from agent_project_memory_consolidate import consolidate, summary_line  # noqa: E402

TODAY = date(2026, 10, 7)


class ConsolidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        state_home = mock.patch.dict(os.environ, {"MORU_STATE_HOME": str(self.project / "state-home")})
        state_home.start()
        self.addCleanup(state_home.stop)
        self.store = store_dir(self.project)
        self.store.mkdir(parents=True)
        self.counter = 0

    def write(self, body: str, *, scope: str = "task", source: str = "",
              days: int = 60, status: str = "active", replaces: str = "") -> dict:
        """Write a valid record directly, so past review dates are possible."""
        self.counter += 1
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": f"{self.counter:016x}",
            "status": status,
            "scope": scope,
            "body": body,
            "source": source or f"source {self.counter}",
            "review_on": (TODAY + timedelta(days=days)).isoformat(),
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        if replaces:
            record["replaces"] = replaces
        record["digest"] = _digest(record)
        (self.store / f'{record["id"]}.json').write_text(json.dumps(record), encoding="utf-8")
        return record

    def report(self, **kwargs) -> dict:
        return consolidate(self.project, today=TODAY, **kwargs)

    def test_an_empty_or_missing_store_has_no_findings(self) -> None:
        report = self.report()
        self.assertEqual([], report["expired"] + report["expiring"] + report["duplicate_groups"])
        self.assertEqual(0, report["unreadable"])
        self.assertEqual("", summary_line(report, self.project, "moru-hook"))

    def test_expired_and_expiring_follow_the_review_date(self) -> None:
        expired = self.write("Due today", days=0)
        past = self.write("Long overdue", days=-5)
        soon = self.write("Due soon", days=14)
        self.write("Due later", days=15)
        self.write("Retired and overdue", days=-5, status="retired")
        report = self.report()
        self.assertEqual([expired["id"], past["id"]], [item["id"] for item in report["expired"]])
        self.assertEqual([soon["id"]], [item["id"] for item in report["expiring"]])
        self.assertEqual("Due today", report["expired"][0]["body"])
        self.assertIn("reason", report["expired"][0])
        self.assertEqual([], [item["id"] for item in self.report(within_days=13)["expiring"]])

    def test_near_identical_bodies_in_overlapping_scopes_are_grouped(self) -> None:
        first = self.write("Run the adapter contract check before editing the adapter.")
        general = self.write("run the adapter contract check, before editing the adapter", scope="all")
        self.write("Run the adapter contract check before editing the adapter.", scope="review")
        report = self.report()
        # `review` pairs with `all` too, so all three are one chain.
        [group] = report["duplicate_groups"]
        self.assertEqual(3, len(group["ids"]))
        self.assertEqual(sorted(group["ids"]), group["ids"])
        self.assertIn(first["id"], group["ids"])
        self.assertIn(general["id"], group["ids"])

    def test_different_route_scopes_are_not_duplicates(self) -> None:
        self.write("Run the adapter contract check first.", scope="task")
        self.write("Run the adapter contract check first.", scope="review")
        self.assertEqual([], self.report()["duplicate_groups"])

    def test_a_below_threshold_near_duplicate_is_not_reported(self) -> None:
        # 5 shared of 7 distinct words: Jaccard 0.71 < 0.8.
        self.write("run the adapter contract check first")
        self.write("run the adapter contract check now")
        self.assertEqual([], self.report()["duplicate_groups"])

    def test_shared_sources_are_grouped_after_normalization(self) -> None:
        one = self.write("Prefer the queue.", source="docs/design.md")
        two = self.write("Avoid the queue entirely.", source="DOCS/design.md ")
        self.write("Unrelated.", source="docs/other.md")
        self.write("Retired copy.", source="docs/design.md", status="retired")
        [group] = self.report()["shared_source_groups"]
        self.assertEqual(sorted([one["id"], two["id"]]), group["ids"])
        self.assertEqual({"Prefer the queue.", "Avoid the queue entirely."},
                         {item["body"] for item in group["records"]})

    def test_a_replaced_but_live_record_is_an_unfinished_replacement(self) -> None:
        old = self.write("Old advice about the guard.")
        new = self.write("Corrected advice about retries.", replaces=old["id"])
        finished = self.write("Finished replacement.", status="retired")
        self.write("Its successor.", replaces=finished["id"])
        [finding] = self.report()["unfinished_replacements"]
        self.assertEqual(old["id"], finding["id"])
        self.assertEqual([new["id"]], finding["replaced_by"])

    def test_unreadable_files_are_only_counted(self) -> None:
        self.write("Valid record.")
        (self.store / "0123456789abcdef.json").write_text("{not json SECRET", encoding="utf-8")
        tampered = self.write("Tampered body.")
        path = self.store / f'{tampered["id"]}.json'
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["body"] = "Changed on disk"
        path.write_text(json.dumps(payload), encoding="utf-8")
        report = self.report()
        self.assertEqual(2, report["unreadable"])
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertNotIn("Changed on disk", json.dumps(report))

    def test_the_summary_line_holds_counts_only(self) -> None:
        self.write("Confidential guidance body.", days=0)
        self.write("Same source body.", source="shared", days=90)
        self.write("Other source body.", source="shared", days=90)
        line = summary_line(self.report(), self.project, "/home/u/.moru/bin/moru-hook")
        self.assertEqual(
            "Project memory upkeep: expired=1 expiring=0 duplicates=0 shared_source=1 "
            f"unfinished=0 -> /home/u/.moru/bin/moru-hook project-memory --project {self.project} "
            "consolidate",
            line,
        )
        self.assertNotIn("Confidential", line)

    def test_negative_window_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "within-days"):
            self.report(within_days=-1)

    def test_startup_notice_never_runs_pairwise_similarity(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        records = [self.write("Secret body one", source="shared", days=0),
                   self.write("Secret body two", source="shared")]
        with mock.patch("agent_project_memory_consolidate._jaccard",
                        side_effect=AssertionError("pairwise work during startup")):
            line = startup_summary_line(records, self.project, "moru-hook", today=TODAY)
        self.assertIn("expired=1 exact_duplicates=0 shared_source=1 unfinished=0", line)
        self.assertNotIn("Secret", line)
        self.assertIn("consolidate", line)

    def test_startup_exact_groups_respect_scope_bridges_and_retirement(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        records = [self.write("Same advice.", scope=scope) for scope in ("task", "review")]
        self.assertEqual("", startup_summary_line(records, self.project, "moru-hook", today=TODAY))
        records.append(self.write("SAME advice", scope="all"))
        records.append(self.write("Same advice", scope="all", status="retired"))
        self.assertIn("exact_duplicates=1", startup_summary_line(
            records, self.project, "moru-hook", today=TODAY))

    def test_near_duplicate_detection_stays_available_on_demand(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        records = [self.write("alpha bravo charlie delta echo foxtrot"),
                   self.write("alpha bravo charlie delta echo foxtrot golf")]
        self.assertEqual("", startup_summary_line(records, self.project, "moru-hook", today=TODAY))
        self.assertEqual(1, len(self.report()["duplicate_groups"]))

    def test_startup_unfinished_counts_use_current_live_records(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        old = self.write("Old advice")
        new = self.write("Corrected advice", replaces=old["id"])
        records = [old, new, self.write("Retired", status="retired", replaces=new["id"])]
        self.assertIn("unfinished=1", startup_summary_line(
            records, self.project, "moru-hook", today=TODAY))

    def test_startup_empty_and_punctuation_only_bodies_do_not_create_duplicate_hints(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        self.assertEqual("", startup_summary_line([], self.project, "moru-hook", today=TODAY))
        records = [self.write("!!!"), self.write("???")]
        self.assertEqual("", startup_summary_line(records, self.project, "moru-hook", today=TODAY))

    def test_startup_counts_disjoint_exact_groups_and_legacy_live_statuses(self) -> None:
        from agent_project_memory_consolidate import startup_summary_line

        records = [self.write("Same advice", scope=scope, status=status)
                   for scope in ("task", "review") for status in ("pending", "approved")]
        self.assertIn("exact_duplicates=2", startup_summary_line(
            records, self.project, "moru-hook", today=TODAY))

    def test_startup_work_grows_linearly_without_building_full_findings(self) -> None:
        from agent_project_memory_consolidate import normalize, startup_summary_line

        records = [{"id": f"{n:016x}", "body": f"note{n}", "source": f"source{n}",
                    "scope": "all", "status": "active", "review_on": "2099-01-01"}
                   for n in range(5000)]
        with mock.patch("agent_project_memory_consolidate.normalize", wraps=normalize) as normalized, \
                mock.patch("agent_project_memory_consolidate.findings", side_effect=AssertionError), \
                mock.patch("agent_project_memory_consolidate._duplicate_groups", side_effect=AssertionError):
            self.assertEqual("", startup_summary_line(records, self.project, "moru-hook", today=TODAY))
        self.assertLessEqual(normalized.call_count, 3 * len(records))


if __name__ == "__main__":
    unittest.main()
