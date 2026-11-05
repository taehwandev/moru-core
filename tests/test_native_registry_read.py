"""Real native prepared snapshots, canonical fallback and import boundaries."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_registry_read as reads
import agent_run_registry as legacy
from agent_state_read import evidence_binding_key, registry_path
from native_pretool_support import PROJECT, environment, prepare


class NativeRegistryReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-registry-read-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()
        self.path = registry_path(self.project)
        self.locks = [self.path.parent / name for name in (".state.lock.lock", ".run-registry.json.lock")]
        for lock in self.locks:
            lock.touch()
        self.evidence = self.project / ".moru/runs" / ("a" * 32) / "preflight.json"
        self.key = evidence_binding_key(self.project, self.evidence)
        self.legacy_key = evidence_binding_key(self.project, self.path.parent / "preflight.json")

    def write(self, rows):
        self.path.write_text(json.dumps({"schema_version": 1, "runs": rows}, ensure_ascii=False))

    def payload(self, **fields):
        return {"state_dir": str(self.path.parent), "legacy_key": self.legacy_key,
                "states": sorted(legacy.ACTIVE_RUN_STATES), "evidence_key": self.key,
                "evidence_name": "preflight.json", "legacy_default": False, **fields}

    def raw(self, operation, payload=None, **env):
        value = self.payload() if payload is None else payload
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
                "--registry-read-probe", operation], input=value if isinstance(value, bytes) else json.dumps(value).encode(),
            env={**self.env, "PATH": str(self.empty), **env}, cwd=self.project, capture_output=True, timeout=4)

    def value(self, operation, **fields):
        done = self.raw(operation, self.payload(**fields))
        self.assertEqual((0, b""), (done.returncode, done.stderr), done)
        return json.loads(done.stdout)["result"]["value"]

    def test_all_reads_match_order_latest_state_and_legacy_semantics_without_writes(self):
        self.write([{"run_id": "old", "state": "running", "evidence_key": self.key},
                    {"run_id": "other", "state": "paused", "evidence_key": "other", "resume_generation": None},
                    {"run_id": "new", "state": "completed", "evidence_key": self.key},
                    {"run_id": "legacy", "state": "resuming", "evidence_name": "preflight.json"},
                    {"run_id": "ignored", "state": "running", "evidence_name": "other.json"}])
        before = {p.name: p.read_bytes() for p in self.path.parent.iterdir()}
        self.assertEqual(legacy.active_runs(self.project), self.value("active"))
        self.assertEqual(list(legacy.active_run_bindings(self.project).items()),
                         [tuple(row) for row in self.value("bindings")])
        self.assertEqual("new", self.value("latest"))
        self.assertEqual("legacy", self.value("latest", evidence_key=self.legacy_key, legacy_default=True))
        for state in ("claiming", "cancelled", "failed"):
            rows = json.loads(self.path.read_text())["runs"]
            rows.append({"run_id": state, "state": state, "evidence_key": "other"})
            self.write(rows)
            self.assertNotIn("other", dict(self.value("bindings")))
        self.write(json.loads(before["run-registry.json"])["runs"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.path.parent.iterdir()})

    def test_empty_null_and_large_unfinished_histories_are_successes(self):
        self.write([])
        self.assertEqual([], self.value("active"))
        self.assertEqual([], self.value("bindings"))
        self.assertIsNone(self.value("latest"))
        rows = [{"run_id": str(i), "state": "running", "evidence_key": str(i)} for i in range(257)]
        self.write(rows)
        self.assertEqual(257, len(self.value("active")))
        self.assertEqual(257, len(self.value("bindings")))
        self.assertIsNone(self.value("latest"))

    def test_adapter_uses_native_and_python_rollback_keeps_canonical_results(self):
        self.write([{"run_id": "한글", "state": "running", "evidence_key": self.key}])
        expected = [legacy.active_runs(self.project), legacy.active_run_bindings(self.project),
                    legacy.latest_run_id(self.project, self.evidence)]
        with patch.dict(os.environ, self.env, clear=True):
            with patch.multiple(legacy, active_runs=unittest.mock.DEFAULT,
                                active_run_bindings=unittest.mock.DEFAULT, latest_run_id=unittest.mock.DEFAULT) as mocks:
                for mock in mocks.values(): mock.side_effect = AssertionError("unexpected Python fallback")
                self.assertEqual(expected, [reads.active_runs(self.project), reads.active_run_bindings(self.project),
                                            reads.latest_run_id(self.project, self.evidence)])
            with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertEqual(expected, [reads.active_runs(self.project), reads.active_run_bindings(self.project),
                                            reads.latest_run_id(self.project, self.evidence)])
        self.assertIs(reads.ACTIVE_RUN_STATES, legacy.ACTIVE_RUN_STATES)
        self.assertEqual(legacy.evidence_binding_key(self.project, self.evidence), self.key)

    def test_missing_busy_symlink_and_special_locks_decline_without_initializing(self):
        self.write([])
        for lock in self.locks:
            with lock.open("a+b") as file:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(125, self.raw("active").returncode)
            lock.unlink()
            self.assertEqual(125, self.raw("active").returncode)
            self.assertFalse(lock.exists())
            target = self.base / (lock.name + "-target")
            target.touch()
            lock.symlink_to(target)
            self.assertEqual(125, self.raw("active").returncode)
            lock.unlink()
            os.mkfifo(lock)
            self.assertEqual(125, self.raw("active").returncode)
            lock.unlink()
            lock.touch()

    def test_unsafe_state_and_unsupported_rows_keep_exact_legacy_fallback(self):
        for rows in ([{"state": "running", "evidence_key": 42}],
                     [{"state": "running", "counter": 10 ** 100}],
                     [{"state": "running", "counter": 1.5}], [None]):
            self.write(rows)
            self.assertEqual(125, self.raw("active").returncode)
        self.write([{"state": "running", "counter": 10 ** 100}])
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(legacy.active_runs(self.project), reads.active_runs(self.project))
        for raw in (b"{broken", b"[]", b'{"schema_version":2,"runs":[]}', b" " * (1024 * 1024 + 1)):
            self.path.write_bytes(raw)
            self.assertEqual(125, self.raw("active").returncode)
        self.path.unlink()
        target = self.base / "registry-target"
        target.write_text('{"schema_version":1,"runs":[]}')
        self.path.symlink_to(target)
        self.assertEqual(125, self.raw("active").returncode)
        self.path.unlink()
        os.mkfifo(self.path)
        self.assertEqual(125, self.raw("active").returncode)
        self.path.unlink()
        self.assertEqual(125, self.raw("active").returncode)
        self.assertFalse(self.path.exists())
        state_link = self.base / "state-link"
        state_link.symlink_to(self.path.parent, target_is_directory=True)
        self.assertEqual(125, self.raw("active", self.payload(state_dir=str(state_link))).returncode)

    def test_protocol_and_environment_declines_are_silent_even_with_softfail(self):
        self.write([])
        for op, payload in (("unknown", self.payload()), ("active", b"{broken"),
                            ("active", b" " * (1024 * 1024 + 1)),
                            ("active", self.payload(states=[1]))):
            done = self.raw(op, payload, MORU_HOOK_SOFT_FAIL="1")
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        self.assertEqual(125, self.raw("active", PYTHONVERBOSE="1").returncode)

    def test_session_import_and_prepared_read_do_not_load_transaction_owners(self):
        self.write([])
        code = ("import sys; sys.path.insert(0,sys.argv[1]); from pathlib import Path; import agent_runtime_session; "
                "from agent_registry_read import active_runs; assert active_runs(Path(sys.argv[2])) == []; "
                "assert 'agent_run_registry' not in sys.modules; assert 'agent_ipc' not in sys.modules")
        done = subprocess.run([sys.executable, "-B", "-c", code, str(PROJECT / "scripts"), str(self.project)],
            env=self.env, capture_output=True, timeout=6)
        self.assertEqual((0, b"", b""), (done.returncode, done.stdout, done.stderr))


if __name__ == "__main__":
    unittest.main()
