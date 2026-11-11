"""Observe real native card writes, isolation, timestamps and pre-DML decline."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unittest

from native_pretool_support import result
import test_native_work_cards as fixtures


class NativeCardSettlementTests(unittest.TestCase):
    setUp = fixtures.NativeWorkCardTests.setUp
    call = fixtures.NativeWorkCardTests.call
    key = fixtures.NativeWorkCardTests.key
    store = fixtures.NativeWorkCardTests.store
    insert = fixtures.NativeWorkCardTests.insert

    def seed(self, *, version=3, wal=True, extra=""):
        with closing(self.store(version, wal, extra)) as connection:
            self.insert(connection)
            self.insert(connection, 2, state="done")
            self.insert(connection, 1, repo="other-repository")
            connection.commit()

    def rows(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM cards ORDER BY repo,work_id")]

    def reset_active(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE cards SET state='active', updated_at='old' WHERE work_id=?", (f"{1:032x}",))

    def close_args(self, state=None, work=None):
        return ["--project", str(self.project), "close", work or f"{1:032x}", *(["--state", state] if state else [])]

    def test_default_done_and_cancelled_match_reference_and_run_without_python(self):
        self.seed()
        for state in (None, "done", "cancelled"):
            for backend, env in (("python", {}), ("auto", {}), ("auto", {"PATH": str(self.git_only)})):
                with self.subTest(state=state, backend=backend, env=env):
                    self.reset_active()
                    before = self.rows()
                    start = datetime.now(timezone.utc)
                    done = self.call(self.close_args(state), backend=backend, **env)
                    end = datetime.now(timezone.utc)
                    expected = {"state": state or "done", "work_id": f"{1:032x}"}
                    self.assertEqual((0, (json.dumps(expected, sort_keys=True) + "\n").encode(), b""), result(done))
                    after = self.rows()
                    for old, new in zip(before, after):
                        if old["repo"] == self.key() and old["work_id"] == f"{1:032x}":
                            self.assertEqual(state or "done", new["state"])
                            stamp = new.pop("updated_at")
                            self.assertRegex(stamp, r"T\d\d:\d\d:\d\d(?:\.\d{6})?\+00:00$")
                            self.assertLessEqual(start, datetime.fromisoformat(stamp))
                            self.assertLessEqual(datetime.fromisoformat(stamp), end)
                            old.pop("updated_at")
                            old["state"] = state or "done"
                        self.assertEqual(old, new)

    def test_settled_unknown_and_other_repository_cards_remain_unchanged(self):
        self.seed()
        for work in (f"{2:032x}", f"{99:032x}"):
            before = self.rows()
            expected = self.call(self.close_args(work=work), backend="python")
            self.assertEqual(2, expected.returncode)
            self.assertEqual(result(expected), result(self.call(self.close_args(work=work))))
            self.assertEqual(result(expected), result(self.call(self.close_args(work=work), PATH=str(self.git_only))))
            self.assertEqual(before, self.rows())
        plain = self.base / "unrelated-project"
        plain.mkdir()
        expected = self.call(["--project", str(plain), "close", f"{1:032x}"], backend="python")
        before = self.rows()
        self.assertEqual(result(expected), result(self.call(["--project", str(plain), "close", f"{1:032x}"], PATH=str(self.git_only))))
        self.assertEqual(before, self.rows())

    def test_default_relative_project_and_file_symlink_use_the_same_repository(self):
        self.seed()
        for args in (["close", f"{1:032x}"], ["--project", ".", "close", f"{1:032x}"]):
            self.reset_active()
            self.assertEqual(0, self.call(args, PATH=str(self.git_only)).returncode)
        self.reset_active()
        target = self.base / "cards ?#%한글.sqlite3"
        self.database.rename(target)
        self.database.symlink_to(target)
        self.assertEqual(0, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
        self.assertEqual("done", next(row["state"] for row in self.rows() if row["repo"] == self.key() and row["work_id"] == f"{1:032x}"))

    def test_live_wal_writer_observes_only_committed_settlement(self):
        self.seed()
        with closing(sqlite3.connect(self.database)) as observer:
            observer.execute("BEGIN")
            self.assertEqual("active", observer.execute("SELECT state FROM cards WHERE repo=? AND work_id=?", (self.key(), f"{1:032x}")).fetchone()[0])
            self.assertEqual(0, self.call(self.close_args("cancelled"), PATH=str(self.git_only)).returncode)
            self.assertEqual("active", observer.execute("SELECT state FROM cards WHERE repo=? AND work_id=?", (self.key(), f"{1:032x}")).fetchone()[0])
            observer.commit()
            self.assertEqual("cancelled", observer.execute("SELECT state FROM cards WHERE repo=? AND work_id=?", (self.key(), f"{1:032x}")).fetchone()[0])

    def test_absent_stores_and_legacy_or_non_wal_stores_decline_without_creating_or_upgrading(self):
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
        self.assertFalse(self.database.parent.exists())
        for version, wal in ((0, True), (1, True), (2, True), (99, True), (3, False)):
            with self.subTest(version=version, wal=wal):
                self.seed(version=version, wal=wal)
                before = self.rows()
                self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
                self.assertEqual(before, self.rows())
                with closing(sqlite3.connect(self.database)) as connection:
                    self.assertEqual(version, connection.execute("PRAGMA user_version").fetchone()[0])
                    self.assertEqual("wal" if wal else "delete", connection.execute("PRAGMA journal_mode").fetchone()[0])
                self.database.unlink()

    def test_unknown_schema_indexes_and_triggers_decline_before_update(self):
        for extra in ("ALTER TABLE cards ADD COLUMN extra TEXT", "CREATE INDEX custom ON cards(updated_at)",
                      "CREATE TRIGGER custom AFTER UPDATE ON cards BEGIN UPDATE cards SET summary='unexpected'; END"):
            with self.subTest(extra=extra):
                self.seed(extra=extra)
                before = self.rows()
                self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
                self.assertEqual(before, self.rows())
                # Compatibility still belongs to the existing Python owner.
                self.assertEqual(0, self.call(self.close_args()).returncode)
                self.database.unlink()

    def test_competing_writer_declines_without_changing_rows_and_preserves_python_error(self):
        self.seed()
        before = self.rows()
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
            expected = self.call(self.close_args(), backend="python")
            self.assertEqual((2, b"", b"work cards: database is locked\n"), result(expected))
            self.assertEqual(result(expected), result(self.call(self.close_args())))
            writer.rollback()
        self.assertEqual(before, self.rows())

    def test_invalid_cli_and_test_store_guard_never_write_native_data(self):
        self.seed()
        before = self.rows()
        for args in (self.close_args(work="BAD"), self.close_args("active"),
                     self.close_args() + ["--unknown"]):
            self.assertEqual(127, self.call(args, PATH=str(self.git_only)).returncode)
        # Resume now has native recorded-session navigation. An unbound board
        # must report the original no-session error without writes or Python.
        expected = self.call(["resume"], backend="python")
        self.assertEqual((2,b"",b"work cards: no tasks with a recorded Codex session in this repository\n"),result(expected))
        self.assertEqual(result(expected),result(self.call(["resume"],PATH=str(self.git_only))))
        for env in ({"PYTHONVERBOSE": "1"}, {"MORU_STATE_HOME": "relative-store"}):
            self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only), **env).returncode)
        protected = Path(self.env["HOME"]) / ".moru/work-cards"
        original = self.database
        self.database = protected / "cards.sqlite3"
        self.seed()
        protected_rows = self.rows()
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only),
                                       MORU_STATE_HOME="", MORU_UNDER_UNITTEST="1").returncode)
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only),
                                       MORU_STATE_HOME="", MORU_UNDER_UNITTEST=b"\xff").returncode)
        expected = self.call(self.close_args(), backend="python", MORU_STATE_HOME="", MORU_UNDER_UNITTEST="1")
        self.assertEqual(2, expected.returncode)
        self.assertIn(b"refusing to write the user's Moru state from a test run", expected.stderr)
        self.assertEqual(result(expected), result(self.call(self.close_args(), MORU_STATE_HOME="", MORU_UNDER_UNITTEST="1")))
        self.assertEqual(protected_rows, self.rows())
        self.database = original
        self.assertEqual(before, self.rows())

    def test_symlinked_directory_or_sidecar_and_corruption_decline_before_update(self):
        self.seed()
        before = self.rows()
        target = self.base / "external-sidecar"
        target.write_bytes(b"untouched")
        sidecar = self.database.with_name(self.database.name + "-wal")
        if sidecar.exists():
            # Some SQLite builds leave an empty WAL after the last reader.
            # No connection remains and all committed frames are checkpointed.
            self.assertEqual(0, sidecar.stat().st_size)
            sidecar.unlink()
        sidecar.symlink_to(target)
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
        self.assertEqual(b"untouched", target.read_bytes())
        sidecar.unlink()
        self.assertEqual(before, self.rows())
        directory = self.database.parent
        actual = directory.with_name("real-cards")
        directory.rename(actual)
        directory.symlink_to(actual, target_is_directory=True)
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
        self.assertEqual(before, self.rows())
        directory.unlink()
        actual.rename(directory)
        self.database.write_bytes(b"not a database")
        self.assertEqual(127, self.call(self.close_args(), PATH=str(self.git_only)).returncode)
        self.assertEqual(b"not a database", self.database.read_bytes())


if __name__ == "__main__":
    unittest.main()
