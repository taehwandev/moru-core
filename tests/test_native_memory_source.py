"""Memory callers verify worktree evidence through real native/Git boundaries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from unittest.mock import patch

import agent_project_memory as source
from native_pretool_support import environment, prepare
from support.native_memory import NativeMemory


class NativeMemorySourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-memory-source-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.tools = self.base / "tools"
        self.tools.mkdir()
        (self.tools / "git").symlink_to(shutil.which("git"))
        self.env = {**environment(self.base), "PATH": str(self.tools)}
        self.path = self.project / "src" / "프로필 space.py"
        self.path.parent.mkdir()
        self.path.write_bytes(b"dirty\r\nbytes\x00\xff")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], env=self.env,
                              capture_output=True, check=True, timeout=5)

    def original(self, path, tracked=False):
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            return source._source_blob(self.project, path, tracked=tracked)

    def native(self, path, tracked=False):
        with patch.dict(os.environ, self.env, clear=True):
            return NativeMemory.blob(self.project, path, tracked)

    def parity(self, path, tracked=False):
        expected = self.original(path, tracked)
        actual = self.native(path, tracked)
        self.assertIsNotNone(actual)
        self.assertEqual(expected, actual["blob"])
        return actual["blob"]

    def test_dirty_bytes_filters_and_index_are_preserved(self):
        relative = self.path.relative_to(self.project).as_posix()
        self.git("add", "--", relative)
        before = (self.project / ".git/index").read_bytes()
        (self.project / ".gitattributes").write_text("*.py text\n")
        self.path.write_bytes(b"changed\r\n\x00\xff")
        raw = self.path.read_bytes()
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        objects = sorted(p.relative_to(self.project / ".git/objects").as_posix()
                         for p in (self.project / ".git/objects").rglob("*"))
        self.assertEqual(expected, self.parity(relative, tracked=True))
        self.assertEqual(raw, self.path.read_bytes())
        self.assertEqual(before, (self.project / ".git/index").read_bytes())
        self.assertEqual(objects, sorted(p.relative_to(self.project / ".git/objects").as_posix()
                                        for p in (self.project / ".git/objects").rglob("*")))

    def test_untracked_missing_directory_and_symlinks_are_unavailable(self):
        relative = self.path.relative_to(self.project).as_posix()
        self.assertTrue(self.parity(relative))
        self.assertEqual("", self.parity(relative, tracked=True))
        (self.project / "link.py").symlink_to(self.path)
        (self.project / "linked").symlink_to(self.path.parent)
        os.mkfifo(self.project / "fifo")
        for path in ("missing.py", "src", "link.py", "linked/프로필 space.py", "fifo"):
            with self.subTest(path=path):
                self.assertEqual("", self.parity(path))

    def test_literal_git_pathspecs_do_not_match_another_file(self):
        self.git("add", "--", "src/프로필 space.py")
        for name in ("*.py", ":(glob)*", "-leading.py", "[x].py"):
            (self.project / name).write_bytes(b"literal")
            self.assertEqual("", self.parity(name, tracked=True))
            self.git("add", "--", ":(literal)" + name)
            self.assertTrue(self.parity(name, tracked=True))

    def test_sha256_repository_keeps_64_digit_blobs(self):
        other = self.base / "sha256"
        subprocess.run(["git", "init", "-q", "--object-format=sha256", str(other)],
                       env=self.env, check=True, capture_output=True, timeout=5)
        (other / "a.py").write_bytes(b"raw\r\n")
        with patch.dict(os.environ, self.env, clear=True):
            actual = NativeMemory.blob(other, "a.py", False)
        expected = hashlib.sha256(b"blob 5\0raw\r\n").hexdigest()
        self.assertEqual({"blob": expected}, actual)

    def test_real_caller_avoids_python_file_checks_and_git_replay(self):
        expected = self.original("src/프로필 space.py")
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(Path, "is_file", side_effect=AssertionError("Python file check")), \
             patch.object(source.subprocess, "run", wraps=subprocess.run) as run:
            # NativeProbe.available is the only expected Python is_file call.
            with patch("support.native_probe_transport.NativeProbe.available", return_value=True):
                self.assertEqual(expected, source._source_blob(self.project, "src/프로필 space.py"))
            self.assertTrue(run.call_args_list)
            self.assertTrue(all(call.args[0][0] == str(self.entry.with_name("moru-hook-native"))
                                for call in run.call_args_list))
        # Negative control: removing native admission must expose Python replay.
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(NativeMemory, "blob", return_value=None), \
             patch.object(Path, "is_file", side_effect=AssertionError("Python replay")):
            with self.assertRaisesRegex(AssertionError, "Python replay"):
                source._source_blob(self.project, "src/프로필 space.py")

    def test_unsafe_protocol_paths_are_rejected_before_git(self):
        for path in ("../a.py", ".git/config", "./a.py", "a//b.py", "a/./b.py",
                     "a/../b.py", "/absolute", "a\\b.py", ".", "", "bad\npath"):
            with self.subTest(path=path):
                self.assertEqual({"blob": ""}, self.native(path))

    def test_missing_git_is_unavailable_without_python_replay(self):
        (self.tools / "git").unlink()
        self.assertEqual("", self.parity("src/프로필 space.py"))

    def fake_git(self, body):
        path = self.tools / "git"
        path.unlink()
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def test_git_errors_and_malformed_hash_are_unavailable(self):
        self.fake_git("printf 'invalid hash\\n'\n")
        self.assertEqual("", self.parity("src/프로필 space.py"))
        (self.tools / "git").write_text("#!/bin/sh\nprintf '%s\\n' " + "a" * 40 + "\nexit 1\n")
        self.assertEqual("", self.parity("src/프로필 space.py"))
        self.assertEqual("", self.parity("src/프로필 space.py", tracked=True))

    def test_git_timeout_returns_unavailable_within_the_bound(self):
        self.fake_git("exec /bin/sleep 3\n")
        started = time.monotonic()
        self.assertEqual({"blob": ""}, self.native("src/프로필 space.py"))
        self.assertLess(time.monotonic() - started, 5)

    def test_non_utf8_git_pipes_keep_original_decoding_errors(self):
        self.fake_git("printf 'called\\n' >> \"$SOURCE_GIT_LOG\"\n"
                      "printf '%s\\n' " + "a" * 40 + "\nprintf '\\377' >&2\n")
        log = self.base / "git-calls"
        self.env["SOURCE_GIT_LOG"] = str(log)
        with self.assertRaises(UnicodeDecodeError) as expected:
            self.original("src/프로필 space.py")
        log.unlink()
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(UnicodeDecodeError) as actual:
            source._source_blob(self.project, "src/프로필 space.py")
        self.assertEqual(expected.exception.args, actual.exception.args)
        self.assertEqual("called\n", log.read_text())  # No Git replay after decoding failure.

    def test_source_status_changes_and_unavailable_are_visible(self):
        relative = "src/프로필 space.py"
        record = {"source_files": [{"path": relative, "blob": self.original(relative)}]}
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual({"source_status": "unchanged"}, source._source_status(self.project, record))
            self.path.write_text("changed")
            changed = source._source_status(self.project, record)
            self.assertEqual("changed", changed["source_status"])
            self.assertEqual([relative], changed["unverified_sources"])
            self.path.unlink()
            self.assertEqual("unavailable", source._source_status(self.project, record)["source_status"])

    def test_malformed_bridge_results_fall_back(self):
        for value in (None, {}, {"blob": None}, {"blob": "A" * 40}, {"blob": "x"},
                      {"blob": "a" * 40, "extra": True}):
            with self.subTest(value=value), \
                 patch("support.native_memory.NativeProbe.request", return_value=value):
                self.assertIsNone(self.native("src/프로필 space.py"))

    def test_protocol_schema_and_unicode_profile_decline(self):
        payload = {"unicode": unicodedata.unidata_version, "root": str(self.project),
                   "path": "src/프로필 space.py", "tracked": False, "stdin_eof": True, "encoding": "utf-8"}
        for fields in ({"unicode": "unknown"}, {"tracked": 1}, {"extra": True}, {"root": "."},
                       {"stdin_eof": False}, {"stdin_eof": 1}, {"encoding": "ascii"},
                       {"root": "/dev/fd/0"}, {"root": "/proc/self/fd"}):
            done = subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
                                   "--memory-probe", "blob"], input=json.dumps({**payload, **fields}).encode(),
                                  env=self.env, capture_output=True, timeout=8)
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))

    def test_exact_git_argv_and_binary_tracked_output(self):
        self.fake_git("printf '%s\\n' \"$@\" >> \"$SOURCE_GIT_LOG\"\n"
                      "if [ \"$1\" = --literal-pathspecs ]; then printf '\\377'; exit 0; fi\n"
                      "printf '%s\\n' " + "a" * 40 + "\n")
        log = self.base / "argv"
        self.env["SOURCE_GIT_LOG"] = str(log)
        self.assertEqual({"blob": "a" * 40}, self.native("src/프로필 space.py", tracked=True))
        self.assertEqual(["--literal-pathspecs", "-C", str(self.project), "ls-files", "--error-unmatch",
                          "--", "src/프로필 space.py", "-C", str(self.project), "hash-object", "--no-filters",
                          "--", "src/프로필 space.py"], log.read_text().splitlines())

    def test_utf8_whitespace_stderr_and_decode_order(self):
        self.fake_git("printf '\\302\\240%s\\302\\205' " + "a" * 40 + "\nprintf '한글' >&2\n")
        self.assertEqual("a" * 40, self.parity("src/프로필 space.py"))
        (self.tools / "git").write_text("#!/bin/sh\nprintf '\\377stdout'\nprintf '\\376stderr' >&2\nexit 1\n")
        with self.assertRaises(UnicodeDecodeError) as expected:
            self.original("src/프로필 space.py")
        with self.assertRaises(UnicodeDecodeError) as actual:
            self.native("src/프로필 space.py")
        self.assertEqual(expected.exception.args, actual.exception.args)
        self.assertEqual(b"\xffstdout", actual.exception.object)

    def test_loop_and_root_alias_keep_source_resolution_behavior(self):
        (self.project / "loop").symlink_to("loop")
        self.assertIsNone(self.native("loop"))
        with patch.dict(os.environ, self.env, clear=True):
            try:
                expected = self.original("loop")
            except RuntimeError:
                with self.assertRaises(RuntimeError):
                    source._source_blob(self.project, "loop")
            else:
                self.assertEqual(expected, source._source_blob(self.project, "loop"))
        alias = self.project.with_name(self.project.name.upper())
        if alias.exists():  # Darwin case-insensitive volume: argv spelling must survive.
            with patch.dict(os.environ, self.env, clear=True):
                self.assertEqual(self.original("src/프로필 space.py"),
                                 NativeMemory.blob(alias, "src/프로필 space.py", False)["blob"])

    def test_stdin_admission_does_not_read_live_input(self):
        program = ("from support.native_memory import NativeMemory; "
                   "import os; print(NativeMemory._source_profile(), flush=True); "
                   "print(os.read(0, 4).hex(), flush=True)")
        env = {**self.env, "PYTHONPATH": str(Path(source.__file__).parent)}
        for data, closed, accepted in ((b"", True, True), (b"data", True, False), (b"data", False, False)):
            reader, writer = os.pipe()
            try:
                if data:
                    os.write(writer, data)
                if closed:
                    os.close(writer)
                    writer = None
                done = subprocess.run([sys.executable, "-B", "-c", program], stdin=reader,
                                      env=env, capture_output=True, timeout=5, text=True)
                self.assertEqual(0, done.returncode, done.stderr)
                self.assertEqual([str(accepted), data.hex()], done.stdout.splitlines())
            finally:
                os.close(reader)
                if writer is not None:
                    os.close(writer)
        done = subprocess.run([sys.executable, "-B", "-c", program], stdin=subprocess.DEVNULL,
                              env=env, capture_output=True, timeout=5, text=True)
        self.assertEqual(["True", ""], done.stdout.splitlines())

    def test_unproven_profiles_decline_before_transport(self):
        for target, value in (("_source_profile", False),):
            with patch.object(NativeMemory, target, return_value=value), \
                 patch("support.native_memory.NativeProbe.request", side_effect=AssertionError("transport")):
                self.assertIsNone(NativeMemory.blob(self.project, "x", False))
        with patch("locale.getpreferredencoding", return_value="ascii"):
            self.assertFalse(NativeMemory._source_profile())
        for root, path, tracked in ((str(self.project), "x", False), (self.project, b"x", False),
                                    (self.project, "x", 1)):
            self.assertIsNone(NativeMemory.blob(root, path, tracked))

    def test_tty_regular_file_named_fifo_and_live_empty_pipe_decline(self):
        import pty
        probe = "from support.native_memory import NativeMemory; print(NativeMemory._source_profile())"
        env = {**self.env, "PYTHONPATH": str(Path(source.__file__).parent)}
        def check(fd):
            done = subprocess.run([sys.executable, "-B", "-c", probe], stdin=fd,
                                  env=env, capture_output=True, timeout=5, text=True)
            self.assertEqual((0, "False\n", ""), (done.returncode, done.stdout, done.stderr))
        with self.path.open("rb") as regular:
            check(regular)
            self.assertEqual(0, regular.tell())
        master, slave = pty.openpty()
        try:
            check(slave)
        finally:
            os.close(master)
            os.close(slave)
        reader, writer = os.pipe()
        try:
            check(reader)
        finally:
            os.close(reader)
            os.close(writer)
        fifo = self.base / "named-input"
        os.mkfifo(fifo)
        reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            check(reader)
        finally:
            os.close(reader)

    def test_malformed_decode_packets_cannot_raise_or_replay(self):
        for raw in ([], [65], [256], [True], "invalid", [255, "x"]):
            with patch("support.native_memory.NativeProbe.request", return_value={"decode_error": raw}):
                self.assertIsNone(self.native("src/프로필 space.py"))
