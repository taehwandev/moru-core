"""Verification suggestions preserve Git text, paths and read-only process semantics."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest

from native_pretool_support import environment, result
import test_native_next as next_tests


class NativeNextVerificationTests(unittest.TestCase):
    setUp = next_tests.NativeNextTests.setUp

    def fake_git(self, stdout=b"", stderr=b"", status=0, body=None):
        binary = self.base / "fake-bin"
        binary.mkdir(exist_ok=True)
        log = self.base / "git-argv"
        script = binary / "git"
        def printf(data):
            return "printf '" + "".join("\\%03o" % byte for byte in data) + "'"
        script.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >> " + shlex.quote(str(log)) + "\n" +
                          (body if body is not None else printf(stdout) + "; " + printf(stderr) +
                           " >&2; exit " + str(status)) + "\n")
        script.chmod(0o755)
        return binary

    def parity(self, binary=None, *, native=True, input_bytes=b"", utf8=True,
               input_file=False, locale=None, extra_args=(), expected_code=None):
        binary = binary or self.git_only
        python_bin = self.base / "python-bin"
        python_bin.mkdir(exist_ok=True)
        if not (python_bin / "python3").exists():
            (python_bin / "python3").symlink_to(sys.executable)
        verification = None
        before = {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()}
        for output in ("json", "markdown"):
            args = [str(self.launcher), "next", "--project", str(self.project), "--format", output, *extra_args]
            env = environment(self.base)
            if not utf8:
                env.pop("PYTHONUTF8", None)
            if locale is not None:
                env["LC_ALL"] = locale
            env["PATH"] = str(binary) + os.pathsep + str(python_bin)
            def run(selected):
                if input_file:
                    path = self.base / "stdin-fixture"
                    path.write_bytes(input_bytes)
                    with path.open("rb") as stream:
                        return subprocess.run(args, cwd=self.project, env=selected, stdin=stream,
                                              capture_output=True, timeout=15)
                if not input_bytes:
                    return subprocess.run(args, cwd=self.project, env=selected, stdin=subprocess.DEVNULL,
                                          capture_output=True, timeout=15)
                return subprocess.run(args, cwd=self.project, env=selected, input=input_bytes,
                                      capture_output=True, timeout=15)
            reference = run({**env, "MORU_LAUNCHER_BACKEND": "python"})
            if expected_code is not None:
                self.assertEqual(expected_code, reference.returncode, reference.stderr)
            automatic = run(env)
            self.assertEqual(result(reference), result(automatic))
            actual = run({**env, "PATH": str(binary)})
            if native:
                self.assertEqual(0, reference.returncode, reference.stderr)
                self.assertEqual(result(reference), result(actual))
                if output == "json":
                    verification = json.loads(actual.stdout)["verification"]
            else:
                self.assertEqual(127, actual.returncode)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()})
        return verification

    def test_dirty_real_unicode_punctuation_and_quoted_names(self):
        for name in ["한글.py", "-dash.py", "a;b.py", "a$().py", "a'b.py", "a\nb.py", "..py", "...py"]:
            (self.project / name).write_text("synthetic\n")
        (self.project / "tests").mkdir()
        (self.project / "tests/test_-dash.py").write_text("synthetic\n")
        value = self.parity()
        self.assertTrue(value["changed_paths"])

    def test_fake_paths_normalization_unicode_columns_and_splitlines(self):
        (self.project / "tests").mkdir()
        for name in ["-dash.py", "test_x.py", "..py", "...py"]:
            (self.project / "tests" / name).write_text("synthetic\n")
        external = self.base / "external.py"
        external.write_text("synthetic\n")
        text = "😀😀😀./tests//test_x.py/.\u0085?? tests/-dash.py\u001c?? tests/..py\u2028"
        text += "?? tests/...py\n?? ../external.py\n?? " + str(external) + "\n?? a\u001fb.py\n"
        text += "?? .moru/excluded\n?? ./tests/test_x.py\n"
        value = self.parity(self.fake_git(text.encode()))
        self.assertIn("../external.py", value["changed_paths"])
        self.assertIn(str(external), value["changed_paths"])
        self.assertEqual(["status", "--porcelain", "--untracked-files=all"] * 6,
                         (self.base / "git-argv").read_text().splitlines())

    def test_nonzero_git_is_empty_even_with_valid_stdout(self):
        value = self.parity(self.fake_git(b"?? misleading.py\n", b"fatal\n", 128))
        self.assertEqual([], value["changed_paths"])

    def test_non_git_directory_is_native(self):
        shutil.rmtree(self.project / ".git")
        value = self.parity()
        self.assertEqual([], value["changed_paths"])

    def test_invalid_stdout_before_nonzero_exit_defers(self):
        self.parity(self.fake_git(b"\xff", status=7), native=False)

    def test_invalid_stderr_before_nonzero_exit_defers(self):
        self.parity(self.fake_git(b"?? a.py\n", b"\xff", 7), native=False)

    def test_git_inherits_stdin(self):
        value = self.parity(self.fake_git(body='read path; printf "?? %s\\n" "$path"'),
                            input_bytes=b"from-input.py\n", input_file=True)
        self.assertEqual(["from-input.py"], value["changed_paths"])

    def test_nonempty_pipe_defers_before_git_can_consume_it(self):
        self.parity(self.fake_git(body='read path; printf "?? %s\\n" "$path"'),
                    input_bytes=b"from-input.py\n", native=False)
        self.assertEqual(["status", "--porcelain", "--untracked-files=all"] * 4,
                         (self.base / "git-argv").read_text().splitlines())

    def test_anonymous_pipe_closed_before_launch_is_native(self):
        reader, writer = os.pipe()
        os.close(writer)
        try:
            with os.fdopen(os.dup(reader), "rb") as stream:
                actual = subprocess.run([str(self.launcher), "next", "--project", str(self.project), "--format=json"],
                    stdin=stream, env={**environment(self.base), "PATH": str(self.git_only)},
                    capture_output=True, timeout=15)
            self.assertEqual(0, actual.returncode, actual.stderr)
            self.assertEqual("no_active_run", json.loads(actual.stdout)["status"])
        finally:
            os.close(reader)

    def test_named_fifo_at_eof_declines_before_any_git_invocation(self):
        path = self.base / "named-fifo"
        os.mkfifo(path)
        reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(writer)
            binary = self.fake_git()
            with os.fdopen(os.dup(reader), "rb") as stream:
                actual = subprocess.run([str(self.launcher), "next", "--project", str(self.project)],
                    stdin=stream, env={**environment(self.base), "PATH": str(binary)},
                    capture_output=True, timeout=15)
            self.assertEqual(127, actual.returncode)
            self.assertFalse((self.base / "git-argv").exists())
        finally:
            os.close(reader)

    def test_invalid_output_after_read_rewinds_file_before_fallback(self):
        self.parity(self.fake_git(body='read path; if [ -n "$path" ]; then printf "\\377"; else printf "?? empty.py\\n"; fi'),
                    input_bytes=b"from-input.py\n", input_file=True, native=False)

    def test_later_preflight_failure_rewinds_successful_git_input(self):
        invalid = self.base / "invalid-preflight.json"
        invalid.write_text("{")
        binary = self.fake_git(body='read path; if [ -n "$path" ]; then printf "?? valid.py\\n"; else printf "\\377"; fi')
        self.parity(binary, input_bytes=b"from-input.py\n", input_file=True, native=False,
                    extra_args=("--evidence", str(invalid)), expected_code=0)

    def test_unproven_python_encoding_defers(self):
        self.parity(self.fake_git(b"?? a.py\n"), native=False, utf8=False, locale="en_US.ISO8859-1")

    def test_default_c_posix_utf8_without_explicit_python_flag(self):
        binary = self.fake_git("?? 한글.py\n".encode())
        for locale in ("C", "POSIX"):
            with self.subTest(locale=locale):
                self.parity(binary, utf8=False, locale=locale)

    def test_installed_utf8_locale_without_explicit_python_flag(self):
        installed = subprocess.run(["/usr/bin/locale", "-a"], capture_output=True, check=True).stdout.decode().splitlines()
        selected = next((name for name in installed if name.lower().endswith((".utf-8", ".utf8"))), None)
        self.assertIsNotNone(selected, "supported hosts must provide an installed UTF8 locale")
        self.parity(self.fake_git("?? 한글.py\n".encode()), utf8=False, locale=selected)


if __name__ == "__main__":
    unittest.main()
