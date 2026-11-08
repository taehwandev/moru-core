"""Real native bootstrap SQL preserves original initialization order and effects."""
from contextlib import closing, ExitStack
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import agent_work_cards as cards
from support.native_card_write import NativeCardWrite
import support.native_card_write as transport
import test_native_work_cards as fixtures
import test_native_card_write as writer_fixtures


class NativeCardBootstrapTests(unittest.TestCase):
    setUp = fixtures.NativeWorkCardTests.setUp
    store = fixtures.NativeWorkCardTests.store
    peer = writer_fixtures.NativeCardWriteTests.peer

    def activate(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,self.env,clear=True))
        self.raw_connect = sqlite3.connect
        self.parent_sql, self.connections = [], []
        self.addCleanup(lambda: [connection.close() for connection in self.connections])
        def connect(*args,**kwargs):
            connection = self.raw_connect(*args,**kwargs)
            connection.set_trace_callback(self.parent_sql.append)
            self.connections.append(connection)
            return connection
        self.stack.enter_context(patch.object(sqlite3,"connect",side_effect=connect))

    def snapshot(self):
        with closing(self.raw_connect(self.database)) as connection:
            return (connection.execute("PRAGMA user_version").fetchone()[0],
                connection.execute("PRAGMA journal_mode").fetchone()[0],
                connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
                connection.execute("PRAGMA table_info(cards)").fetchall())

    def assert_no_parent_bootstrap(self):
        forbidden = ("CREATE", "ALTER", "PRAGMAJOURNAL_MODE", "PRAGMAUSER_VERSION", "PRAGMATABLE_INFO")
        self.assertFalse([sql for sql in self.parent_sql if
            "".join(sql.upper().split()).startswith(forbidden)],self.parent_sql)

    def connect_outcome(self,backend):
        self.parent_sql.clear()
        first=len(self.connections)
        try:
            with patch.dict(os.environ,{"MORU_LAUNCHER_BACKEND":backend}), closing(cards._connect()) as connection:
                self.assertIsInstance(connection,sqlite3.Connection)
                self.assertIs(connection.row_factory,sqlite3.Row)
            return None
        except (ValueError,sqlite3.Error) as error:
            outcome=(type(error),str(error),getattr(error,"sqlite_errorcode",None),getattr(error,"sqlite_errorname",None))
            self.error_connection_closed=False
            if len(self.connections)>first:
                try: self.connections[-1].in_transaction
                except sqlite3.ProgrammingError: self.error_connection_closed=True
            # Compare durable state after releasing the original error's connection.
            for connection in self.connections[first:]: connection.close()
            return outcome

    def test_new_empty_store_uses_native_table_and_version_sql(self):
        self.activate()
        self.assertIsNone(self.connect_outcome("auto"))
        self.assert_no_parent_bootstrap()
        native = self.snapshot()
        self.assertEqual((3,"wal"),native[:2])
        self.assertEqual(["repo","work_id","summary","command","project","state","created_at",
                          "updated_at","run_id","runtime","session_id"],[row[1] for row in native[3]])
        self.database.unlink()
        self.assertIsNone(self.connect_outcome("python"))
        self.assertEqual(native,self.snapshot())
        self.assertTrue(any(sql.lstrip().startswith("CREATE") for sql in self.parent_sql))

    def test_all_legacy_column_masks_and_versions_match_original_schema_layouts(self):
        self.activate()
        for mask in range(8):
            outcomes=[]
            for backend in ("python","auto"):
                if self.database.exists(): self.database.unlink()
                self.database.parent.mkdir(parents=True,exist_ok=True)
                schema=cards._SCHEMA
                for bit,name in enumerate(("run_id","runtime","session_id")):
                    if not mask & (1<<bit): schema=schema.replace(f"    {name} TEXT NOT NULL DEFAULT '',\n","")
                with closing(self.raw_connect(self.database)) as connection:
                    connection.execute(schema)
                    connection.execute(f"PRAGMA user_version={mask%4}")
                self.assertIsNone(self.connect_outcome(backend))
                if backend=="auto": self.assert_no_parent_bootstrap()
                outcomes.append(self.snapshot())
            self.assertEqual(outcomes[0],outcomes[1],mask)

    def test_future_version_changes_wal_before_value_error_and_closes_parent(self):
        self.activate()
        outcomes=[]
        for backend in ("python","auto"):
            if self.database.exists(): self.database.unlink()
            with closing(self.store(version=1)) as connection:
                connection.execute("PRAGMA user_version=99")
            error=self.connect_outcome(backend)
            self.assertEqual((ValueError,"unsupported work-card schema version 99",None,None),error)
            self.assertTrue(self.error_connection_closed)
            if backend=="auto": self.assert_no_parent_bootstrap()
            with self.assertRaises(sqlite3.ProgrammingError): self.connections[-1].execute("SELECT 1")
            state=self.snapshot()
            self.assertEqual((99,"wal"),state[:2])
            self.assertNotIn("run_id",[row[1] for row in state[3]])
            outcomes.append(state)
        self.assertEqual(outcomes[0],outcomes[1])

    def test_partial_upgrade_is_not_wrapped_in_a_new_transaction(self):
        self.activate()
        outcomes=[]
        for backend in ("python","auto"):
            if self.database.exists(): self.database.unlink()
            self.database.parent.mkdir(parents=True,exist_ok=True)
            with closing(self.raw_connect(self.database)) as connection:
                connection.execute("CREATE TABLE cards(repo TEXT, runtime TEXT GENERATED ALWAYS AS ('fixed') VIRTUAL)")
                connection.execute("PRAGMA user_version=1")
            error=self.connect_outcome(backend)
            self.assertEqual(sqlite3.OperationalError,error[0])
            self.assertIn("duplicate column name: runtime",error[1])
            if backend=="auto": self.assert_no_parent_bootstrap()
            state=self.snapshot()
            self.assertEqual((1,"wal"),state[:2])
            self.assertIn("run_id",[row[1] for row in state[3]])
            self.assertNotIn("session_id",[row[1] for row in state[3]])
            outcomes.append((error,state))
        self.assertEqual(outcomes[0],outcomes[1])

    def test_corrupt_store_and_busy_writer_preserve_original_errors_and_data(self):
        self.activate()
        self.database.parent.mkdir(parents=True)
        self.database.write_bytes(b"not a SQLite store")
        expected=self.connect_outcome("python")
        self.assertEqual(expected,self.connect_outcome("auto"))
        self.assertEqual(b"not a SQLite store",self.database.read_bytes())
        self.database.unlink()
        with closing(self.store(wal=True)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            expected=self.connect_outcome("python")
            self.assertEqual((sqlite3.OperationalError,"database is locked"),expected[:2])
            self.assertEqual(expected,self.connect_outcome("auto"))
            connection.rollback()

    def test_path_and_test_store_refusals_precede_bootstrap_dispatch(self):
        self.activate()
        with patch.object(NativeCardWrite,"bootstrap",side_effect=AssertionError("unexpected native dispatch")):
            with patch.dict(os.environ,{"MORU_STATE_HOME":"","MORU_UNDER_UNITTEST":"1"}):
                with self.assertRaisesRegex(ValueError,"refusing to write"): cards._connect()
            target=self.base/"real-card-directory"
            target.mkdir()
            self.database.parent.parent.mkdir(parents=True,exist_ok=True)
            self.database.parent.symlink_to(target,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,"must not be a symlink"): cards._connect()
            self.database.parent.unlink()
            self.database.parent.write_bytes(b"not a directory")
            with self.assertRaises(FileExistsError): cards._connect()

    def test_existing_parent_connection_and_native_schema_are_usable_by_public_apis(self):
        self.activate()
        cards.open_card(self.project,"a"*32,summary="native bootstrap",command="test")
        self.assertTrue(cards.settle_card(self.project,"a"*32,"done"))
        self.assert_no_parent_bootstrap()
        self.assertFalse([sql for sql in self.parent_sql if sql.startswith(("INSERT","UPDATE","DELETE"))])
        with closing(self.raw_connect(self.database)) as connection:
            self.assertEqual("done",connection.execute("SELECT state FROM cards").fetchone()[0])

    def test_committed_bootstrap_with_lost_response_never_replays_python_ddl(self):
        self.activate()
        action="import sqlite3\nwith sqlite3.connect("+repr(str(self.database))+") as c:\n"
        action+=" c.execute('CREATE TABLE bootstrap_marker(value TEXT)')\nprint('lost bootstrap response')"
        self.peer(action,bootstrap=False)
        with self.assertRaisesRegex(sqlite3.OperationalError,"refusing to replay"): cards._connect()
        self.assert_no_parent_bootstrap()
        with closing(self.raw_connect(self.database)) as connection:
            names={row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
            self.assertIn("bootstrap_marker",names)
            self.assertNotIn("cards",names)

    def test_only_quiet_pre_bootstrap_refusal_runs_original_sql_once(self):
        self.activate()
        self.peer("sys.exit(125)",bootstrap=False)
        self.assertIsNone(self.connect_outcome("auto"))
        self.assertEqual(1,sum(sql.lstrip().startswith("CREATE TABLE") for sql in self.parent_sql))
        self.assertEqual((3,"wal"),self.snapshot()[:2])

    def test_malformed_version_packet_is_terminal_and_valid_future_closes_connection(self):
        self.activate()
        for version in (3,99):
            if self.database.exists(): self.database.unlink()
            self.peer("print("+repr(json.dumps({"schema_version":1,"unsupported_version":version}))+")",bootstrap=False)
            with self.assertRaises(ValueError if version==99 else sqlite3.OperationalError): cards._connect()
            self.assert_no_parent_bootstrap()
            if version==99:
                with self.assertRaises(sqlite3.ProgrammingError): self.connections[-1].execute("SELECT 1")

    def test_raw_bootstrap_never_creates_absent_paths_and_requires_closed_payload(self):
        payload={"values":[],"foreign_keys":False}
        env={**self.env,"PATH":str(self.empty)}
        def raw(value):
            return subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                "--cards-write-probe","bootstrap"],input=json.dumps(value).encode(),env=env,
                cwd=self.project,capture_output=True,timeout=3)
        done=raw(payload)
        self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        self.assertFalse(self.database.parent.exists())
        self.database.parent.mkdir(parents=True)
        sqlite3.connect(self.database).close()
        for value in ({"values":["unexpected"],"foreign_keys":False},{"values":[]},
                      {"values":[],"foreign_keys":0},{**payload,"extra":True}):
            done=raw(value)
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        self.assertEqual(b"",self.database.read_bytes())


if __name__ == "__main__":
    unittest.main()
