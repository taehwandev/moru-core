"""Native prepared status parity, initialization, source and concurrency bounds."""
import fcntl
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

from agent_os_api import validate_status_snapshot
from benchmark_native_sha import capture
from native_launcher_support import install
from native_pretool_support import PROJECT, environment
from native_runtime_status_support import comparable, install_snapshot, invoke, prepared, state_hashes
from runtime_snapshot_normalize import normalize_output


class NativeRuntimeStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-runtime-status-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.entry, self.project = prepared(self.base)
        self.empty = self.base / "empty-path"
        self.empty.mkdir()
        self.local = self.project / ".moru"

    def parity(self, args=None, *, validated=False, native_only=False, **overrides):
        reference = invoke(self.entry, self.base, self.project, args, backend="python", **overrides)
        actual = invoke(self.entry, self.base, self.project, args,
                        **({"PATH": str(self.empty)} if native_only else {}), **overrides)
        self.assertEqual(comparable(reference, validated), comparable(actual, validated))
        return actual

    def test_basic_validated_and_default_cli_match_python_without_it(self):
        before = state_hashes(self.project)
        ids = []
        for args, validated in (([], False), (["--validate"], True),
                (["--project", str(self.project)], False),
                (["--project", str(self.project), "--validate"], True),
                (["--validate", "--project", str(self.project)], True)):
            done = self.parity(args, validated=validated, native_only=True)
            self.assertEqual(0, done.returncode)
            value = json.loads(done.stdout)
            snapshot = value["snapshot"] if validated else value
            self.assertEqual([], validate_status_snapshot(snapshot))
            self.assertEqual(4, uuid.UUID(hex=snapshot["snapshot_id"]).version)
            ids.append(snapshot["snapshot_id"])
            self.assertEqual(2, snapshot["active_runs"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(before, state_hashes(self.project))

    def test_unicode_controls_unknown_counts_and_nonlist_collections(self):
        (self.local / "scheduler.json").write_text(json.dumps({"tasks": [
            {"state": "한글"}, {"state": 'quote"\n'}, {"state": ""}, {}, {"state": None}]}))
        (self.local / "events.json").write_text(json.dumps({"events": [None, 3, {}, {"event_type": "🛠"}]}))
        self.assertEqual(0, self.parity(native_only=True).returncode)
        for name, key in (("run-registry.json", "runs"), ("scheduler.json", "tasks"), ("events.json", "events")):
            (self.local / name).write_text(json.dumps({key: "not a list"}))
        self.assertEqual(0, self.parity(native_only=True).returncode)

    def test_missing_state_initializes_in_python_then_uses_native(self):
        other = self.base / "unprepared"
        other.mkdir()
        done = invoke(self.entry, self.base, other, PATH=str(self.empty))
        self.assertEqual(127, done.returncode)
        self.assertFalse((other / ".moru").exists())
        reference = invoke(self.entry, self.base, other, backend="python")
        actual = invoke(self.entry, self.base, other, PATH=str(self.empty))
        self.assertEqual(comparable(reference), comparable(actual))
        self.assertFalse(json.loads(actual.stdout)["registry_present"])

    def test_each_missing_lock_is_left_for_python_creation(self):
        for name in (".state.lock.lock", ".run-registry.json.lock", ".scheduler.json.lock", ".events.json.lock"):
            with self.subTest(name=name):
                lock = self.local / name
                lock.unlink()
                self.assertEqual(127, invoke(self.entry, self.base, self.project, PATH=str(self.empty)).returncode)
                self.assertFalse(lock.exists())
                self.assertEqual(0, self.parity().returncode)
                self.assertTrue(lock.is_file())

    def test_unusual_malformed_and_oversized_inputs_retain_python(self):
        cases = [("scheduler.json", json.dumps({"tasks": [None]})),
                 ("scheduler.json", json.dumps({"tasks": [{"state": 5}]})),
                 ("scheduler.json", json.dumps({"tasks": [{"state": []}]})),
                 ("scheduler.json", "{malformed"),
                 ("scheduler.json", json.dumps({"ignored": "x" * 1_048_577})),
                 ("run-registry.json", json.dumps({"runs": [{"state": []}]})),
                 ("events.json", json.dumps({"events": [{"event_type": 1.5}]}))]
        for name, content in cases:
            path = self.local / name
            original = path.read_bytes()
            with self.subTest(name=name, size=len(content)):
                path.write_text(content)
                self.assertEqual(127, invoke(self.entry, self.base, self.project, PATH=str(self.empty)).returncode)
                self.parity()
                path.write_bytes(original)

    def test_symlinked_data_lock_and_project_lock_marker_retain_python(self):
        for name in ("events.json", ".events.json.lock", ".state.lock"):
            path = self.local / name
            original = path.read_bytes() if path.exists() else None
            external = self.base / ("outside-" + name.replace(".", "_"))
            external.write_bytes(original or b"")
            if path.exists():
                path.unlink()
            path.symlink_to(external)
            with self.subTest(name=name):
                self.assertEqual(127, invoke(self.entry, self.base, self.project, PATH=str(self.empty)).returncode)
                self.parity()
            path.unlink()
            if original is not None:
                path.write_bytes(original)

    def test_unsupported_cli_environment_and_changed_source_retain_python(self):
        for args in (["--help"], ["--invalid"], ["--project", "."], ["--month", "2026-11"]):
            with self.subTest(args=args):
                if args == ["--help"]:
                    reference = invoke(self.entry, self.base, self.project, args, backend="python")
                    actual = invoke(self.entry, self.base, self.project, args)
                    self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                                     (actual.returncode, actual.stdout, actual.stderr))
                else:
                    self.parity(args)
                self.assertEqual(127, invoke(self.entry, self.base, self.project, args, PATH=str(self.empty)).returncode)
        self.parity(PYTHONNOUSERSITE="1")
        self.assertEqual(127, invoke(self.entry, self.base, self.project,
                                    PYTHONNOUSERSITE="1", PATH=str(self.empty)).returncode)
        root = self.base / "changed-source"
        capture(root)
        home = self.base / "changed-home"
        install(home, root)
        entry = home / ".moru/bin/moru-hook"
        original = invoke(entry, self.base, self.project, source=root, HOME=str(home), PATH=str(self.empty))
        self.assertEqual(0, original.returncode)
        (root / "scripts/agent_os_api.py").write_text((root / "scripts/agent_os_api.py").read_text() + "\n# changed\n")
        done = invoke(entry, self.base, self.project, source=root, HOME=str(home), PATH=str(self.empty))
        self.assertEqual(127, done.returncode)
        reference = invoke(entry, self.base, self.project, source=root, HOME=str(home), backend="python")
        actual = invoke(entry, self.base, self.project, source=root, HOME=str(home))
        self.assertEqual(comparable(reference), comparable(actual))

    def test_project_lock_contention_waits_for_fresh_python_snapshot(self):
        lock = (self.local / ".state.lock.lock").open("r+b")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        self.assertEqual(127, invoke(self.entry, self.base, self.project, PATH=str(self.empty)).returncode)
        child = subprocess.Popen([str(self.entry), "agent-os-status", "--project", str(self.project)],
            env=environment(self.base), cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            time.sleep(0.2)
            self.assertIsNone(child.poll(), "a held project lock must prevent a stale native snapshot")
            (self.local / "run-registry.json").write_text(json.dumps({"runs": [{"state": "running"}] * 3}))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
        stdout, stderr = child.communicate(timeout=8)
        self.assertEqual((0, b""), (child.returncode, stderr))
        self.assertEqual(3, json.loads(stdout)["active_runs"])

    def test_trends_keep_their_python_output_and_fallback(self):
        args = ["--project", str(self.project), "--efficiency-trends"]
        reference = invoke(self.entry, self.base, self.project, args, backend="python")
        actual = invoke(self.entry, self.base, self.project, args)
        self.assertEqual((0, b""), (reference.returncode, reference.stderr))
        self.assertEqual((0, b""), (actual.returncode, actual.stderr))
        self.assertEqual(normalize_output(reference.stdout, "trends"), normalize_output(actual.stdout, "trends"))
        self.assertEqual(127, invoke(self.entry, self.base, self.project, args, PATH=str(self.empty)).returncode)

    def test_file_lock_contention_releases_native_locks_before_fallback(self):
        with (self.local / ".events.json.lock").open("r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(127, invoke(self.entry, self.base, self.project, PATH=str(self.empty)).returncode)
            with (self.local / ".state.lock.lock").open("r+b") as outer:
                fcntl.flock(outer, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(outer, fcntl.LOCK_UN)
        self.assertEqual(0, self.parity(native_only=True).returncode)

    def test_snapshot_installer_uses_its_own_frozen_source(self):
        root = self.base / "frozen-installer"
        package = root / "scripts/support"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "stable_launcher.py").write_text(
            "from pathlib import Path\n"
            "def ensure_stable_launcher(root, dry_run=False):\n"
            "    entry = Path.home() / '.moru/bin/moru-hook'\n"
            "    entry.parent.mkdir(parents=True)\n"
            "    entry.write_text('frozen installer')\n")
        home = self.base / "frozen-home"
        entry, env = install_snapshot(self.base, home, root)
        self.assertEqual("frozen installer", entry.read_text())
        self.assertEqual(str(home), env["HOME"])
        self.assertEqual(str(root), env["MORU_HOME"])
