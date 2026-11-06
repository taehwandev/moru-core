"""Exercise native ps fallback from real dead-leader sessions without Python on PATH."""
import json
import os
from pathlib import Path
import unittest

from native_next_ps_support import dead_session_next
from native_pretool_support import environment
import test_native_next_session as session_tests


class NativeNextPsTests(unittest.TestCase):
    setUp = session_tests.NativeNextSessionTests.setUp
    add_run = session_tests.NativeNextSessionTests.add_run

    def check(self, body, active, *, pid=123456789, input_bytes=None, native=True, env=None):
        peer = self.add_run("c" * 32, session="synthetic-next")
        if pid == 123456789:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertFalse((Path("/proc") / str(pid) / "stat").exists())
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["owner"] = {}
        registry["runs"][1]["owner"] = {"pid": pid, "start_token": ""}
        self.registry.write_text(json.dumps(registry))
        before = {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()}
        report = dead_session_next(self.launcher, self.project, self.base,
                                   (self.git_only / "git").resolve(), body, input_bytes=input_bytes, env=env)
        calls = report["calls"]
        for index in (0, 2):
            self.assertEqual(0, calls[index]["returncode"], calls[index]["stderr"])
            if native:
                self.assertEqual(calls[index], calls[index + 1])
            else:
                self.assertEqual(127, calls[index + 1]["returncode"])
        value = json.loads(calls[0]["stdout"])
        self.assertEqual("active_run" if active else "no_active_run", value["status"])
        if active:
            self.assertEqual(str(peer), value["evidence"])
        if body is not None:
            self.assertEqual(["-o", "ppid=", "-p", str(report["sid"])] * (4 if native else 2), report["argv"])
        self.assertEqual(before, {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()})

    def test_decimal_parent_selects_exact_owner(self):
        self.check("printf '123456789\\n'", True)

    def test_unicode_underscores_whitespace_and_nonzero_exit(self):
        self.check("printf '\\r\\n１２３_٤٥٦_789\\r'; exit 7", True)

    def test_malformed_parent_has_no_owner(self):
        self.check("printf '123__456789\\n'", False)

    def test_empty_parent_has_no_owner(self):
        self.check("exit 0", False)

    def test_invalid_stdout_has_no_owner(self):
        self.check("printf '\\377'", False)

    def test_invalid_stderr_has_no_owner(self):
        self.check("printf '123456789'; printf '\\377' >&2", False)

    def test_unavailable_ps_has_no_owner(self):
        self.check(None, False)

    def test_ps_inherits_command_stdin(self):
        self.check('read parent; printf "%s\\n" "$parent"', True, input_bytes=b"123456789\n")

    def test_unproven_text_encoding_defers_before_ps(self):
        env = environment(self.base)
        env.pop("PYTHONUTF8", None)
        self.check("printf '123456789\\n'", True, native=False, env=env)

    def test_ps_timeout_has_no_owner(self):
        self.check("exec /bin/sleep 6", False)


if __name__ == "__main__":
    unittest.main()
