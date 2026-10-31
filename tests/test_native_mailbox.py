"""Quiet-path proof and effectful mailbox differential checks on real entrypoints."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_mailbox_support import invoke, prepare, reference, restore, snapshot, stable, warm
from native_pretool_support import environment, result


class NativeMailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-mailbox-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare(self.base)
        scoped = patch.dict(os.environ, environment(self.base), clear=True)
        scoped.start()
        self.addCleanup(scoped.stop)
        self.bin = self.base / "git-only"
        self.bin.mkdir()
        (self.bin / "git").symlink_to(shutil.which("git"))
        for runtime in ("claude", "codex"):
            warm(self.launcher, self.base, self.project, runtime)
        self.store = reference(self.base, self.project)

    def run_hook(self, **kwargs):
        return invoke(self.launcher, self.base, self.project, **kwargs)

    def parity(self, **kwargs):
        before = snapshot(self.base, self.project)
        expected = self.run_hook(backend="python", **kwargs)
        expected_state = stable(snapshot(self.base, self.project))
        restore(self.base, self.project, before)
        actual = self.run_hook(**kwargs)
        self.assertEqual(result(expected), result(actual))
        self.assertEqual(expected_state, stable(snapshot(self.base, self.project)))
        return actual

    def fallback(self, **kwargs):
        before = snapshot(self.base, self.project)
        self.assertEqual(127, self.run_hook(PATH=str(self.bin), **kwargs).returncode)
        self.assertEqual(before, snapshot(self.base, self.project))
        return self.parity(**kwargs)

    def test_repeated_deliver_and_ack_are_native_without_state_changes(self):
        child = self.project / "child"
        child.mkdir()
        before = snapshot(self.base, self.project)
        for runtime in ("claude", "codex"):
            for action in ("deliver", "ack"):
                payload = {"cwd": str(child), "session_id": "synthetic-mailbox"}
                self.assertEqual((0, b"", b""), result(self.run_hook(
                    runtime=runtime, action=action, payload=payload, PATH=str(self.bin))))
                self.parity(runtime=runtime, action=action, payload=payload)
        self.assertEqual(before, snapshot(self.base, self.project))

    def test_missing_changed_and_malformed_guidance_use_python(self):
        for runtime in ("claude", "codex"):
            identity = hashlib.sha256((runtime + ":synthetic-mailbox").encode()).hexdigest()
            path = self.store.root / "guidance" / (identity + ".json")
            original = path.read_bytes()
            for content in (None, b"{broken", b'{"sha256":"changed"}'):
                if content is None: path.unlink()
                else: path.write_bytes(content)
                done = self.fallback(runtime=runtime)
                self.assertEqual(0, done.returncode)
                path.write_bytes(original)

    def test_first_prompt_and_unusual_payload_shapes_preserve_output(self):
        done = self.fallback(payload={"cwd": str(self.project), "session_id": "new-session"})
        self.assertIn(b"Current shared continuation guidance", done.stdout)
        for payload in (b"{broken", b"[]", b"null", {}, {"cwd": str(self.project)},
                        {"cwd": str(self.project), "session_id": 17},
                        {"cwd": str(self.project), "session_id": "session-한글"}):
            with self.subTest(payload=payload): self.fallback(payload=payload)

    def test_packets_are_delivered_then_acknowledged_by_python(self):
        packet = self.store.enqueue(sender="codex", recipient="claude", kind="task",
                                    body="Synthetic reference only.", ttl_seconds=3600)
        done = self.fallback()
        self.assertIn(packet["message_id"].encode(), done.stdout)
        self.assertTrue((self.store.root / "inbox/claude" / (packet["message_id"] + ".json")).is_file())
        self.fallback(action="ack")
        self.assertFalse((self.store.root / "inbox/claude" / (packet["message_id"] + ".json")).exists())
        self.assertTrue((self.store.root / "acked/claude" / (packet["message_id"] + ".json")).is_file())

    def test_malformed_local_packets_and_orphan_leases_keep_cleanup(self):
        local = self.project / ".moru/agent-mailbox"
        inbox = local / "inbox/claude"
        inbox.mkdir(parents=True)
        (inbox / "invalid.json").write_text("{broken")
        self.fallback()
        leases = self.store.root / "leases/claude"
        leases.mkdir(parents=True, exist_ok=True)
        (leases / "orphan.json").write_text("{}")
        self.fallback(action="ack")
        self.assertFalse((leases / "orphan.json").exists())

    def test_task_pause_and_turn_budget_reset_remain_effectful(self):
        tasks = self.project / ".moru/agent-mailbox/task-continuation"
        tasks.mkdir(parents=True)
        record = tasks / ("a" * 32 + ".json")
        identity = {"runtime": "claude", "session_id": "synthetic-mailbox"}
        budget = tasks / (hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() + ".budget")
        record.write_text(json.dumps({"identity": identity, "status": "armed"}))
        budget.write_text("used")
        self.fallback()
        self.assertEqual("paused", json.loads(record.read_text())["status"])
        self.assertFalse(budget.exists())

    def test_missing_lock_symlinks_and_busy_lock_do_not_bypass_python(self):
        lock = self.store.root / ".mailbox.lock"
        lock.unlink()
        self.fallback()
        outside = self.base / "outside-lock"
        lock.replace(outside)
        lock.symlink_to(outside)
        self.fallback()
        lock.unlink()
        outside.replace(lock)
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.assertEqual(127, self.run_hook(PATH=str(self.bin)).returncode)

    def test_empty_task_root_is_native_but_any_record_requires_python(self):
        tasks = self.project / ".moru/agent-mailbox/task-continuation"
        tasks.mkdir(parents=True)
        self.parity()  # Python creates the task lock once.
        self.assertEqual((0, b"", b""), result(self.run_hook(PATH=str(self.bin))))
        (tasks / "unknown").write_text("unknown state")
        self.fallback()

    def test_reordered_arguments_and_python_environment_use_compatibility(self):
        self.fallback(args=["mailbox-hook", "--runtime", "claude", "deliver"])
        self.fallback(PYTHONPATH="synthetic")

    def test_linked_worktree_uses_the_same_reference_mailbox(self):
        env = environment(self.base)
        for args in (["-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                      "commit", "--allow-empty", "-qm", "fixture"],
                     ["worktree", "add", "-qb", "fixture-linked", str(self.base / "linked")]):
            subprocess.run(["git", "-C", str(self.project), *args], check=True,
                           capture_output=True, env=env, timeout=8)
        linked = self.base / "linked"
        self.assertEqual(self.store.repository_id, reference(self.base, linked).repository_id)
        done = invoke(self.launcher, self.base, linked, PATH=str(self.bin))
        self.assertEqual((0, b"", b""), result(done))
        packet = self.store.enqueue(sender="codex", recipient="claude", kind="task",
                                    body="Linked reference.", ttl_seconds=3600)
        done = invoke(self.launcher, self.base, linked)
        self.assertIn(packet["message_id"].encode(), done.stdout)
