"""Read-only mailbox status parity through generated native ingress."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_mailbox_reference import ReferenceMailboxStore
from native_mailbox_support import snapshot
from native_pretool_support import PROJECT, environment, prepare, result


class NativeMailboxStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-mailbox-status-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.git_only = self.base / "git-only"
        self.git_only.mkdir()
        (self.git_only / "git").symlink_to(shutil.which("git"))
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        with patch.dict(os.environ, self.env, clear=True):
            self.store = ReferenceMailboxStore(self.project)
        self.local = self.project / ".moru/agent-mailbox"

    def args(self, runtime="claude", json_output=True):
        return ["status", "--project", str(self.project), "--runtime", runtime, *(["--json"] if json_output else [])]

    def call(self, args=None, *, backend="auto", cwd=None, data=None, **overrides):
        return subprocess.run([str(self.entry), "agent-mailbox", *(args if args is not None else self.args())],
            cwd=cwd or self.project, input=data, capture_output=True, timeout=10,
            env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides})

    def parity(self, args=None, **env):
        before = snapshot(self.base, self.project)
        expected = self.call(args, backend="python", **env)
        self.assertEqual(0, expected.returncode, expected.stderr)
        self.assertFalse(expected.stderr)
        self.assertEqual(result(expected), result(self.call(args, **env)))
        self.assertEqual(result(expected), result(self.call(args, PATH=str(self.git_only), **env)))
        self.assertEqual(before, snapshot(self.base, self.project))
        return json.loads(expected.stdout) if "--json" in (args if args is not None else self.args()) else expected.stdout

    def receipts(self, root, count, runtime="claude"):
        directory = root / "acked" / runtime
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (directory / f"{index:032x}.json").write_text("not parsed by status")
        return directory

    def fallback(self, args=None, **env):
        before = snapshot(self.base, self.project)
        expected = self.call(args, backend="python", **env)
        self.assertEqual(result(expected), result(self.call(args, **env)))
        self.assertEqual(127, self.call(args, PATH=str(self.git_only), **env).returncode)
        self.assertEqual(before, snapshot(self.base, self.project))
        return expected

    def test_missing_empty_status_aliases_and_formats_create_nothing(self):
        for runtime in ("claude", "codex", "agy", "antigravity"):
            for json_output in (True, False):
                with self.subTest(runtime=runtime, json=json_output):
                    self.parity(self.args(runtime, json_output))
        self.assertFalse(self.local.exists())
        self.assertFalse(self.store.root.exists())
        done = self.call(PATH=str(self.empty))
        self.assertEqual((0, b'{"acked": 0, "expired": 0, "pending": 0, "rejected": 0, "runtime": "claude"}\n', b""), result(done))

    def test_both_stores_and_all_runs_contribute_ack_counts_with_runtime_isolation(self):
        self.receipts(self.store.root, 3)
        self.receipts(self.local / "runs" / ("a" * 32), 2)
        self.receipts(self.local / "runs" / ("b" * 32), 4)
        self.receipts(self.store.root, 7, "codex")
        self.receipts(self.store.root, 1, "antigravity")
        self.assertEqual(9, self.parity()["acked"])
        self.assertEqual(7, self.parity(self.args("codex"))["acked"])
        self.assertEqual(1, self.parity(self.args("agy"))["acked"])
        self.assertEqual(b"claude: pending=0 expired=0 acked=9 rejected=0\n", self.parity(self.args(json_output=False)))

    def test_ack_suffixes_directories_and_ignored_state_match_python(self):
        acked = self.receipts(self.store.root, 1)
        (acked / "directory.json").mkdir()
        (acked / ".json").touch()
        (acked / "ignored.JSON").touch()
        (acked / "ignored.link").symlink_to(self.base / "absent")
        for category in ("leases", "rejected", "task-continuation"):
            folder = self.local / category / "claude"
            folder.mkdir(parents=True)
            (folder / "ignored.json").write_text("ignored")
        self.assertEqual(2, self.parity()["acked"])

    def test_explicit_relative_home_and_default_nearest_repo_selection(self):
        self.receipts(self.store.root, 2)
        nested = self.project / "nested"
        nested.mkdir()
        for args, cwd in ((["status", "--runtime", "claude", "--json"], nested),
                          (["status", "--runtime", "claude", "--project", "..", "--json"], nested),
                          (["status", "--json", "--runtime", "claude", "--project", "."], self.project)):
            self.assertEqual(2, self.parity(args, cwd=cwd)["acked"])
        home_project = self.base / "home/plain"
        home_project.mkdir()
        self.assertEqual(0, self.parity(["status", "--project", "~/plain", "--runtime", "claude", "--json"])["acked"])

    def test_state_home_relative_current_home_and_default_expansion(self):
        repo = self.store.root.name
        cases = [("relative-state", self.project / "relative-state"),
                 ("~/alt-state", self.base / "home/alt-state"),
                 ("", self.base / "home/.moru"),
                 ("\x1c" + str(self.base / "whitespace-state") + "\x1f", self.base / "whitespace-state")]
        for raw, path in cases:
            with self.subTest(raw=raw):
                self.receipts(path / "agent-mailbox" / repo, 1)
                # The shared native environment guard deliberately delegates
                # relative and tilde state overrides to Python for every alias.
                if raw in ("relative-state", "~/alt-state"):
                    self.assertEqual(1, json.loads(self.fallback(MORU_STATE_HOME=raw).stdout)["acked"])
                else:
                    self.assertEqual(1, self.parity(MORU_STATE_HOME=raw)["acked"])

    def test_linked_worktrees_share_reference_but_not_legacy_ack_counts(self):
        subprocess.run(["git", "-C", str(self.project), "-c", "user.email=fixture@example.invalid",
            "-c", "user.name=fixture", "commit", "--allow-empty", "-qm", "fixture"], env=self.env, check=True)
        linked = self.base / "linked"
        subprocess.run(["git", "-C", str(self.project), "worktree", "add", "-q", "-b", "mailbox-linked", str(linked)],
            env=self.env, check=True)
        self.receipts(self.store.root, 2)
        self.receipts(self.local / "runs" / ("a" * 32), 3)
        self.assertEqual(5, self.parity()["acked"])
        self.assertEqual(2, self.parity(["status", "--project", str(linked), "--runtime", "claude", "--json"])["acked"])

    def test_missing_git_retains_python_project_identity_fallback(self):
        key = hashlib.sha256(str(self.project).encode()).hexdigest()[:24]
        self.receipts(self.base / "state/agent-mailbox" / key, 4)
        args = self.args()
        expected = subprocess.run([sys.executable, str(PROJECT / "scripts/agent-mailbox.py"), *args],
            env={**self.env, "PATH": str(self.empty)}, cwd=self.project, capture_output=True, timeout=10)
        self.assertEqual(0, expected.returncode, expected.stderr)
        self.assertEqual(4, json.loads(expected.stdout)["acked"])
        self.assertEqual(result(expected), result(self.call(PATH=str(self.empty))))

    def test_reference_packets_pending_expired_and_malformed_replay_without_changes(self):
        from datetime import datetime, timezone
        for mode in ("pending", "expired", "malformed"):
            if mode == "expired": self.store._clock = lambda: datetime(2000, 1, 1, tzinfo=timezone.utc)
            with patch.dict(os.environ, self.env, clear=True):
                packet = self.store.enqueue(sender="codex", recipient="claude", kind="review", body="Synthetic fixture.", ttl_seconds=60)
            path = self.store.root / "inbox/claude" / (packet["message_id"] + ".json")
            if mode == "malformed": path.write_text("{broken")
            value = json.loads(self.fallback().stdout)
            self.assertEqual(1, value[mode if mode != "malformed" else "rejected"])
            path.unlink()

    def test_legacy_inbox_any_json_replays_canonical_rejection(self):
        inbox = self.local / "runs" / ("a" * 32) / "inbox/claude"
        inbox.mkdir(parents=True)
        (inbox / "invalid.json").write_text("{}")
        self.assertEqual(1, json.loads(self.fallback().stdout)["rejected"])

    def test_exact_file_and_run_limits_and_error_fallback(self):
        directory = self.receipts(self.store.root, 128)
        self.receipts(self.local / "runs" / ("a" * 32), 64)
        self.receipts(self.local / "runs" / ("b" * 32), 64)
        self.assertEqual(256, self.parity()["acked"])
        (directory / "extra.json").touch()
        self.assertEqual(1, self.fallback().returncode)
        (directory / "extra.json").unlink()
        bad = self.local / "runs/invalid"
        bad.mkdir()
        self.assertEqual(1, self.fallback().returncode)
        bad.rmdir()
        for index in range(2, 65): (self.local / "runs" / f"{index:032x}").mkdir()
        self.assertEqual(1, self.fallback().returncode)

    def test_symlinked_store_or_receipt_keeps_python_errors_and_no_external_writes(self):
        directory = self.receipts(self.store.root, 1)
        target = self.base / "external.json"
        target.write_text("untouched")
        link = directory / "linked.json"
        link.symlink_to(target)
        self.assertEqual(1, self.fallback().returncode)
        self.assertEqual("untouched", target.read_text())
        link.unlink()
        original = self.store.root
        moved = original.with_name("moved")
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        self.assertEqual(1, self.fallback().returncode)

    def test_unsupported_commands_flags_and_session_inference_remain_python(self):
        cases = [["--help"], ["status"], ["status", "--runtime", "CLAUDE"],
                 [*self.args(), "--json"], [*self.args(), "--unknown"],
                 ["receive", "--project", str(self.project), "--runtime", "claude", "--json"],
                 ["status", "--project", str(self.base / "absent"), "--runtime", "claude"]]
        for args in cases:
            with self.subTest(args=args): self.fallback(args)
        self.fallback(["status", "--project", str(self.project), "--json"], CODEX_THREAD_ID="synthetic-status")
        self.assertEqual(127, self.call(PATH=str(self.git_only), PYTHONVERBOSE="1").returncode)


if __name__ == "__main__":
    unittest.main()
