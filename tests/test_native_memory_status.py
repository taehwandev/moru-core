"""Recall callers observe source changes while sharing a per-recall hash cache."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import unicodedata
from unittest.mock import patch

import agent_project_memory as source
from native_pretool_support import environment, prepare
from support.native_memory import NativeMemory
from support.native_memory_status import NativeMemoryStatus


class NativeMemoryStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-status-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        tools = self.base / "tools"
        tools.mkdir()
        (tools / "git").symlink_to(shutil.which("git"))
        self.env = {**environment(self.base), "PATH": str(tools)}
        self.file = self.project / "a.py"
        self.file.write_text("original\r\n")
        self.other = self.project / "b.py"
        self.other.write_text("other")
        self.files = [{"path": name, "blob": self.blob(name)} for name in ("a.py", "b.py")]

    def blob(self, path):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            return source._source_blob(self.project, path)

    def status(self, files, cache, backend="auto"):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
            return source._source_status(self.project, {"source_files": files}, cache)

    def parity(self, files=None, cache=None):
        files = self.files if files is None else files
        original_cache = {} if cache is None else dict(cache)
        actual_cache = dict(original_cache)
        expected = self.status(files, original_cache, "python")
        with patch.dict(os.environ, self.env, clear=True):
            if all(f["path"] in actual_cache for f in files):
                with patch("support.native_memory_status.NativeProbe.request", side_effect=AssertionError("cache-only RPC")):
                    self.assertIsNone(NativeMemoryStatus.evaluate(self.project, files, actual_cache))
                    actual = self.status(files, actual_cache)
            else:
                actual = NativeMemoryStatus.evaluate(self.project, files, actual_cache)
        self.assertIsNotNone(actual)
        self.assertEqual(expected, actual)
        self.assertEqual(list(expected), list(actual))
        self.assertEqual(list(original_cache.items()), list(actual_cache.items()))
        return actual, actual_cache

    def test_changed_precedes_unavailable_and_warning_paths_keep_record_order(self):
        self.assertEqual({"source_status": "unchanged"}, self.parity()[0])
        self.file.unlink()
        self.assertEqual("unavailable", self.parity()[0]["source_status"])
        self.other.write_text("dirty")
        result, _ = self.parity()
        self.assertEqual({"source_status": "changed", "unverified_sources": ["a.py", "b.py"],
                          "warning": "Source evidence changed — verify before use"}, result)
        self.assertEqual(["b.py", "a.py"], self.parity(list(reversed(self.files)))[0]["unverified_sources"])

    def test_actual_caller_batches_hashes_without_python_source_loop(self):
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_source_blob", side_effect=AssertionError("Python hash loop")):
            cache = {}
            self.assertEqual({"source_status": "unchanged"},
                             source._source_status(self.project, {"source_files": self.files}, cache))
        self.assertEqual({f["path"]: f["blob"] for f in self.files}, cache)
        # Negative control: the same assertion detects removal of native wiring.
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(NativeMemoryStatus, "evaluate", return_value=None), \
             patch.object(source, "_source_blob", side_effect=AssertionError("Python hash loop")):
            with self.assertRaisesRegex(AssertionError, "Python hash loop"):
                source._source_status(self.project, {"source_files": self.files}, {})

    def test_shared_cache_survives_file_changes_and_preserves_unrelated_values(self):
        sentinel = object()
        cache = {"unused": sentinel}
        self.assertEqual("unchanged", self.status(self.files, cache)["source_status"])
        self.file.write_text("changed after the first record")
        self.assertEqual("unchanged", self.status(self.files, cache)["source_status"])
        self.assertIs(sentinel, cache["unused"])
        self.assertEqual("changed", self.status(self.files, {})["source_status"])
        self.assertEqual(["unused", "a.py", "b.py"], list(cache))
        self.other.write_text("changed after its cached evidence")
        mixed = {"b.py": self.files[1]["blob"], "unused": sentinel}
        result, mixed = self.parity(cache=mixed)
        self.assertEqual(["a.py"], result["unverified_sources"])
        self.assertEqual(["b.py", "unused", "a.py"], list(mixed))
        self.assertIs(sentinel, mixed["unused"])

    def fake_git(self):
        git = Path(self.env["PATH"]) / "git"
        git.unlink()
        git.write_text("#!/bin/sh\nprintf '%s\\n' \"$6\" >> \"$HASH_LOG\"\n"
                       "if [ \"$6\" = b.py ]; then printf '\\377'; else printf '%s\\n' " + "a" * 40 + "; fi\n")
        git.chmod(0o755)
        self.env["HASH_LOG"] = str(self.base / "hash-log")

    def test_decode_error_keeps_completed_cache_and_does_not_replay_git(self):
        self.fake_git()
        original_cache = {}
        with self.assertRaises(UnicodeDecodeError) as expected:
            self.status(self.files, original_cache, "python")
        log = self.base / "hash-log"
        self.assertEqual(["a.py", "b.py"], log.read_text().splitlines())
        log.unlink()
        actual_cache = {}
        with self.assertRaises(UnicodeDecodeError) as actual:
            self.status(self.files, actual_cache)
        self.assertEqual(expected.exception.args, actual.exception.args)
        self.assertEqual(original_cache, actual_cache)
        self.assertEqual({"a.py": "a" * 40}, actual_cache)
        self.assertEqual(["a.py", "b.py"], log.read_text().splitlines())

    def test_partial_decline_retains_completed_hash_before_original_loop_error(self):
        (self.project / "loop").symlink_to("loop")
        files = [self.files[0], {"path": "loop", "blob": "b" * 40}]
        expected_cache, cache = {}, {}
        try:
            expected = self.status(files, expected_cache, "python")
        except RuntimeError:
            with patch.object(source, "_source_blob", wraps=source._source_blob) as resumed, \
                 self.assertRaises(RuntimeError):
                self.status(files, cache)
            self.assertEqual(["loop"], [call.args[1] for call in resumed.call_args_list])
        else:
            self.assertEqual(expected, self.status(files, cache))
        self.assertEqual(expected_cache, cache)
        self.assertEqual(self.files[0]["blob"], cache["a.py"])

    def test_duplicate_and_shared_record_hash_queries_execute_once(self):
        self.fake_git()
        files = [self.files[0], {"path": "a.py", "blob": "different"}]
        cache = {}
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(source, "_source_blob", side_effect=AssertionError("Python hash loop")):
            self.assertEqual("changed", source._source_status(self.project, {"source_files": files}, cache)["source_status"])
            self.assertEqual("changed", source._source_status(self.project, {"source_files": files}, cache)["source_status"])
        self.assertEqual(["a.py"], (self.base / "hash-log").read_text().splitlines())

    def test_cached_and_duplicate_paths_need_no_git_and_keep_duplicate_warnings(self):
        cache = {"a.py": "changed", "b.py": ""}
        (Path(self.env["PATH"]) / "git").unlink()
        result, actual = self.parity([self.files[0], self.files[0], self.files[1]], cache)
        self.assertEqual(["a.py", "a.py", "b.py"], result["unverified_sources"])
        self.assertEqual(cache, actual)

    def test_empty_metadata_keeps_original_shape_and_cache(self):
        for files in (None, [], False, {}):
            cache = {"unused": "x"}
            self.assertEqual({}, self.status(files, cache))
            self.assertEqual({"unused": "x"}, cache)

    def test_unsupported_profile_uses_original_without_native_transport(self):
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(NativeMemory, "_source_profile", return_value=False), \
             patch("support.native_probe_transport.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertEqual("unchanged", source._source_status(self.project, {"source_files": self.files})["source_status"])

    def test_malformed_result_cannot_mutate_cache(self):
        for value in (None, {}, {"blobs": {"foreign": "a" * 40}, "result": None},
                      {"blobs": {"a.py": 1}, "result": None},
                      {"blobs": {"b.py": "a" * 40}, "result": None},
                      {"blobs": {"a.py": "a" * 40}, "result": {"source_status": "unchanged"}},
                      {"blobs": {"a.py": "a" * 40}, "result": {"source_status": "unknown"}},
                      {"blobs": {"a.py": "a" * 40, "b.py": "b" * 40}, "result": {
                          "source_status": "changed", "unverified_sources": ["b.py", "a.py"],
                          "warning": "Source evidence changed — verify before use"}},
                      {"blobs": {"a.py": "a" * 40, "b.py": "b" * 40}, "result": {
                          "source_status": "changed", "unverified_sources": ["a.py", "a.py"],
                          "warning": "Source evidence changed — verify before use"}},
                      {"blobs": {"a.py": "a" * 40}, "decode_error": [True]}):
            cache = {"unused": "x"}
            with patch.dict(os.environ, self.env, clear=True), \
                 patch("support.native_memory_status.NativeProbe.request", return_value=value):
                self.assertIsNone(NativeMemoryStatus.evaluate(self.project, self.files, cache))
            self.assertEqual({"unused": "x"}, cache)

    def test_custom_and_malformed_inputs_keep_source_exceptions(self):
        for files in ([{}], [{"path": []}], [None], {"x": 1}):
            with self.subTest(files=files):
                try:
                    expected = self.status(files, {}, "python")
                except Exception as error:
                    with self.assertRaises(type(error)):
                        self.status(files, {})
                else:
                    self.assertEqual(expected, self.status(files, {}))

    def test_custom_cache_keys_and_root_aliases_decline_before_transport(self):
        class CustomKey:
            def __hash__(self):
                return hash("a.py")

            def __eq__(self, other):
                raise AssertionError("custom key lookup")

        custom = {CustomKey(): "irrelevant"}
        alias = self.base / "project-link"
        alias.symlink_to(self.project, target_is_directory=True)
        with patch.dict(os.environ, self.env, clear=True), \
             patch("support.native_memory_status.NativeProbe.request", side_effect=AssertionError("transport")):
            self.assertIsNone(NativeMemoryStatus.evaluate(self.project, self.files, custom))
            self.assertIsNone(NativeMemoryStatus.evaluate(alias, self.files, {}))
            self.assertIsNone(NativeMemoryStatus.evaluate(Path("."), self.files, {}))
        self.assertEqual(1, len(custom))

    def test_retargeted_project_alias_preserves_each_source_root(self):
        other = self.base / "retargeted"
        other.mkdir()
        (other / "b.py").write_text("new-root evidence")
        alias = self.base / "project-link"
        alias.symlink_to(self.project, target_is_directory=True)
        git = Path(self.env["PATH"]) / "git"
        git.unlink()
        git.write_text("#!/bin/sh\nprintf '%s\\n' \"$2\" >> \"$HASH_LOG\"\n"
                       "if [ \"$6\" = a.py ]; then /bin/ln -sfn \"$NEW_ROOT\" \"$PROJECT_LINK\"; fi\n"
                       "if [ \"$2\" = \"$OLD_ROOT\" ]; then printf '%s\\n' " + "a" * 40
                       + "; else printf '%s\\n' " + "b" * 40 + "; fi\n")
        git.chmod(0o755)
        log = self.base / "root-log"
        self.env.update(HASH_LOG=str(log), NEW_ROOT=str(other), PROJECT_LINK=str(alias), OLD_ROOT=str(self.project))
        files = [{"path": "a.py", "blob": "a" * 40}, {"path": "b.py", "blob": "b" * 40}]
        caches, results = [], []
        for backend in ("python", "auto"):
            alias.unlink()
            alias.symlink_to(self.project, target_is_directory=True)
            if log.exists():
                log.unlink()
            cache = {}
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
                results.append(source._source_status(alias, {"source_files": files}, cache))
            caches.append(cache)
            self.assertEqual([str(self.project), str(other)], log.read_text().splitlines())
        self.assertEqual([{"source_status": "unchanged"}] * 2, results)
        self.assertEqual(caches[0], caches[1])

    def test_raw_protocol_rejects_unsupported_shapes_before_git(self):
        payload = {"unicode": unicodedata.unidata_version, "root": str(self.project),
                   "files": self.files, "blobs": {}, "stdin_eof": True, "encoding": "utf-8"}
        for fields in ({"extra": 1}, {"unicode": "unknown"}, {"stdin_eof": 1},
                       {"encoding": "ascii"}, {"files": [None]}, {"blobs": {"foreign": "a"}},
                       {"blobs": {"a.py": 1}}, {"files": self.files * 3}):
            done = subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
                                   "--memory-probe", "source-status"],
                                  input=json.dumps({**payload, **fields}).encode(), env=self.env,
                                  capture_output=True, timeout=8)
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
