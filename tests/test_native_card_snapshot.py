"""Internal card reads use real native SQLite snapshots without Python replay."""
from contextlib import closing
import json
import math
import os
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import agent_work_cards as cards
from support.native_cards import NativeCards
from support.native_probe_transport import NativeProbe
from support.git_read_scope import git_read_scope
import test_native_work_cards as fixtures


class NativeCardSnapshotTests(unittest.TestCase):
    setUp = fixtures.NativeWorkCardTests.setUp
    key = fixtures.NativeWorkCardTests.key
    store = fixtures.NativeWorkCardTests.store
    insert = fixtures.NativeWorkCardTests.insert

    def read(self, all=False, *, native=True, **overrides):
        env = {**self.env, "MORU_LAUNCHER_BACKEND": "auto" if native else "python", **overrides}
        with patch.dict(os.environ, env, clear=True):
            if native:
                with patch.object(cards, "_connect_readonly", side_effect=AssertionError("Python SQLite replay")):
                    return cards.list_cards(self.project, include_settled=all)
            return cards.list_cards(self.project, include_settled=all)

    def same(self, expected, actual):
        self.assertIs(type(expected), type(actual))
        if type(expected) is dict:
            self.assertEqual(list(expected), list(actual))
            for key in expected:
                self.same(expected[key], actual[key])
        elif type(expected) is list:
            self.assertEqual(len(expected), len(actual))
            for left, right in zip(expected, actual):
                self.same(left, right)
        else:
            self.assertEqual(expected, actual)
            if type(expected) is float and expected == 0:
                self.assertEqual(math.copysign(1, expected), math.copysign(1, actual))

    def raw(self, payload):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--cards-probe", "list"], input=json.dumps(payload).encode(),
            env={**self.env, "PATH": str(self.git_only)}, cwd=self.project, capture_output=True, timeout=8)

    def test_missing_store_and_table_do_not_create_state_or_use_python(self):
        self.assertEqual([], self.read(PATH=str(self.empty)))
        self.assertFalse(self.database.parent.exists())
        self.database.parent.mkdir(parents=True)
        sqlite3.connect(self.database).close()
        before = self.database.read_bytes()
        self.assertEqual([], self.read(PATH=str(self.empty)))
        self.assertEqual(before, self.database.read_bytes())

    def test_all_sqlite_types_column_order_filtering_and_no_input_writes(self):
        with closing(self.store(extra="ALTER TABLE cards ADD COLUMN metric REAL")) as connection:
            for name, kind in (("payload", "BLOB"), ("extra_null", "TEXT"), ("huge", "INTEGER")):
                connection.execute(f"ALTER TABLE cards ADD COLUMN {name} {kind}")
            self.insert(connection)
            self.insert(connection, 2, state="done")
            self.insert(connection, 3, repo="another-repository")
            connection.execute("UPDATE cards SET metric=?, payload=?, huge=?",
                               (1.2345678901234567, bytes(range(256)), 2**63-1))
            connection.commit()
        before = self.database.read_bytes()
        for all in (False, True):
            expected = self.read(all, native=False)
            actual = self.read(all, PATH=str(self.git_only))
            self.same(expected, actual)
            self.assertEqual(bytes(range(256)), actual[0]["payload"])
        self.assertEqual(before, self.database.read_bytes())

    def test_legacy_defaults_generated_columns_and_infinite_reals(self):
        for version in (1, 2, 3):
            with closing(self.store(version, extra="ALTER TABLE cards ADD COLUMN metric REAL")) as connection:
                connection.execute("ALTER TABLE cards ADD COLUMN computed TEXT GENERATED ALWAYS AS (summary || '-computed') VIRTUAL")
                self.insert(connection)
                connection.execute("UPDATE cards SET metric=?", (math.inf,))
                connection.commit()
            expected = self.read(native=False)
            actual = self.read(PATH=str(self.git_only))
            self.same(expected, actual)
            self.assertEqual(math.inf, actual[0]["metric"])
            self.database.unlink()

    def test_live_wal_reads_committed_snapshot_only(self):
        with closing(self.store(wal=True)) as connection:
            self.insert(connection)
            connection.commit()
            expected = self.read(native=False)
            connection.execute("UPDATE cards SET summary='uncommitted'")
            self.same(expected, self.read(PATH=str(self.git_only)))
            connection.rollback()

    def test_internal_reads_retain_the_callers_repository_identity_memo(self):
        repo = self.key()
        with closing(self.store()) as connection:
            self.insert(connection)
            connection.commit()
        with git_read_scope(), patch("agent_repository_key._repository_key", side_effect=[repo, "f"*24]) as lookup:
            first = self.read(PATH=str(self.empty))
            self.same(first, self.read(PATH=str(self.empty)))
            self.assertEqual(1, len(first))
            self.assertEqual(1, lookup.call_count)

    def test_unknown_schema_and_invalid_text_decline_to_original_errors(self):
        with closing(self.store()) as connection:
            self.insert(connection)
            connection.execute("PRAGMA user_version=99")
            connection.commit()
        before = self.database.read_bytes()
        with patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(NativeCards.list(self.project, False))
            with self.assertRaisesRegex(ValueError, "unsupported work-card schema version 99"):
                cards.list_cards(self.project)
        self.assertEqual(before, self.database.read_bytes())
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version=3")
            connection.execute("UPDATE cards SET summary=CAST(X'FF' AS TEXT)")
            connection.commit()
        with patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(NativeCards.list(self.project, False))
            with self.assertRaises(sqlite3.OperationalError):
                cards.list_cards(self.project)

    def test_early_optional_failures_preserve_missing_store_and_schema_error_priority(self):
        with patch.dict(os.environ, self.env, clear=True), \
                patch("support.native_cards.repository_key", side_effect=RuntimeError("symlink loop")), \
                patch.object(NativeProbe, "available", return_value=True):
            self.assertEqual([], cards.list_cards(self.project))
            self.assertFalse(self.database.parent.exists())
            with closing(self.store(version=99)) as connection:
                connection.commit()
            with self.assertRaisesRegex(ValueError, "unsupported work-card schema version 99"):
                cards.list_cards(self.project)

    def test_custom_index_and_invalid_protocol_decline_without_effects(self):
        with closing(self.store(extra="CREATE INDEX custom_cards_index ON cards(updated_at)")) as connection:
            self.insert(connection)
            connection.commit()
        before = self.database.read_bytes()
        for payload in ({"repo": self.key(), "include_settled": False},
                        {"repo": self.key(), "include_settled": 1},
                        {"repo": None, "include_settled": False}):
            done = self.raw(payload)
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        self.assertEqual(before, self.database.read_bytes())


