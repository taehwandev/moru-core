"""A run's unread required docs reach the model once, at its first file edit."""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_required_doc_delivery import (
    MARKER, MAX_REDELIVERIES, _contains_run, compaction_text, _read_spans, delivery_text, edited_paths,
)
from agent_closeout_command import closeout_project

STARTED = "2026-10-02T03:00:00+00:00"
CORE = "platforms/android/skills/sample/SKILL.md"
OTHER = "common/skills/testing/references/final-check.md"
BIG = "common/skills/big/references/current-guidance.md"


class ExactReadMatchingTests(unittest.TestCase):
    def test_repeated_prefix_comparisons_stay_linear(self) -> None:
        class CountedLine(str):
            comparisons = 0

            def __eq__(self, other):
                CountedLine.comparisons += 1
                return str.__eq__(self, other)

            def __ne__(self, other):
                CountedLine.comparisons += 1
                return str.__ne__(self, other)

        document = [CountedLine("repeat") for _ in range(199)] + [CountedLine("required rule")]
        output = [CountedLine("repeat") for _ in range(2000)]
        self.assertFalse(_contains_run(output, document))
        self.assertLessEqual(CountedLine.comparisons, 12 * (len(output) + len(document)))
        CountedLine.comparisons = 0
        self.assertEqual({}, _read_spans([CORE], {CORE: output}, "\n".join(["repeat"] * 200)))
        self.assertLessEqual(CountedLine.comparisons, 12 * (len(output) + 200))

    def test_a_complete_read_after_many_overlapping_prefixes_is_found(self) -> None:
        document = ["repeat"] * 199 + ["required rule"]
        output = ["repeat"] * 2000 + ["required rule"]
        self.assertTrue(_contains_run(output, document))
        self.assertFalse(_contains_run(output, document + ["missing rule"]))

    def test_partial_read_credit_matches_an_exact_unique_span(self) -> None:
        rng = random.Random(20261023)
        for _ in range(500):
            document = [rng.choice(("rule", "repeat", "한국어")) for _ in range(rng.randrange(1, 60))]
            if rng.randrange(2):
                start = rng.randrange(len(document))
                fragment = document[start:start + rng.randrange(1, 15)]
            else:
                fragment = [rng.choice(("rule", "repeat", "한국어", "absent")) for _ in range(rng.randrange(1, 15))]
            starts = [i for i in range(len(document) - len(fragment) + 1)
                      if document[i:i + len(fragment)] == fragment]
            expected = {CORE: range(starts[0], starts[0] + len(fragment))} if len(starts) == 1 else {}
            with self.subTest(document=document, fragment=fragment):
                self.assertEqual(bool(starts), _contains_run(document, fragment))
                self.assertEqual(expected, _read_spans([CORE], {CORE: document}, "\n".join(fragment)))

    def test_ambiguous_overlapping_partial_reads_do_not_count(self) -> None:
        self.assertEqual({}, _read_spans([CORE], {CORE: ["repeat"] * 2000}, "\n".join(["repeat"] * 200)))


class DeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        self.rules = base / "rules"
        self.project = base / "project"
        for doc, body in ((CORE, "## Must\n\n- Keep state immutable."),
                          (OTHER, "## Final\n\n- Run the tests."),
                          (BIG, "x" * 9000)):
            (self.rules / doc).parent.mkdir(parents=True, exist_ok=True)
            (self.rules / doc).write_text(f"---\nkeyflow_id: k\n---\n{body}\n", encoding="utf-8")
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        (self.project / ".moru" / "run-registry.json").write_text("{}", encoding="utf-8")
        self.evidence = run / "preflight.json"
        self.transcript = base / "transcript.jsonl"
        self._preflight([CORE, OTHER])
        self._transcript()

    def _preflight(self, docs: list[str]) -> None:
        self.evidence.write_text(json.dumps({
            "project": str(self.project), "rules": str(self.rules), "timestamp": STARTED,
            "route": {"required_docs": docs},
        }), encoding="utf-8")

    def _transcript(self, *calls, rows: list[dict] | None = None) -> None:
        """Claude Read calls as (stamp, doc[, output, is_error]); output defaults to the doc."""

        rows = list(rows or [])
        for index, (stamp, doc, *rest) in enumerate(calls):
            output = rest[0] if rest else (self.rules / doc).read_text(encoding="utf-8")
            rows.append({"type": "assistant", "timestamp": stamp, "message": {"content": [
                {"type": "tool_use", "id": f"t{index}", "name": "Read",
                 "input": {"file_path": f"{self.rules}/{doc}"}}]}})
            rows.append({"type": "user", "timestamp": stamp, "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{index}", "content": output,
                 "is_error": bool(rest[1]) if len(rest) > 1 else False}]}})
        self.transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def _deliver(self, evidence: Path | None = None) -> str:
        payload = {"tool_name": "Edit", "transcript_path": str(self.transcript),
                   "tool_input": {"file_path": str(self.project / "src" / "Screen.kt")}}
        found = self.evidence if evidence is None else evidence
        return delivery_text(payload, lambda project: found if project == self.project else None)

    def _compaction(self, evidence: Path | None = None, cwd: Path | None = None) -> str:
        payload = {"cwd": str(self.project if cwd is None else cwd), "transcript_path": str(self.transcript)}
        found = self.evidence if evidence is None else evidence
        return compaction_text(payload, lambda project: found if project == self.project else None)

    def test_a_compaction_event_hands_back_every_required_doc(self) -> None:
        self._transcript((STARTED, CORE))
        text = self._compaction()
        self.assertIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)

    def test_a_compaction_event_is_not_delivered_again_by_the_edit_check(self) -> None:
        self._transcript((STARTED, CORE))
        self._compaction()
        self.assertEqual("", self._deliver())
        self.assertEqual("", self._deliver())

    def test_a_later_compaction_still_reaches_the_edit_check_once_event_was_missed(self) -> None:
        self._transcript((STARTED, CORE))
        self._compaction()
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertIn("Keep state immutable.", self._deliver())

    def test_a_compaction_event_names_an_oversized_doc_instead_of_inlining_it(self) -> None:
        self._preflight([CORE, BIG])
        text = self._compaction()
        self.assertIn("Keep state immutable.", text)
        self.assertIn(f"{self.rules}/{BIG}", text)
        self.assertNotIn("x" * 100, text)

    def test_a_compaction_event_without_a_run_or_a_cwd_is_silent(self) -> None:
        self.assertEqual("", compaction_text({"transcript_path": str(self.transcript)}, lambda p: self.evidence))
        self.assertEqual("", self._compaction(cwd=self.project.parent / "elsewhere"))

    def _count_document_reads(self):
        counts = {CORE: 0, OTHER: 0}
        original = Path.read_text

        def read(path, *args, **kwargs):
            for doc in counts:
                if path == self.rules / doc:
                    counts[doc] += 1
            return original(path, *args, **kwargs)

        return counts, patch.object(Path, "read_text", read)

    def test_unread_docs_are_opened_once_and_the_marker_skips_future_reads(self) -> None:
        counts, reads = self._count_document_reads()
        with reads:
            first = self._deliver()
        self.assertIn("Keep state immutable.", first)
        self.assertIn("Run the tests.", first)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)
        counts, reads = self._count_document_reads()
        with reads:
            self.assertEqual("", self._deliver())
        self.assertEqual({CORE: 0, OTHER: 0}, counts)

    def test_proven_reuse_does_not_open_document_content(self) -> None:
        counts, reads = self._count_document_reads()
        with reads, patch("agent_required_doc_delivery.required_doc_reuse",
                          return_value={"reused": [CORE, OTHER], "unread": []}):
            self.assertEqual("", self._deliver())
        self.assertEqual({CORE: 0, OTHER: 0}, counts)

    def test_mixed_reuse_and_fresh_delivery_opens_only_the_fresh_doc_once(self) -> None:
        counts, reads = self._count_document_reads()
        with reads, patch("agent_required_doc_delivery.required_doc_reuse",
                          return_value={"reused": [CORE], "unread": [OTHER]}):
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 0, OTHER: 1}, counts)

    def test_transcript_comparison_and_rendering_share_the_document_read(self) -> None:
        self._transcript((STARTED, CORE))
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_missing_transcript_still_opens_each_delivered_doc_once(self) -> None:
        self.transcript.unlink()
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertIn("Keep state immutable.", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_a_missing_doc_is_attempted_once_and_other_docs_are_delivered(self) -> None:
        (self.rules / CORE).unlink()
        counts, reads = self._count_document_reads()
        with reads:
            text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn("Run the tests.", text)
        self.assertEqual({CORE: 1, OTHER: 1}, counts)

    def test_unread_docs_are_delivered_once(self) -> None:
        first = self._deliver()
        self.assertIn(f"=== {CORE} ===", first)
        self.assertIn("Keep state immutable.", first)
        self.assertIn("Run the tests.", first)
        self.assertNotIn("keyflow_id", first)
        self.assertEqual("", self._deliver())
        self.assertTrue((self.evidence.parent / MARKER).exists())

    def test_a_doc_read_before_the_run_started_still_counts(self) -> None:
        self._transcript(("2026-10-02T03:05:00.000Z", CORE), ("2026-10-02T02:00:00.000Z", OTHER))
        # Both readings are still in context, whichever side of `start` they fell on.
        self.assertEqual("", self._deliver())

    def test_a_compaction_drops_earlier_readings(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE), ("2026-10-02T02:00:00.000Z", OTHER))
        rows = [json.loads(line) for line in self.transcript.read_text(encoding="utf-8").splitlines()]
        rows.insert(2, {"type": "system", "subtype": "compact_boundary"})
        self.transcript.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
                                   encoding="utf-8")
        text = self._deliver()
        self.assertIn(f"=== {CORE} ===", text)
        self.assertNotIn(f"=== {OTHER} ===", text)

    def test_compaction_is_detected_independently_of_json_spacing(self) -> None:
        for boundary in ({"type": "system", "subtype": "compact_boundary"},
                         {"type": "compacted", "payload": {"message": "summary"}}):
            for separators in (None, (",", ":")):
                with self.subTest(boundary=boundary["type"], separators=separators):
                    (self.evidence.parent / MARKER).unlink(missing_ok=True)
                    self._transcript((STARTED, CORE), (STARTED, OTHER))
                    rows = [json.loads(line) for line in self.transcript.read_text().splitlines()]
                    rows.insert(2, boundary)
                    self.transcript.write_text("\n".join(json.dumps(row, separators=separators)
                                                        for row in rows) + "\n")
                    text = self._deliver()
                    self.assertIn(f"=== {CORE} ===", text)
                    self.assertNotIn(f"=== {OTHER} ===", text)

    def _append(self, *rows: dict) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_a_compaction_after_the_delivery_delivers_the_unread_docs_again(self) -> None:
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self.assertEqual("", self._deliver())
        self._append({"type": "assistant", "message": {"content": []}})
        self.assertEqual("", self._deliver())
        self._append({"type": "system", "subtype": "compact_boundary"})
        again = self._deliver()
        self.assertIn(f"=== {CORE} ===", again)
        self.assertIn(f"=== {OTHER} ===", again)
        self.assertEqual("", self._deliver())

    def test_docs_read_again_after_the_compaction_are_not_delivered(self) -> None:
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self._append({"type": "system", "subtype": "compact_boundary"})
        stamp = "2099-01-01T00:00:00.000Z"
        self._append(
            {"type": "assistant", "timestamp": stamp, "message": {"content": [
                {"type": "tool_use", "id": "r1", "name": "Read",
                 "input": {"file_path": f"{self.rules}/{CORE}"}}]}},
            {"type": "user", "timestamp": stamp, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r1",
                 "content": (self.rules / CORE).read_text(encoding="utf-8")}]}})
        again = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", again)
        self.assertIn(f"=== {OTHER} ===", again)

    def test_redelivery_is_bounded_per_run(self) -> None:
        from agent_required_doc_delivery import MAX_REDELIVERIES

        self._deliver()
        for _ in range(MAX_REDELIVERIES):
            self._append({"type": "system", "subtype": "compact_boundary"})
            self.assertIn(f"=== {CORE} ===", self._deliver())
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertEqual("", self._deliver())

    def test_a_reuse_proof_does_not_survive_a_compaction(self) -> None:
        reuse = patch("agent_required_doc_delivery.required_doc_reuse",
                      return_value={"reused": [CORE], "unread": [OTHER]})
        with reuse:
            first = self._deliver()
            self.assertNotIn(f"=== {CORE} ===", first)
            self._append({"type": "system", "subtype": "compact_boundary"})
            again = self._deliver()
        self.assertIn(f"=== {CORE} ===", again)
        self.assertIn(f"=== {OTHER} ===", again)

    def test_a_compaction_row_written_after_a_partial_line_is_still_found(self) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write('{"type": "assistant", "message": {"content": [')  # still being written
        self.assertIn(f"=== {CORE} ===", self._deliver())
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(']}}\n' + json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_large_partial_compaction_line_keeps_the_previous_offset_until_completed(self) -> None:
        from agent_required_doc_delivery import _aligned_size

        self._append({"type": "assistant", "message": {"content": []}})
        prior_offset = self.transcript.stat().st_size
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write('{"type": "compacted", "payload": {"summary": "' + ("x" * 70000))
        self.assertEqual(prior_offset, _aligned_size(self.transcript, prior_offset))
        self.assertEqual(0, _aligned_size(self.transcript))
        self.assertIn(f"=== {CORE} ===", self._deliver())
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write('"}}\n')
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_an_unterminated_compaction_json_line_waits_for_its_newline_and_delivers_once(self) -> None:
        self.assertIn(f"=== {CORE} ===", self._deliver())
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "system", "subtype": "compact_boundary"}))
        self.assertEqual("", self._deliver())
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self.assertEqual("", self._deliver())
        state = json.loads((self.evidence.parent / MARKER).read_text(encoding="utf-8"))
        self.assertEqual(1, state["redeliveries"])

    def test_no_transcript_path_records_no_offset_instead_of_a_directory_size(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(self.project / "a.kt")}}
        delivery_text(payload, lambda project: self.evidence if project == self.project else None)
        state = json.loads((self.evidence.parent / MARKER).read_text(encoding="utf-8"))
        self.assertEqual(0, state["transcript_bytes"])

    def test_a_shrunken_transcript_is_scanned_again_from_the_start(self) -> None:
        self._append(*({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 50}]}}
                       for _ in range(5)))
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self.transcript.write_text(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n",
                                   encoding="utf-8")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def _closeout(self) -> str:
        payload = {"tool_name": "Bash", "transcript_path": str(self.transcript), "cwd": "/elsewhere",
                   "tool_input": {"command": f"moru-hook finish --project {self.project} --rules {self.rules}"}}
        project = closeout_project(payload)
        edit = {**payload, "tool_name": "Edit", "tool_input": {"file_path": str(project)}}
        return delivery_text(edit, lambda found: self.evidence if found == self.project else None, closeout=True)

    def test_a_closeout_command_names_its_project_and_other_commands_do_not(self) -> None:
        def project(command: str, cwd: str = "/w"):
            return closeout_project({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}})

        self.assertEqual(Path("/p"), project("~/.moru/bin/moru-hook finish --project /p --rules /r"))
        self.assertEqual(Path("/p q"), project("moru-hook review --project '/p q'"))
        self.assertEqual(Path("/w/rel"), project("moru-hook gate-batch --project rel"))
        self.assertEqual(Path("/w"), project("moru-hook finish"))
        self.assertIsNone(project("moru-hook start --project /p"))
        self.assertIsNone(project("git status"))
        self.assertIsNone(project("cat moru-hook-notes.md"))
        # Shell words, not substrings: mentions are not closeouts, a chained cd moves relative paths.
        self.assertIsNone(project('rg "moru-hook finish" scripts/'))
        self.assertIsNone(project('git commit -m "run moru-hook review --project /p"'))
        self.assertIsNone(project("echo moru-hook finish"))
        self.assertEqual(Path("/proj"), project("cd /proj && moru-hook finish --project ."))
        self.assertEqual(Path("/proj/sub"), project("cd /proj; moru-hook review --project sub"))
        self.assertEqual(Path("/proj"), project("cd /proj\nmoru-hook gate-batch"))
        self.assertEqual(Path("/p"), project("MORU_X=1 moru-hook finish --project=/p"))
        self.assertEqual(Path("/p"), project("python3 /r/scripts/agent-hook.py finish --project /p"))
        self.assertEqual(Path("/p"), project("moru-hook start --project /wrong && moru-hook finish --project /p"))
        # Edge syntax that broke the first parser: it must not raise and must stay accurate.
        self.assertIsNone(project("cd ~nosuchuser_zz && git push # finish"))
        self.assertEqual(Path("/w"), project("cd ~nosuchuser_zz; moru-hook finish --project ~nosuchuser_zz"))
        self.assertEqual(Path("/p"), project("moru-hook finish \\\n  --project /p"))
        self.assertEqual(Path("/p"), project("# closeout\nmoru-hook finish --project /p"))
        self.assertEqual(Path("/p"), project("python3 -u /r/scripts/agent-hook.py finish --project /p"))
        self.assertEqual(Path("/p"), project("env A=1 moru-hook finish --project /p"))
        self.assertEqual(Path("/proj"), project("(cd /proj && moru-hook finish --project .)"))
        self.assertEqual(Path("/proj"), project("cd -P /proj && moru-hook finish --project ."))
        self.assertEqual(Path("/w"), project("cd /missing || moru-hook finish --project ."))
        self.assertIsNone(project("python3 cd /tmp"))
        self.assertEqual(Path("/p"), project("moru-hook finish --project /p # don't skip"))
        self.assertIsNone(project("# cd /tmp && moru-hook finish\ngit status"))
        self.assertEqual(Path("/w"), project("moru-hook finish # --project /wrong"))
        self.assertEqual(Path("/w"), project('moru-hook finish --project "$TARGET"'))
        self.assertEqual(Path("/p"), project("git commit -m 'a\nb'\nmoru-hook finish --project /p"))

    def test_a_late_compaction_is_caught_at_the_closeout_command(self) -> None:
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertIn(f"=== {CORE} ===", self._closeout())
        self.assertEqual("", self._closeout())

    def test_the_closeout_keeps_one_redelivery_the_edits_cannot_spend(self) -> None:
        self._deliver()
        for _ in range(MAX_REDELIVERIES):
            self._append({"type": "system", "subtype": "compact_boundary"})
            self.assertIn(f"=== {CORE} ===", self._deliver())
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertEqual("", self._deliver())
        self.assertIn(f"=== {CORE} ===", self._closeout())
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertEqual("", self._closeout())

    def test_a_held_lock_delays_delivery_but_never_stalls_it(self) -> None:
        import fcntl
        import agent_required_doc_delivery as module

        lock = self.evidence.parent / (MARKER + ".lock")
        with lock.open("a") as handle, patch.object(module, "_LOCK_WAIT_SECONDS", 0.1):
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_reuse_proof_is_void_when_a_compaction_came_before_the_first_delivery(self) -> None:
        self._append({"type": "system", "subtype": "compact_boundary"})
        with patch("agent_required_doc_delivery.required_doc_reuse",
                   return_value={"reused": [CORE], "unread": []}):
            self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_reuse_proof_is_void_by_a_compaction_before_this_run_started(self) -> None:
        # The proof carries no time: a compaction between the earlier run and this
        # one (before this run's preflight) may have evicted the doc, so deliver it.
        self._append({"type": "system", "subtype": "compact_boundary",
                      "timestamp": "2026-10-02T02:00:00.000Z"})
        with patch("agent_required_doc_delivery.required_doc_reuse",
                   return_value={"reused": [CORE], "unread": []}):
            self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_reuse_proof_is_void_when_a_compaction_is_newer_than_this_run(self) -> None:
        self._append({"type": "system", "subtype": "compact_boundary",
                      "timestamp": "2026-10-02T03:05:00.000Z"})
        with patch("agent_required_doc_delivery.required_doc_reuse",
                   return_value={"reused": [CORE], "unread": []}):
            self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_reuse_proof_still_holds_without_any_compaction(self) -> None:
        with patch("agent_required_doc_delivery.required_doc_reuse",
                   return_value={"reused": [CORE], "unread": []}):
            self.assertNotIn(f"=== {CORE} ===", self._deliver())

    def test_an_old_marker_with_no_compaction_is_upgraded_in_place_without_delivering(self) -> None:
        marker = self.evidence.parent / MARKER
        marker.write_text(json.dumps({"delivered": [CORE]}), encoding="utf-8")
        self._append({"type": "assistant"})
        self.assertEqual("", self._deliver())
        upgraded = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(self.transcript.stat().st_size, upgraded["transcript_bytes"])
        self.assertEqual(0, upgraded["redeliveries"])
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_an_old_marker_with_a_compaction_already_in_the_transcript_delivers_once(self) -> None:
        # When the old marker was written is unknown, so the compaction may be after it.
        (self.evidence.parent / MARKER).write_text(json.dumps({"delivered": []}), encoding="utf-8")
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self.assertEqual("", self._deliver())

    def test_a_compaction_before_the_delivery_does_not_repeat_it(self) -> None:
        self._append({"type": "system", "subtype": "compact_boundary"})
        self.assertIn(f"=== {CORE} ===", self._deliver())
        self.assertEqual("", self._deliver())

    def test_a_doc_changed_after_its_reading_is_delivered(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE))
        (self.rules / CORE).write_text("## Must\n\n- Keep state immutable.\n- A newer rule.\n", encoding="utf-8")
        self.assertIn("A newer rule.", self._deliver())

    def test_deleting_or_reordering_rules_invalidates_an_old_read(self) -> None:
        body = "## Rules\n- First rule.\n- Removed rule.\n- Last rule.\n"
        for current in ("## Rules\n- First rule.\n- Last rule.\n",
                        "## Rules\n- Last rule.\n- Removed rule.\n- First rule.\n"):
            with self.subTest(current=current):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                (self.rules / CORE).write_text(body)
                self._transcript((STARTED, CORE))
                (self.rules / CORE).write_text(current)
                self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_complete_numbered_partial_reads_are_reused(self) -> None:
        body = (self.rules / CORE).read_text().splitlines(keepends=True)
        for numbered in (False, True):
            with self.subTest(numbered=numbered):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                lines = [f"{index + 1}\t{line}" if numbered else line
                         for index, line in enumerate(body)]
                self._transcript((STARTED, CORE, "".join(lines[:3])),
                                 (STARTED, CORE, "".join(lines[3:])))
                self.assertNotIn(f"=== {CORE} ===", self._deliver())

    def test_a_compaction_resets_partial_read_coverage(self) -> None:
        body = (self.rules / CORE).read_text().splitlines(keepends=True)
        self._transcript((STARTED, CORE, "".join(body[:3])),
                         (STARTED, CORE, "".join(body[3:])))
        rows = [json.loads(line) for line in self.transcript.read_text().splitlines()]
        rows.insert(2, {"type": "compacted"})
        self.transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_partial_read_does_not_count(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "1\t---\n2\tkeyflow_id: k\n3\t---\n4\t## Must"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_searches_failed_and_partial_reads_do_not_count(self) -> None:
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "Found 1 file"),
                         ("2026-10-02T02:00:00.000Z", OTHER, "File does not exist.", True))
        text = self._deliver()
        self.assertIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_a_codex_command_read_counts(self) -> None:
        body = (self.rules / CORE).read_text(encoding="utf-8")
        self._transcript(rows=[{"timestamp": "2026-10-02T02:00:00.000Z", "type": "event_msg", "payload": {
            "type": "item_completed", "item": {"type": "CommandExecution", "id": "e1", "status": "completed",
                                               "command": ["/bin/zsh", "-lc", f"cat {self.rules}/{CORE}"],
                                               "stdout": body}}}])
        text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_structured_codex_outputs_reuse_complete_reads(self) -> None:
        body = (self.rules / CORE).read_text() + '- Use "settings".\n'
        (self.rules / CORE).write_text(body)
        for kind in ("function_call", "custom_tool_call"):
            for serialized in (False, True):
                with self.subTest(kind=kind, serialized=serialized):
                    (self.evidence.parent / MARKER).unlink(missing_ok=True)
                    output = {"output": body, "exit_code": 0}
                    self._transcript(rows=[
                        {"type": "response_item", "payload": {
                            "type": kind, "call_id": "r1", "name": "exec_command",
                            "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
                        {"type": "response_item", "payload": {
                            "type": kind + "_output", "call_id": "r1",
                            "output": json.dumps(output) if serialized else output}},
                    ])
                    self.assertNotIn(f"=== {CORE} ===", self._deliver())

    def test_a_failed_codex_read_cannot_supply_partial_coverage(self) -> None:
        body = (self.rules / CORE).read_text()
        self._transcript(rows=[
            {"type": "response_item", "payload": {
                "type": "function_call", "call_id": "r1",
                "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
            {"type": "response_item", "payload": {
                "type": "function_call_output", "call_id": "r1",
                "output": {"output": body, "exit_code": 1}}},
        ])
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def _orchestrated_read(self, output: str) -> str:
        (self.evidence.parent / MARKER).unlink(missing_ok=True)
        self._transcript(rows=[
            {"type": "response_item", "payload": {
                "type": "custom_tool_call", "call_id": "r1", "name": "functions.exec",
                "input": f'const r = await tools.exec_command({{cmd:"cat {self.rules}/{CORE} {self.rules}/{OTHER}"}}); text(r);'}},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "r1", "output": output},
             "timestamp": "2099-01-01T00:00:00Z"},
        ])
        return self._deliver()

    def test_orchestration_json_items_preserve_complete_reads(self) -> None:
        items = [json.dumps({"i": i, "result": {"status": "fulfilled", "value": {
            "output": (self.rules / doc).read_text(), "exit_code": 0}}})
                 for i, doc in enumerate((CORE, OTHER))]
        for output in ("".join(items), "\n".join(items),
                       "Script completed\nWall time 0.3 seconds\nOutput:\n" + "".join(items)):
            with self.subTest(output=output):
                self.assertEqual("", self._orchestrated_read(output))

    def test_orchestration_failed_and_incomplete_results_stay_unread(self) -> None:
        first = json.dumps({"output": (self.rules / CORE).read_text(), "exit_code": 0})
        second = {"output": (self.rules / OTHER).read_text(), "exit_code": 0}
        for output in (first + json.dumps(second)[:-1], first + " trailing noise",
                       "Script running with cell ID 1\nOutput:\n" + first + json.dumps(second),
                       "Script completed\nOutput:\n" + first + json.dumps(second),
                       first + json.dumps({**second, "exit_code": 1})):
            with self.subTest(output=output):
                self.assertIn(f"=== {OTHER} ===", self._orchestrated_read(output))

        raw_pending = "Script running with cell ID 1\nOutput:\n" + (self.rules / OTHER).read_text()
        self.assertIn(f"=== {OTHER} ===", self._orchestrated_read(raw_pending))

    def test_orchestration_does_not_credit_a_rejected_nested_result(self) -> None:
        output = json.dumps({"result": {"status": "rejected", "value": {
            "output": (self.rules / CORE).read_text(), "exit_code": 0}}})
        self.assertIn(f"=== {CORE} ===", self._orchestrated_read(output))

    def test_orchestration_completed_sibling_does_not_credit_pending_command(self) -> None:
        first = json.dumps({"output": (self.rules / CORE).read_text(), "exit_code": 0})
        body = (self.rules / OTHER).read_text()
        for pending in ({"output": body, "session_id": 42},
                        {"output": body, "session_id": 42, "exit_code": None},
                        *({"output": body, "status": status}
                          for status in ("pending", "running", "in_progress"))):
            with self.subTest(pending=pending):
                output = first + json.dumps({"result": {"status": "fulfilled", "value": pending}})
                delivered = self._orchestrated_read(output)
                self.assertNotIn(f"=== {CORE} ===", delivered)
                self.assertIn(f"=== {OTHER} ===", delivered)

        completed = first + json.dumps({"output": body, "session_id": 42, "exit_code": 0})
        self.assertEqual("", self._orchestrated_read(completed))

    def test_codex_wrappers_preserve_text_and_failed_commands_stay_unread(self) -> None:
        body = (self.rules / CORE).read_text()
        for output, read in (
            ({"result": {"status": "fulfilled", "value": {"output": body, "exit_code": 0}}}, True),
            ({"content": [{"type": "text", "text": json.dumps({"output": body})}]}, True),
            (f"Chunk ID: c1\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n{body}", True),
            (f"Chunk ID: c1\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\n{body}", False),
        ):
            with self.subTest(output=output):
                (self.evidence.parent / MARKER).unlink(missing_ok=True)
                self._transcript(rows=[
                    {"type": "response_item", "payload": {
                        "type": "function_call", "call_id": "r1",
                        "arguments": json.dumps({"cmd": f"cat {self.rules}/{CORE}"})}},
                    {"type": "response_item", "payload": {
                        "type": "function_call_output", "call_id": "r1", "output": output}},
                ])
                self.assertEqual(not read, f"=== {CORE} ===" in self._deliver())

    def test_repeated_lines_need_unambiguous_partial_read_evidence(self) -> None:
        (self.rules / CORE).write_text("Repeated rule.\nUnique rule.\nRepeated rule.\n")
        self._transcript((STARTED, CORE, "Repeated rule.\n"),
                         (STARTED, CORE, "Unique rule.\n"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_batched_read_reuses_each_complete_doc_in_command_order(self) -> None:
        body = (self.rules / OTHER).read_text() + (self.rules / CORE).read_text()
        self._transcript(rows=[{"type": "event_msg", "payload": {
            "item": {"type": "CommandExecution", "id": "r1", "status": "completed",
                     "exit_code": 0, "command": f"cat {self.rules}/{OTHER} {self.rules}/{CORE}",
                     "stdout": body}}}])
        self.assertEqual("", self._deliver())

    def test_a_doc_inside_a_compound_read_counts(self) -> None:
        body = (self.rules / CORE).read_text()
        self._transcript(("2099-01-01T00:00:00.000Z", CORE, f"## Other file\n- unrelated\n{body}trailing output\n"))
        text = self._deliver()
        self.assertNotIn(f"=== {CORE} ===", text)
        self.assertIn(f"=== {OTHER} ===", text)

    def test_a_compound_read_of_a_since_changed_doc_does_not_count(self) -> None:
        """An old version whose trailing rule was deleted still holds the new text unbroken."""

        (self.rules / CORE).write_text("## Rules\n- First rule.\n- Removed rule.\n")
        self._transcript(("2026-10-02T02:00:00.000Z", CORE, "noise\n## Rules\n- First rule.\n- Removed rule.\n"))
        (self.rules / CORE).write_text("## Rules\n- First rule.\n")
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_a_line_inserted_inside_the_doc_breaks_a_compound_read(self) -> None:
        self._transcript(("2099-01-01T00:00:00.000Z", CORE,
                          "noise\n---\nkeyflow_id: k\n---\n## Must\n- An old rule.\n- Keep state immutable.\n"))
        self.assertIn(f"=== {CORE} ===", self._deliver())

    def test_everything_read_delivers_nothing_but_still_marks_the_run(self) -> None:
        self._transcript(("2026-10-02T03:05:00.000Z", CORE), ("2026-10-02T03:06:00.000Z", OTHER))
        self.assertEqual("", self._deliver())
        self.assertTrue((self.evidence.parent / MARKER).exists())

    def test_a_doc_over_the_inline_cap_is_named_not_inlined(self) -> None:
        self._preflight([BIG, CORE])
        text = self._deliver()
        self.assertIn(f"{self.rules / BIG} (", text)
        self.assertIn("whole, with no line range", text)
        self.assertNotIn("x" * 100, text)
        self.assertIn(f"=== {CORE} ===", text)

    def test_no_session_run_or_broken_evidence_delivers_nothing(self) -> None:
        self.assertEqual("", self._deliver(evidence=Path("/nonexistent/preflight.json")))
        self.evidence.write_text("not json", encoding="utf-8")
        self.assertEqual("", self._deliver())

    def test_codex_apply_patch_names_its_files(self) -> None:
        payload = {"cwd": str(self.project), "tool_input": {
            "command": "*** Begin Patch\n*** Update File: src/Screen.kt\n@@\n-a\n+b\n*** End Patch"}}
        self.assertIn(self.project / "src" / "Screen.kt", edited_paths(payload))


class GateCarriesTheDeliveryTests(unittest.TestCase):
    def test_the_context_rides_on_the_verdict_without_changing_it(self) -> None:
        import io
        from contextlib import redirect_stdout

        import claude_pretool_gate as gate

        for runtime in ("claude", "codex"):
            with self.subTest(runtime=runtime), patch.dict(os.environ, {"MORU_PRETOOL_RUNTIME": runtime}):
                gate._PENDING_CONTEXT.append("delivered docs")
                output = io.StringIO()
                with redirect_stdout(output):
                    gate.allow()
                hook = json.loads(output.getvalue())["hookSpecificOutput"]
                self.assertEqual("delivered docs", hook["additionalContext"])
                self.assertNotIn("permissionDecision", hook)
                self.assertNotIn("systemMessage", json.loads(output.getvalue()))

    def test_a_closeout_command_queues_the_delivery_and_other_bash_does_not(self) -> None:
        import claude_pretool_gate as gate

        calls = []

        def fake(payload, evidence_for, read_in_context=None, *, closeout=False):
            calls.append((payload["tool_input"], closeout))
            return "docs"

        class Reader:
            @staticmethod
            def resolve_runtime_evidence(project, identity):
                return None

        for command, queued in (("moru-hook finish --project /p", True), ("ls", False)):
            gate._PENDING_CONTEXT.clear()
            calls.clear()
            payload = {"tool_name": "Bash", "session_id": "s", "cwd": "/w", "tool_input": {"command": command}}
            with patch("agent_required_doc_delivery.delivery_text", fake), \
                    patch.object(gate, "_run_evidence_reader", return_value=Reader), \
                    patch.object(gate, "gate_enabled", return_value=True):
                gate._queue_unread_required_docs(payload)
            self.assertEqual(queued, bool(gate._PENDING_CONTEXT), command)
            if queued:
                self.assertEqual([({"file_path": "/p"}, True)], calls)
        gate._PENDING_CONTEXT.clear()


if __name__ == "__main__":
    unittest.main()
