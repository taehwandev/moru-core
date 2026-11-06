"""Next argument parsing preserves argparse output, status and ordering."""
import json
import os
import fcntl
import termios
import struct
import subprocess
import unittest

from native_next_support import invoke_next
from native_pretool_support import result, environment
import test_native_next_session as session_tests


class NativeNextCliTests(unittest.TestCase):
    setUp = session_tests.NativeNextSessionTests.setUp

    def call(self, args, *, backend="auto", no_python=False, **env):
        return invoke_next(self.launcher, self.base, self.project, args, backend=backend,
            **self.identity, **({"PATH": str(self.git_only)} if no_python else {}), **env)

    def parity(self, args, *, code=None, **env):
        reference = self.call(args, backend="python", **env)
        if code is not None:
            self.assertEqual(code, reference.returncode, reference.stderr)
        self.assertEqual(result(reference), result(self.call(args, **env)))
        self.assertEqual(result(reference), result(self.call(args, no_python=True, **env)))
        return reference

    def test_reordered_inline_abbreviated_and_repeated_options(self):
        project, evidence = str(self.project), str(self.evidence)
        for args in (
            ["--format=json", "--project=" + project],
            ["--f", "json", "--p", project, "--e", evidence],
            ["--evidence=" + evidence, "--format", "json", "--project", project],
            ["--format", "markdown", "--format", "json"],
            ["--project", project, "--project=.", "--format=json"],
            ["--project=", "--format=json"],
            ["--project", ".", "--format", "json"],
        ):
            with self.subTest(args=args):
                reference = self.parity(args, code=0)
                self.assertEqual(str(self.evidence), json.loads(reference.stdout)["evidence"])

    def test_missing_or_nonfile_explicit_evidence_uses_current_session(self):
        for value in ("", "absent.json", str(self.project), "~/not-expanded.json"):
            with self.subTest(value=value):
                reference = self.parity(["--format=json", "--evidence=" + value], code=0)
                self.assertEqual(str(self.evidence), json.loads(reference.stdout)["evidence"])

    def test_help_and_errors_need_no_git_or_python(self):
        empty = self.base / "empty"
        empty.mkdir()
        for args in (["--help"], ["--format", "bad"], ["--project"], ["--unknown"]):
            reference = self.call(args, backend="python")
            actual = self.call(args, PATH=str(empty))
            self.assertEqual(result(reference), result(actual))

    def test_missing_arguments_invalid_choices_and_unknown_tokens(self):
        for args in (
            ["--project"], ["--evidence"], ["--format"],
            ["--format="], ["--format=xml"], ["--format", "한글😀"],
            ["--format", "--help"], ["--project", "--format=json"],
            ["--project", "--format=bad value"],
            ["--unknown"], ["positional"], ["--", "--help"],
            ["--=x"], ["--unknown=x", "another"],
        ):
            with self.subTest(args=args):
                self.parity(args, code=2)

    def test_help_precedence_and_short_option_profile(self):
        for args in (
            ["-h"], ["--h"], ["-hh"], ["-hfoo"], ["-hhfoo"],
            ["-h=foo"], ["-hh=foo"], ["-h=h"], ["--help=foo"],
            ["--unknown", "--help"], ["--help", "--unknown"],
            ["--help", "--=x"], ["--=x", "--help"],
            ["--format=bad", "--help"], ["--help", "--format=bad"],
        ):
            with self.subTest(args=args):
                self.parity(args)

    def test_negative_number_classification_preserves_builder_profile(self):
        for value in ("-1", "-.5", "-1.5", "-1\n", "-1\n\n", "-1e2", "-٤", "-٤.٢"):
            with self.subTest(value=value):
                self.parity(["--format", value], code=2)

    def test_help_and_usage_width_match_terminal_columns(self):
        for columns in ("1", "2", "3", "20", "40", "60", "80", "120", "invalid", "-1",
                        "٤٠", "４０", "4_0", "\u2003+٤_٠\u2003", "1__2", "40_",
                        "\x1c40", "++40", "--40", "9" * 100, "-" + "9" * 100,
                        "0" * 4500 + "40", "0" * 4000 + "40"):
            with self.subTest(columns=columns):
                self.parity(["--help"], code=0, COLUMNS=columns)
                self.parity(["--format=bad"], code=2, COLUMNS=columns)

    def test_zero_column_pty_uses_builder_terminal_policy(self):
        for columns in ("1__2", "٤_٠", "1", "0"):
            for args in (["--help"], ["--format=bad"]):
                outputs = []
                for backend in ("python", "auto"):
                    master, slave = os.openpty()
                    try:
                        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 0, 0, 0))
                        env = {**environment(self.base), "NO_COLOR": "1", "COLUMNS": columns,
                               "MORU_LAUNCHER_BACKEND": backend}
                        if backend == "auto":
                            env["PATH"] = str(self.git_only)
                        done = subprocess.run([str(self.launcher), "next", *args],
                            stdout=slave, stderr=subprocess.PIPE, env=env, cwd=self.project, timeout=15)
                        os.close(slave)
                        slave = -1
                        data = bytearray()
                        while True:
                            try:
                                chunk = os.read(master, 4096)
                            except OSError as error:
                                if error.errno != 5:
                                    raise
                                break
                            if not chunk:
                                break
                            data.extend(chunk)
                        outputs.append((done.returncode, bytes(data), done.stderr))
                    finally:
                        if slave >= 0:
                            os.close(slave)
                        os.close(master)
                self.assertEqual(2 if args == ["--format=bad"] else 0, outputs[0][0])
                self.assertEqual(outputs[0], outputs[1], (columns, args))

    def test_end_marker_and_empty_explicit_values_preserve_argparse(self):
        for args in (["--"], ["--format=json", "--"], ["--", ""], [""]):
            with self.subTest(args=args):
                self.parity(args)

    def test_forced_terminal_color_keeps_builder_output_policy(self):
        for args in (["--help"], ["--format=bad"]):
            env = {"FORCE_COLOR": "1", "NO_COLOR": "", "TERM": "xterm-256color"}
            reference = self.call(args, backend="python", **env)
            self.assertEqual(result(reference), result(self.call(args, **env)))
            actual = self.call(args, no_python=True, **env)
            if b"\x1b[" in reference.stdout + reference.stderr:
                self.assertEqual(127, actual.returncode)
            else:
                self.assertEqual(result(reference), result(actual))
            self.parity(args, FORCE_COLOR="1", NO_COLOR="1", TERM="xterm-256color")


if __name__ == "__main__":
    unittest.main()
