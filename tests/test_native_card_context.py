"""Native card liveness and recall preserve canonical ordering and write dispatch."""
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import agent_work_cards as cards
from support.native_cards import NativeCards
from support.native_probe_transport import NativeProbe
import test_native_work_cards as fixtures


class NativeCardContextTests(unittest.TestCase):
    setUp = fixtures.NativeWorkCardTests.setUp
    key = fixtures.NativeWorkCardTests.key
    store = fixtures.NativeWorkCardTests.store
    insert = fixtures.NativeWorkCardTests.insert

    def seed(self, states):
        with closing(self.store()) as connection:
            for index in range(1, len(states)+1):
                self.insert(connection, index, stamp=f"{1000-index:04}")
            connection.commit()
        self.registry = self.project / ".moru/run-registry.json"
        self.registry.write_text(json.dumps({"runs": [
            {"run_id": f"{i:032x}", "state": state} for i, state in enumerate(states, 1)]}))

    def reference(self, current="f"*32, settle=False):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            return cards.open_card_lines(self.project, current, settle_stale=settle)

    def native(self, current="f"*32, settle=False):
        with patch.dict(os.environ, {**self.env, "PATH": str(self.git_only)}, clear=True):
            self.assertIsNotNone(NativeCards.context(self.project, current))
            with patch.object(cards, "_stale_state", side_effect=AssertionError("Python policy replay")), \
                    patch.object(cards, "_connect_readonly", side_effect=AssertionError("Python SQLite replay")):
                return cards.open_card_lines(self.project, current, settle_stale=settle)

    def raw(self):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--cards-probe", "context"], input=json.dumps({"repo": self.key(), "current_work_id": "f"*32}).encode(),
            env={**self.env, "PATH": str(self.empty)}, cwd=self.project, capture_output=True, timeout=3)

    def test_selection_current_exclusion_states_unicode_and_no_writes(self):
        self.seed(["running", "completed", "cancelled", "unknown-nonempty", False, {"nested": True}])
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE cards SET summary='한😀 recall',updated_at='z😀abcdefghi-more' WHERE work_id=?", (f"{1:032x}",))
            connection.commit()
        before = self.database.read_bytes(), self.registry.read_bytes()
        for current in ("f"*32, f"{1:032x}"):
            self.assertEqual(self.reference(current), self.native(current))
        self.assertEqual(before, (self.database.read_bytes(), self.registry.read_bytes()))

    def test_check_and_render_limits_skip_unused_fields_and_count_unchecked(self):
        self.seed(["running"]*25)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE cards SET command=X'00FF' WHERE work_id=?", (f"{4:032x}",))
            connection.execute("UPDATE cards SET project=X'00FF' WHERE work_id=?", (f"{25:032x}",))
            connection.commit()
        expected = self.reference()
        self.assertEqual(5, len(expected))
        self.assertIn("22 more", expected[-1])
        self.assertEqual(expected, self.native())

    def test_unchecked_cards_are_counted_even_when_all_checked_cards_are_stale(self):
        self.seed(["completed"]*23)
        expected = self.reference()
        self.assertEqual(2, len(expected))
        self.assertIn("3 more", expected[-1])
        self.assertEqual(expected, self.native())

    def test_missing_removed_invalid_and_duplicate_registry_records(self):
        self.seed(["running"]*3)
        payloads = [b"not JSON\xff", b"{broken", b"null", b'{"runs":{}}', b'{"runs":"text"}',
            json.dumps({"runs": [{"run_id": f"{1:032x}", "state": "completed"},
                {"run_id": f"{1:032x}", "state": [True]},
                {"run_id": f"{2:032x}", "state": 0}]}).encode()]
        for payload in payloads:
            self.registry.write_bytes(payload)
            self.assertEqual(self.reference(), self.native())
        self.registry.unlink()
        self.assertEqual(self.reference(), self.native())
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE cards SET project=?", (str(self.base / "removed-project"),))
            connection.commit()
        self.assertEqual(self.reference(), self.native())

    def test_null_runs_declines_and_keeps_original_type_error(self):
        self.seed(["running"])
        self.registry.write_text('{"runs":null}')
        with patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(NativeCards.context(self.project, "f"*32))
            with self.assertRaises(TypeError):
                cards.open_card_lines(self.project, "f"*32)
        with self.assertRaises(TypeError):
            self.reference()

    def test_symlink_and_fifo_registry_decline_before_stream_consumption(self):
        self.seed(["running"])
        target = self.base / "actual-registry.json"
        self.registry.replace(target)
        self.registry.symlink_to(target)
        done = self.raw()
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        self.registry.unlink()
        os.mkfifo(self.registry)
        done = self.raw()
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))

    def test_stale_settlement_has_same_order_and_abort_after_first_error(self):
        self.seed(["completed", "cancelled", "running", "completed"])
        expected_calls = []
        def record(project, work, state):
            expected_calls.append((work, state))
            if len(expected_calls) == 2:
                raise sqlite3.OperationalError("synthetic write failure")
        with patch.object(cards, "settle_card", side_effect=record):
            expected = self.reference(settle=True)
        native_calls = []
        def native_record(project, work, state):
            native_calls.append((work, state))
            if len(native_calls) == 2:
                raise sqlite3.OperationalError("synthetic write failure")
        with patch.object(cards, "settle_card", side_effect=native_record):
            self.assertEqual(expected, self.native(settle=True))
        self.assertEqual(expected_calls, native_calls)
        self.assertEqual(2, len(native_calls))

    def test_native_decisions_apply_existing_writer_and_preserve_other_rows(self):
        self.seed(["running", "completed", "cancelled"])
        expected = self.reference()
        self.assertEqual(expected, self.native(settle=True))
        with closing(sqlite3.connect(self.database)) as connection:
            states = dict(connection.execute("SELECT work_id,state FROM cards"))
        self.assertEqual({f"{1:032x}": "active", f"{2:032x}": "done", f"{3:032x}": "cancelled"}, states)


class NativeCardContextResponseTests(unittest.TestCase):
    def test_current_card_after_valid_candidate_rejects_entire_response_before_writes(self):
        current = "f"*32
        response = {"lines": [], "stale": [["b"*32, "done"], [current, "cancelled"]]}
        with patch.object(NativeProbe, "available", return_value=True), \
                patch.object(NativeProbe, "request", return_value=response), \
                patch.object(cards, "list_cards", return_value=[]), \
                patch.object(cards, "settle_card") as writer:
            actual = cards.open_card_lines(fixtures.PROJECT, current, settle_stale=True)
            writer.assert_not_called()
            self.assertEqual([], actual)

    def test_malformed_context_never_returns_partial_lines_or_write_actions(self):
        for response in (None, {"lines": [], "stale": None}, {"lines": [1], "stale": []},
                {"lines": [], "stale": [["work", "active"]]},
                {"lines": ["valid"], "stale": [[None, "done"]]},
                {"lines": ["valid"]*6, "stale": []}):
            with patch.object(NativeProbe, "available", return_value=True), \
                    patch.object(NativeProbe, "request", return_value=response) as request:
                self.assertIsNone(NativeCards.context(fixtures.PROJECT, "f"*32))
                request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
