"""Card API DML executes natively and never replays an ambiguous child outcome."""
from contextlib import closing, ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import agent_work_cards as cards
from support.native_card_write import NativeCardWrite
import support.native_card_write as transport
import test_native_work_cards as fixtures


class NativeCardWriteTests(unittest.TestCase):
    setUp = fixtures.NativeWorkCardTests.setUp
    key = fixtures.NativeWorkCardTests.key
    store = fixtures.NativeWorkCardTests.store
    insert = fixtures.NativeWorkCardTests.insert

    def activate(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, self.env, clear=True))
        self.parent_sql = []
        original = cards._connect
        def connect():
            connection = original()
            if getattr(self,"parent_foreign_keys",None) is not None:
                connection.execute("PRAGMA foreign_keys="+str(int(self.parent_foreign_keys)))
            connection.set_trace_callback(self.parent_sql.append)
            return connection
        self.stack.enter_context(patch.object(cards, "_connect", side_effect=connect))

    def rows(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM cards ORDER BY repo,work_id")]

    def open(self, work="a"*32, **kwargs):
        cards.open_card(self.project, work, summary=kwargs.pop("summary", "한😀 새 카드"),
                        command=kwargs.pop("command", "implement"), **kwargs)

    def assert_native(self):
        self.assertFalse([sql for sql in self.parent_sql if sql.split()[0].upper() in
                         {"INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT"}], self.parent_sql)

    def test_new_store_public_open_settle_and_missing_card_do_real_native_dml(self):
        self.activate()
        now = datetime(2026, 11, 8, 1, 2, 3, 123456, timezone.utc)
        with patch.object(cards, "_now", return_value=now):
            self.open(run_id="b"*32, runtime="codex", session_id="opaque-session")
            row = self.rows()[0]
            self.assertEqual(("active", "b"*32, "codex", "opaque-session", now.isoformat()),
                tuple(row[key] for key in ("state", "run_id", "runtime", "session_id", "created_at")))
            self.assertTrue(cards.settle_card(self.project, "a"*32, "done"))
            self.assertFalse(cards.settle_card(self.project, "a"*32, "cancelled"))
            self.assertFalse(cards.settle_card(self.project, "f"*32, "done"))
        self.assertEqual("done", self.rows()[0]["state"])
        self.assert_native()

    def test_reactivation_precedes_global_retention_and_keeps_original_created_time(self):
        with closing(self.store(wal=True)) as connection:
            now = datetime(2026, 11, 8, 1, 2, 3, tzinfo=timezone.utc)
            cutoff = (now - cards.IDLE_RETENTION).isoformat()
            for i, state, repo, stamp in ((1,"done",self.key(),"0001"),
                    (2,"active","other",cutoff), (3,"cancelled","other","0001"),
                    (4,"active",self.key(),"0001"), (5,"done",self.key(),"zzzz")):
                self.insert(connection, i, state=state, repo=repo, stamp=stamp)
            connection.commit()
        self.activate()
        with patch.object(cards, "_now", return_value=now):
            self.open(f"{1:032x}", summary="  한😀\n  새   카드  ", run_id="e"*32)
        rows = self.rows()
        self.assertEqual({f"{i:032x}" for i in (1,2,5)}, {row["work_id"] for row in rows})
        row = next(row for row in rows if row["work_id"] == f"{1:032x}")
        self.assertEqual(("active","한😀 새 카드","2026-11-01T00:00:00+00:00",now.isoformat(),"e"*32),
            tuple(row[k] for k in ("state","summary","created_at","updated_at","run_id")))
        self.assert_native()

    def test_bootstrap_upgrades_legacy_versions_then_dml_is_native(self):
        self.activate()
        for version in (0,1,2,3):
            with self.subTest(version=version):
                if self.database.exists(): self.database.unlink()
                with closing(self.store(version)) as connection:
                    self.insert(connection)
                    connection.commit()
                self.parent_sql.clear()
                self.open(runtime="codex")
                self.assertTrue(cards.settle_card(self.project, "a"*32, "cancelled"))
                self.assert_native()
                with closing(sqlite3.connect(self.database)) as connection:
                    self.assertEqual(3, connection.execute("PRAGMA user_version").fetchone()[0])

    def test_settlement_is_repository_scoped_and_preserves_unrelated_fields(self):
        with closing(self.store()) as connection:
            self.insert(connection,1)
            self.insert(connection,2,repo="other-repository")
            connection.commit()
        before = self.rows()
        self.activate()
        self.assertTrue(cards.settle_card(self.project, f"{1:032x}", "cancelled"))
        after = self.rows()
        for old, new in zip(before,after):
            if old["repo"] == self.key():
                old["state"] = "cancelled"
                old.pop("updated_at"); new.pop("updated_at")
            self.assertEqual(old,new)
        self.assert_native()

    def test_naive_time_and_unicode_summary_limit_keep_exact_native_values(self):
        self.activate()
        now = datetime(2026,11,8,1,2,3,1000)
        with patch.object(cards,"_now",return_value=now):
            self.open(summary="😀"*201, command="multi\x00line\ncommand")
        row = self.rows()[0]
        self.assertEqual("😀"*200,row["summary"])
        self.assertEqual(now.isoformat(),row["updated_at"])
        self.assertEqual("multi\x00line\ncommand",row["command"])
        self.assert_native()

    def test_validation_keeps_original_bootstrap_and_error_order(self):
        self.activate()
        with self.assertRaises(ValueError): cards.settle_card(self.project,"bad","active")
        self.assertFalse(self.database.exists())
        with self.assertRaises(ValueError): self.open("bad")
        self.assertTrue(self.database.exists())
        self.assertEqual([],self.rows())
        with self.assertRaisesRegex(ValueError,"summary"): self.open(summary="\x00")
        with patch.object(cards,"_now",return_value=datetime.min.replace(tzinfo=timezone.utc)):
            with self.assertRaises(OverflowError): self.open()
        self.assertEqual([],self.rows())  # fallback INSERT then cutoff failed and rolled back
        self.assertTrue(any(sql.startswith("INSERT") for sql in self.parent_sql))

    def test_schema_trigger_adapter_and_non_string_values_decline_before_dml(self):
        self.activate()
        self.open()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TRIGGER fixture AFTER UPDATE ON cards BEGIN SELECT 1; END")
            connection.commit()
        self.parent_sql.clear()
        self.assertTrue(cards.settle_card(self.project,"a"*32,"done"))
        self.assertTrue(any(sql.startswith("UPDATE") for sql in self.parent_sql))
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("DROP TRIGGER fixture")
        self.parent_sql.clear()
        self.open(command=42)
        self.assertTrue(any(sql.startswith("INSERT") for sql in self.parent_sql))
        self.assertEqual("42",self.rows()[0]["command"])
        with patch.dict(sqlite3.adapters,{(str,sqlite3.PrepareProtocol):lambda value:value}):
            self.parent_sql.clear()
            self.open()
            self.assertTrue(any(sql.startswith("INSERT") for sql in self.parent_sql))

    def test_foreign_key_setting_matches_parent_without_unintended_cascade_or_restrict(self):
        self.activate()
        now = datetime(2026,11,8,tzinfo=timezone.utc)
        for setting in (False,True):
            self.parent_foreign_keys = setting
            for action in ("CASCADE","RESTRICT"):
                outcomes = []
                for backend in ("python","auto"):
                    if self.database.exists(): self.database.unlink()
                    with closing(self.store(wal=True)) as connection:
                        self.insert(connection,1,stamp="0001")
                        connection.execute("CREATE TABLE dependent(repo TEXT,work_id TEXT,"
                            "FOREIGN KEY(repo,work_id) REFERENCES cards(repo,work_id) ON DELETE "+action+")")
                        connection.execute("INSERT INTO dependent VALUES(?,?)",(self.key(),f"{1:032x}"))
                        connection.commit()
                    self.parent_sql.clear()
                    error = None
                    with patch.dict(os.environ,{"MORU_LAUNCHER_BACKEND":backend}), patch.object(cards,"_now",return_value=now):
                        try: self.open()
                        except sqlite3.IntegrityError as caught: error = str(caught)
                    with closing(sqlite3.connect(self.database)) as connection:
                        dependent = connection.execute("SELECT * FROM dependent").fetchall()
                    outcomes.append((error,self.rows(),dependent))
                    if backend == "auto": self.assert_native()
                self.assertEqual(outcomes[0],outcomes[1],(setting,action))
                if setting and action == "RESTRICT":
                    self.assertEqual("FOREIGN KEY constraint failed",outcomes[1][0])
                    self.assertEqual(1,len(outcomes[1][1]))
                else:
                    self.assertIsNone(outcomes[1][0])
                self.assertEqual(0 if setting and action=="CASCADE" else 1,len(outcomes[1][2]))

    def test_foreign_in_memory_or_busy_parent_connections_cannot_dispatch(self):
        self.activate()
        values = ("done","2026-11-08T00:00:00+00:00",self.key(),"a"*32)
        with patch.object(transport.subprocess,"Popen",side_effect=AssertionError("unexpected dispatch")):
            for path in (":memory:",str(self.base/"foreign.sqlite3")):
                with closing(sqlite3.connect(path)) as connection:
                    self.assertIsNone(NativeCardWrite.settle(connection,values))
            with closing(cards._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                self.assertIsNone(NativeCardWrite.settle(connection,values))

    def peer(self, action, ready=True):
        native = self.entry.with_name("moru-hook-native")
        # The installed fixture is a copy/hardlink; replace its inode first.
        native.unlink()
        marker = self.base/"peer-marker"
        native.write_text("#!"+sys.executable+"\nimport sys, pathlib, time\n"
            +"if sys.argv[-1] == 'ready':\n"
            +(" print('{\"schema_version\":1,\"ready\":true}'); sys.exit(0)\n" if ready else
              " print('unknown protocol',file=sys.stderr); sys.exit(2)\n")
            +f"pathlib.Path({str(marker)!r}).write_text('possible external effect')\n"+action+"\n")
        native.chmod(0o755)
        return marker

    def test_ambiguous_response_nonzero_stderr_and_timeout_never_replay(self):
        self.activate()
        with closing(cards._connect()): pass
        peers = ("print('broken')", "sys.exit(1)", "print('error',file=sys.stderr)",
            "print('not quiet'); sys.exit(125)",
            "print('{\"schema_version\":1,\"schema_version\":1,\"result\":{\"changed\":true}}')",
            "print('{\"schema_version\":1,\"result\":{\"changed\":false}}')", "time.sleep(10)")
        for action in peers:
            with self.subTest(action=action):
                marker = self.peer(action)
                self.parent_sql.clear()
                with patch.object(transport,"_TIMEOUT",0.5), self.assertRaisesRegex(sqlite3.OperationalError,"refusing to replay"):
                    self.open()
                self.assertTrue(marker.exists())
                self.assert_native()
                self.assertEqual([],self.rows())

    def test_committed_child_effect_survives_lost_response_without_parent_replay(self):
        self.activate()
        with closing(cards._connect()): pass
        row = (self.key(),"a"*32,"child committed","implement",str(self.project),
               "active","child-created","child-updated","a"*32,"codex","opaque")
        action = "import sqlite3\nwith sqlite3.connect("+repr(str(self.database))+") as c:\n"
        action += " c.execute('INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?)',"+repr(row)+")\nprint('lost response')"
        self.peer(action)
        with self.assertRaisesRegex(sqlite3.OperationalError,"refusing to replay"): self.open()
        self.assertEqual("child committed",self.rows()[0]["summary"])
        self.assertEqual("child-created",self.rows()[0]["created_at"])
        action = "import sqlite3\nwith sqlite3.connect("+repr(str(self.database))+") as c:\n"
        action += " c.execute(\"UPDATE cards SET state='cancelled'\")\nprint('lost response')"
        self.peer(action)
        with self.assertRaisesRegex(sqlite3.OperationalError,"refusing to replay"):
            cards.settle_card(self.project,"a"*32,"done")
        self.assertEqual("cancelled",self.rows()[0]["state"])
        self.assert_native()

    def test_only_quiet_125_is_a_safe_once_only_python_fallback(self):
        self.activate()
        self.peer("sys.exit(125)")
        self.open()
        self.assertEqual(1,len(self.rows()))
        self.assertEqual(1,sum(sql.startswith("INSERT") for sql in self.parent_sql))

    def test_old_installed_protocol_declines_before_starting_a_writer(self):
        self.activate()
        marker = self.peer("raise AssertionError('writer must never start')",ready=False)
        self.open()
        self.assertFalse(marker.exists())
        self.assertEqual(1,len(self.rows()))
        self.assertEqual(1,sum(sql.startswith("INSERT") for sql in self.parent_sql))

    def test_native_error_packet_keeps_sqlite_class_code_and_does_not_retry(self):
        self.activate()
        misuse = sqlite3.InterfaceError if sys.version_info >= (3,11) else sqlite3.ProgrammingError
        range_error = sqlite3.InterfaceError if sys.version_info >= (3,11) else sqlite3.DatabaseError
        for code, kind in ((2067,sqlite3.IntegrityError),(18,sqlite3.DataError),
                           (5,sqlite3.OperationalError),(2,sqlite3.InternalError),
                           (21,misuse),(25,range_error),(26,sqlite3.DatabaseError)):
            self.peer("print("+repr(json.dumps({"schema_version":1,
                "error":{"code":code,"message":"synthetic SQLite error"}}))+")")
            self.parent_sql.clear()
            with self.assertRaises(kind) as raised:
                self.open()
            self.assertEqual("synthetic SQLite error",str(raised.exception))
            if sys.version_info >= (3,11):
                self.assertEqual(code,raised.exception.sqlite_errorcode)
                name = "SQLITE_CONSTRAINT_UNIQUE" if code == 2067 else "SQLITE_"+transport._PRIMARY_NAMES[code]
                self.assertEqual(name,raised.exception.sqlite_errorname)
            self.assert_native()

    def test_raw_private_protocol_protects_store_and_declines_unknown_input_before_write(self):
        self.activate()
        with closing(cards._connect()): pass
        before = self.rows()
        for payload in ({"values":[]},{"values":["active","now",self.key(),"a"*32]},
                        {"values":["done","2026-11-08T00:00:00+00:00",self.key(),"a"*32],"extra":True}):
            done = subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                "--cards-write-probe","settle"],input=json.dumps({"foreign_keys":False,**payload}).encode(),
                env={**self.env,"PATH":str(self.empty)},capture_output=True,timeout=3)
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        self.assertEqual(before,self.rows())

    def test_raw_test_guard_cannot_mutate_an_existing_default_home_store(self):
        protected = Path(self.env["HOME"])/".moru/work-cards/cards.sqlite3"
        protected.parent.mkdir(parents=True)
        with closing(sqlite3.connect(protected)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(cards._SCHEMA)
            connection.execute("PRAGMA user_version=3")
            self.insert(connection,1)
            connection.commit()
        payload = {"foreign_keys":False,"values":["done","2026-11-08T00:00:00+00:00",self.key(),f"{1:032x}"]}
        for marker in ("1",b"\xff"):
            done = subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
                "--cards-write-probe","settle"],input=json.dumps(payload).encode(),capture_output=True,
                env={**self.env,"MORU_STATE_HOME":"","MORU_UNDER_UNITTEST":marker,"PATH":str(self.empty)},timeout=3)
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        with closing(sqlite3.connect(protected)) as connection:
            self.assertEqual("active",connection.execute("SELECT state FROM cards").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
