"""Real retention reader parity, without granting native pruning authority."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import agent_run_evidence as source
import agent_registry_read as integration
from agent_run_states import RUN_STATES
from native_pretool_support import environment, prepare
from support.native_probe_transport import NativeProbe

BASELINE = "61b69b2db57c7cbe32af4ac7af23fc733ba007cf"


class NativeRegistryRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="native-retention-")
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name).resolve()
        cls.entry, cls.project = prepare(cls.base)
        empty = cls.base / "empty"
        empty.mkdir()
        cls.env = {**environment(cls.base), "PATH": str(empty)}
        with patch.dict(os.environ, cls.env, clear=True):
            cls.path = source.project_state_dir_target(cls.project) / "run-registry.json"
        original = subprocess.run(["git", "show", BASELINE + ":scripts/agent_run_evidence.py"],
            capture_output=True, check=True, cwd=Path(__file__).resolve().parents[1]).stdout
        cls.oracle = types.ModuleType("original_run_evidence")
        exec(compile(original, "original_run_evidence.py", "exec"), cls.oracle.__dict__)

    def setUp(self):
        self.path.unlink(missing_ok=True)

    def call(self, module=source, backend="auto"):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
            return module.read_registry_states(self.project)

    def profile(self, action):
        calls = []
        def observe(frame, event, arg):
            if event != "call":
                return
            if frame.f_code is source._read_registry_states_reference.__code__:
                calls.append("reference")
            if frame.f_code is Path.read_text.__code__ and frame.f_locals.get("self") == self.path:
                calls.append("Python registry read")
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            result = action()
        finally:
            sys.setprofile(previous)
        return result, calls

    def write(self, rows, version=1):
        self.path.write_text(json.dumps({"schema_version": version, "runs": rows}), encoding="utf-8")

    def test_real_read_has_no_python_file_or_decoder_reference_replay(self):
        self.write([{"run_id": "z", "state": "running"}, {"run_id": "한글", "state": "paused"}])
        expected = self.call(self.oracle)
        with patch.object(NativeProbe, "request", wraps=NativeProbe.request) as request:
            actual, calls = self.profile(self.call)
        self.assertEqual(expected, actual)
        self.assertEqual(list(expected), list(actual))
        self.assertEqual([], calls)
        self.assertEqual(1, request.call_count)
        self.assertEqual("retention-states", request.call_args.args[1])

    def test_negative_control_observes_python_file_and_reference(self):
        self.write([{"run_id": "a", "state": "running"}])
        actual, calls = self.profile(lambda: self.call(backend="python"))
        self.assertEqual(self.call(self.oracle), actual)
        self.assertEqual(["reference", "Python registry read"], calls)

    def test_original_source_schema_rows_order_and_extended_json_parity(self):
        rows = [{"run_id": "z", "state": "blocked"}, {"run_id": "a", "state": "running"}]
        for version in (1, True, 1.0, 2, False, "1", None):
            self.write(rows, version)
            self.assertEqual(self.call(self.oracle), self.call())
        for bad in ([], [{}], [{"run_id": "", "state": "running"}],
                    [{"run_id": "a", "state": "other"}], [{"run_id": 7, "state": "running"}],
                    [{"run_id": "a", "state": "running"}] * 2):
            self.write(bad)
            self.assertEqual(self.call(self.oracle), self.call())
        for extra in ("NaN", "Infinity", "-Infinity", "9" * 1000, '"\\ud800"'):
            self.path.write_text('{"schema_version":1,"runs":[],"unused":' + extra + '}')
            self.assertEqual(self.call(self.oracle), self.call())

    def test_missing_corrupt_encoding_and_large_digit_errors_preserve_behavior(self):
        self.assertIsNone(self.call())
        for raw in (b'{', b'[]', b'\xef\xbb\xbf{}', b'\xff'):
            self.path.write_bytes(raw)
            self.assertEqual(self.call(self.oracle), self.call())
        if hasattr(sys, "get_int_max_str_digits") and sys.get_int_max_str_digits():
            self.path.write_text('{"schema_version":1,"runs":[],"extra":' + '9' * (sys.get_int_max_str_digits()+1) + '}')
            for module in (self.oracle, source):
                with self.assertRaises(ValueError):
                    self.call(module)

    def test_report_reads_create_no_locks_and_do_not_block_on_existing_locks(self):
        self.write([{"run_id": "a", "state": "running"}])
        before = {p.name: p.read_bytes() for p in self.path.parent.iterdir() if p.is_file()}
        self.assertEqual({"a": "running"}, self.call())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.path.parent.iterdir() if p.is_file()})
        lock = self.path.with_name(".run-registry.json.lock")
        with lock.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual({"a": "running"}, self.call())
        lock.unlink()

    def test_custom_decoder_file_reader_schema_and_state_vocabulary_are_preserved(self):
        self.write([{"run_id": "a", "state": "running"}])
        with patch.object(source.json, "loads", return_value={"schema_version":1,"runs":[]}):
            self.assertEqual({}, self.call())
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertIsNone(self.call())
        with patch.object(source, "REGISTRY_SCHEMA_VERSION", 2):
            self.assertIsNone(self.call())
        import agent_run_registry
        with patch.object(agent_run_registry, "RUN_STATES", frozenset({"custom"})):
            self.write([{"run_id":"x","state":"custom"}])
            self.assertEqual({"x":"custom"}, self.call())

    def test_bad_responses_decline_once_to_reference(self):
        self.write([{"run_id":"a","state":"running"}])
        for value in (None, {}, {"value":False}, {"value":[["a","unknown"]]},
                      {"value":[["a","running"],["a","running"]]}):
            with patch.object(NativeProbe,"request",return_value=value) as request:
                self.assertEqual({"a":"running"}, self.call())
                self.assertEqual(1,request.call_count)

    def test_native_states_feed_the_original_retention_preview_without_deletion(self):
        self.write([{"run_id":"a"*32,"state":"running"},{"run_id":"b"*32,"state":"completed"}])
        with patch.dict(os.environ,self.env,clear=True):
            runs=source.runs_dir(self.project)
        runs.mkdir(exist_ok=True)
        for name in ("a"*32,"b"*32):
            folder=runs/name;folder.mkdir()
            (folder/"continuation.json").write_text('{"phase":"done"}')
        with patch.dict(os.environ,self.env,clear=True):
            expected=self.oracle.plan(self.project,keep=0,now=1700000000)
            with patch.object(NativeProbe,"request",wraps=NativeProbe.request) as request:
                actual,calls=self.profile(lambda:source.plan(self.project,keep=0,now=1700000000))
        self.assertEqual(expected,actual)
        self.assertEqual([],calls)
        self.assertEqual(1,request.call_count)
        self.assertIsInstance(actual["removable"],source._RemovalCandidates)
        self.assertEqual([runs/("b"*32)],actual["removable"])
        self.assertIsNotNone(actual["removable"].identities[runs/("b"*32)])
        self.assertTrue((runs/("a"*32)).is_dir());self.assertTrue((runs/("b"*32)).is_dir())

    def test_integer_profile_mismatch_and_unknown_schema_are_quiet(self):
        self.write([])
        payload={"state_dir":str(self.path.parent),"states":sorted(RUN_STATES),
                 "int_digits":getattr(sys,"get_int_max_str_digits",lambda:0)()+1}
        done=subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),
            "--registry-read-probe","retention-states"],input=json.dumps(payload).encode(),env=self.env,
            cwd=self.project,capture_output=True,timeout=8)
        self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))


if __name__ == "__main__":
    unittest.main()