class NativeCardSnapshotResponseTests(unittest.TestCase):
    def test_tagged_response_keeps_all_python_cell_types(self):
        row = [[name, ["text", ""]] for name in ("run_id", "runtime", "session_id")]
        row += [["float", ["real", "-0.0"]], ["blob", ["blob", "00ff"]], ["null", ["null"]],
                ["integer", ["integer", -(2**63)]]]
        with patch.object(NativeProbe, "available", return_value=True), \
                patch.object(NativeProbe, "request", return_value={"rows": [row]}):
            [card] = NativeCards.list(fixtures.PROJECT, False)
        self.assertEqual([name for name, _ in row], list(card))
        self.assertEqual(-1, math.copysign(1, card["float"]))
        self.assertEqual(b"\0\xff", card["blob"])
        self.assertIsNone(card["null"])
        self.assertEqual(-(2**63), card["integer"])

    def test_malformed_typed_results_decline_atomically(self):
        base = [[name, ["text", ""]] for name in ("run_id", "runtime", "session_id")]
        bad = [None, {"rows": None}, {"rows": [1]}, {"rows": [[]]}]
        bad += [{"rows": [base + row]} for row in (
            [["repo", ["text", "private"]]], [["x", ["integer", True]]],
            [["x", ["integer", 2**63]]], [["x", ["blob", "0g"]]],
            [["x", ["real", "nan"]]], [["x", ["unknown", "text"]]],
            [["x", ["text", "first"]], ["x", ["text", "duplicate"]]])]
        for response in bad:
            with patch.object(NativeProbe, "available", return_value=True), \
                    patch.object(NativeProbe, "request", return_value=response) as request:
                self.assertIsNone(NativeCards.list(fixtures.PROJECT, False))
                request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
