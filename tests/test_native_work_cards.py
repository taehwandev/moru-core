"""Real read-only work-card parity, SQLite boundaries and no-Python ingress."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_work_cards as cards
from agent_repository_key import repository_key
from native_launcher_support import copied_build_root, install
from native_pretool_support import PROJECT, environment, prepare, result
from support.native_source_inputs import pretool_contract


class NativeWorkCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-cards-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.git_only = self.base / "git-only"
        self.git_only.mkdir()
        (self.git_only / "git").symlink_to(shutil.which("git"))
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.database = Path(self.env["MORU_STATE_HOME"]) / "work-cards/cards.sqlite3"

    def call(self, args=None, backend="auto", entry=None, **overrides):
        return subprocess.run([str(entry or self.entry), "work-cards", *(args or ["--project", str(self.project), "list"])],
            cwd=self.project, capture_output=True, timeout=10,
            env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides})

    def parity(self, args=None, **env):
        expected = self.call(args, backend="python", **env)
        self.assertEqual(0, expected.returncode, expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(args, **env)))
        self.assertEqual(result(expected), result(self.call(args, PATH=str(self.git_only), **env)))
        return json.loads(expected.stdout)

    def key(self, project=None, **env):
        with patch.dict(os.environ, {**self.env, **env}, clear=True):
            return repository_key(project or self.project)

    def store(self, version=3, wal=False, extra=""):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        if wal: connection.execute("PRAGMA journal_mode=WAL")
        schema = cards._SCHEMA
        missing = ("run_id", "runtime", "session_id") if version == 1 else ("runtime", "session_id") if version == 2 else ()
        for column in missing:
            schema = schema.replace(f"    {column} TEXT NOT NULL DEFAULT '',\n", "")
        connection.execute(schema)
        if extra: connection.execute(extra)
        connection.execute(f"PRAGMA user_version={version}")
        return connection

    def insert(self, connection, index=1, state="active", repo=None, stamp=None):
        connection.execute("INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (repo if repo is not None else self.key(), f"{index:032x}", f"한글😀 card {index}\n", "implement",
             str(self.project), state, "2026-11-01T00:00:00+00:00", stamp or f"2026-11-01T00:00:{index:02}+00:00"))

    def test_absent_empty_and_missing_table_do_not_create_or_migrate(self):
        self.assertEqual([], self.parity())
        self.assertFalse(self.database.parent.exists())
        self.assertEqual((0, b"[]\n", b""), result(self.call(PATH=str(self.empty))))
        self.database.parent.mkdir(parents=True)
        sqlite3.connect(self.database).close()
        before = self.database.read_bytes()
        self.assertEqual([], self.parity())
        self.assertEqual(before, self.database.read_bytes())
        with sqlite3.connect(self.database) as connection:
            self.assertEqual([], connection.execute("SELECT name FROM sqlite_master").fetchall())
            self.assertEqual(0, connection.execute("PRAGMA user_version").fetchone()[0])

    def test_versions_fields_filtering_sort_and_equal_timestamps(self):
        for version in (0, 1, 2, 3):
            with self.subTest(version=version), closing(self.store(version)) as connection:
                for index, state in ((1, "active"), (2, "done"), (3, "cancelled"), (4, "active")):
                    self.insert(connection, index, state, stamp="same" if index in (1, 4) else None)
                self.insert(connection, 5, repo="another-repository")
                connection.commit()
                before = self.database.read_bytes()
                active = self.parity()
                self.assertEqual(2, len(active))
                all_cards = self.parity(["--project", str(self.project), "list", "--all"])
                self.assertEqual(4, len(all_cards))
                self.assertNotIn("repo", active[0])
                self.assertEqual("", active[0]["run_id"])
                self.assertEqual("", active[0]["runtime"])
                self.assertEqual("", active[0]["session_id"])
                self.assertEqual(before, self.database.read_bytes())
            self.database.unlink()

    def test_default_relative_and_linked_project_identity(self):
        with closing(self.store()) as connection:
            self.insert(connection)
            connection.commit()
            expected = self.parity(["list"])
            self.assertEqual(expected, self.parity(["--project", ".", "list"]))
            subprocess.run(["git", "-C", str(self.project), "-c", "user.email=fixture@example.invalid",
                "-c", "user.name=fixture", "commit", "--allow-empty", "-qm", "fixture"], env=self.env, check=True)
            linked = self.base / "linked 한글"
            subprocess.run(["git", "-C", str(self.project), "worktree", "add", "-q", "-b", "cards-linked", str(linked)],
                env=self.env, check=True)
            self.assertEqual(expected, self.parity(["--project", str(linked), "list"]))

    def test_non_git_and_missing_git_use_python_repository_fallback(self):
        plain = self.base / "plain"
        plain.mkdir()
        with closing(self.store()) as connection:
            self.insert(connection, repo=self.key(plain))
            self.insert(connection, 2, repo=self.key(PATH=str(self.empty)))
            connection.commit()
            self.assertEqual(1, len(self.parity(["--project", str(plain), "list"])))
            args = ["--project", str(self.project), "list"]
            baseline = subprocess.run([sys.executable, str(PROJECT / "scripts/agent_work_cards.py"), *args],
                cwd=self.project, capture_output=True, env={**self.env, "PATH": str(self.empty)}, timeout=10)
            self.assertEqual(0, baseline.returncode, baseline.stderr)
            self.assertEqual(result(baseline), result(self.call(args, PATH=str(self.empty))))
            self.assertEqual(1, len(json.loads(baseline.stdout)))

    def test_live_wal_commits_are_visible_without_changing_database_or_wal(self):
        with closing(self.store(wal=True)) as connection:
            self.insert(connection)
            connection.commit()
            wal = self.database.with_name(self.database.name + "-wal")
            before = (self.database.read_bytes(), wal.read_bytes())
            self.assertEqual(1, len(self.parity()))
            self.assertEqual(before, (self.database.read_bytes(), wal.read_bytes()))
            self.insert(connection, 2)
            connection.commit()
            self.assertEqual(2, len(self.parity()))

    def test_checkpointed_wal_and_readonly_parent_keep_compatibility(self):
        with closing(self.store(wal=True)) as connection:
            self.insert(connection)
            connection.commit()
        self.assertEqual(1, len(self.parity()))
        before = self.database.read_bytes()
        self.database.parent.chmod(0o555)
        self.addCleanup(self.database.parent.chmod, 0o755)
        expected = self.call(backend="python")
        self.assertEqual(result(expected), result(self.call()))
        self.assertEqual(0, expected.returncode, expected.stderr)
        self.assertEqual(before, self.database.read_bytes())

    def test_symlink_store_is_empty_and_file_symlinks_and_special_names_work(self):
        with closing(self.store()) as connection:
            self.insert(connection)
            connection.commit()
        target = self.base / "cards ?#%한글.sqlite3"
        self.database.replace(target)
        self.database.symlink_to(target)
        self.assertEqual(1, len(self.parity()))
        directory = self.database.parent
        actual = directory.with_name("actual-cards")
        directory.rename(actual)
        directory.symlink_to(actual, target_is_directory=True)
        self.assertEqual([], self.parity())
        self.assertEqual((0, b"[]\n", b""), result(self.call(PATH=str(self.empty))))

    def test_future_corrupt_and_locked_stores_preserve_python_errors_and_recovery(self):
        with closing(self.store()) as connection:
            self.insert(connection)
            connection.execute("PRAGMA user_version=99")
            connection.commit()
        for state in ("future", "corrupt", "locked"):
            if state == "corrupt": self.database.write_bytes(b"not a SQLite database")
            if state == "locked":
                self.database.unlink()
                lock = self.store()
                self.insert(lock)
                lock.commit()
                lock.execute("BEGIN EXCLUSIVE")
            try:
                before = self.database.read_bytes()
                expected = self.call(backend="python")
                # The canonical owner retries a locked store with its existing
                # immutable read path; native must delegate that recovery.
                self.assertEqual(0 if state == "locked" else 2, expected.returncode, expected.stderr)
                self.assertEqual(result(expected), result(self.call()))
                self.assertEqual(127, self.call(PATH=str(self.git_only)).returncode)
                self.assertEqual(before, self.database.read_bytes())
            finally:
                if state == "locked": lock.close()

    def test_extra_scalar_columns_preserve_null_and_integer_json(self):
        with closing(self.store(extra="ALTER TABLE cards ADD COLUMN extra_integer INTEGER")) as connection:
            connection.execute("ALTER TABLE cards ADD COLUMN extra_null TEXT")
            self.insert(connection)
            connection.execute("UPDATE cards SET extra_integer=9223372036854775807")
            connection.commit()
            [row] = self.parity()
            self.assertEqual(9223372036854775807, row["extra_integer"])
            self.assertIsNone(row["extra_null"])

    def test_unusual_types_indexes_and_cli_are_left_to_python(self):
        with closing(self.store(extra="ALTER TABLE cards ADD COLUMN metric REAL")) as connection:
            self.insert(connection)
            connection.execute("UPDATE cards SET metric=1.25")
            connection.commit()
            self.assertEqual(result(self.call(backend="python")), result(self.call()))
            self.assertEqual(127, self.call(PATH=str(self.git_only)).returncode)
            connection.execute("UPDATE cards SET metric=NULL")
            connection.execute("CREATE INDEX custom_cards_index ON cards(updated_at)")
            connection.commit()
            self.assertEqual(result(self.call(backend="python")), result(self.call()))
            self.assertEqual(127, self.call(PATH=str(self.git_only)).returncode)
        for args in (["--help"], ["list", "--unknown"], ["--project", str(self.base / "missing"), "list"]):
            self.assertEqual(result(self.call(args, backend="python")), result(self.call(args)))
            self.assertEqual(127, self.call(args, PATH=str(self.git_only)).returncode)
        # Prove dispatch defers without starting an interactive resume.
        self.assertEqual(127, self.call(["resume"], PATH=str(self.git_only)).returncode)

    def test_source_drift_and_runtime_environment_keep_python(self):
        root = copied_build_root(self.base / "copy")
        for relative in pretool_contract(PROJECT)[1]: (root / relative).mkdir(parents=True, exist_ok=True)
        for name in ("AGENTS.md", "index.md"): (root / name).write_text("synthetic\n")
        home = self.base / "other-home"
        install(home, root)
        entry = home / ".moru/bin/moru-hook"
        env = {"HOME": str(home), "MORU_HOME": str(root)}
        self.assertEqual(0, self.call(entry=entry, PATH=str(self.empty), **env).returncode)
        changed = root / "scripts/agent_work_cards.py"
        changed.write_text(changed.read_text() + "\n# synthetic stale input\n")
        self.assertEqual(result(self.call(entry=entry, backend="python", **env)), result(self.call(entry=entry, **env)))
        self.assertEqual(127, self.call(entry=entry, PATH=str(self.empty), **env).returncode)
        self.assertEqual(127, self.call(PYTHONVERBOSE="1", PATH=str(self.git_only)).returncode)
