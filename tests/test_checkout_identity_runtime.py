"""Process-level parity and actual direct-entrypoint selection, not mocked ports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import checkout_identity
from checkout_identity_support import (
    BINARY, LIMIT, PROJECT, PYTHON, WRAPPER, CheckoutFixtures,
    environment, invoke, request, rows,
)
from claude_worktree_gate import current_branch, git_common_dir


class CheckoutIdentityRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BINARY.is_file():
            raise AssertionError("build the actual runtime: python3 scripts/build_native_runtime.py")
        cls.directory = tempfile.TemporaryDirectory(prefix="checkout-runtime-tests-")
        cls.fixture = CheckoutFixtures(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def assert_backends(self, payload, expected=None, **kwargs):
        actual_python = rows(invoke(PYTHON, payload, **kwargs))
        actual_rust = rows(invoke([str(WRAPPER)], payload, backend="rust", **kwargs))
        self.assertEqual(actual_python, actual_rust)
        if expected is not None:
            self.assertEqual(expected, actual_rust)
        return actual_rust

    def test_real_layouts_match_original_functions_and_auto_entrypoint(self):
        for root in self.fixture.roots:
            with self.subTest(root=root.name):
                common = git_common_dir(root)
                expected = [{"schema_version": 1, "ok": True,
                             "common_dir": str(common) if common else None,
                             "branch": current_branch(root)}]
                self.assert_backends(request(root), expected)
                self.assertEqual(expected, rows(invoke([str(WRAPPER)], request(root))))

    def test_invalid_shapes_and_recovery(self):
        cases = [None, [], {}, True, {"schema_version": True, "root": "/"},
                 {"schema_version": 1.0, "root": "/"}, {"schema_version": 2, "root": "/"},
                 {"schema_version": 1, "root": "relative"}, {"schema_version": 1, "root": ""},
                 {"schema_version": 1, "root": "/bad\0path"},
                 {"schema_version": 1, "root": "/", "extra": 1}]
        payload = b"".join((json.dumps(value) + "\n").encode() for value in cases)
        actual = self.assert_backends(payload + request(self.fixture.main))
        self.assertEqual(["invalid_request"] * len(cases), [r["error"] for r in actual[:-1]])
        self.assertTrue(actual[-1]["ok"])

    def test_malformed_unicode_and_json(self):
        for payload in (b"\xff\n", b"{\n", b"\n"):
            with self.subTest(payload=payload):
                self.assert_backends(payload, [checkout_identity.failure("invalid_json")])
        self.assert_backends(b"\xef\xbb\xbf" + request(self.fixture.main))
        self.assert_backends(b'{"schema_version":1,"root":"/bad\\ud800"}\n',
                             [checkout_identity.failure("io_error")])

    def test_exact_limit_and_oversize_drain_recovery(self):
        valid = request(self.fixture.main).rstrip(b"\n")
        exact = valid + b" " * (LIMIT - len(valid) - 1) + b"\n"
        self.assertTrue(self.assert_backends(exact)[0]["ok"])
        actual = self.assert_backends(b"x" * LIMIT + b"\n" + request(self.fixture.main))
        self.assertEqual(checkout_identity.failure("input_too_large"), actual[0])
        self.assertTrue(actual[1]["ok"])

    def test_empty_eof_and_final_line_without_newline(self):
        self.assert_backends(b"", [])
        self.assert_backends(request(self.fixture.main).rstrip(b"\n"))

    def test_live_stream_observes_head_mutation(self):
        head = self.fixture.main / ".git" / "HEAD"
        original = head.read_text()
        for command in (PYTHON, [str(WRAPPER)]):
            with self.subTest(command=command):
                process = subprocess.Popen(command, env=environment("rust"), stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    process.stdin.write(request(self.fixture.main))
                    process.stdin.flush()
                    self.assertEqual("main", json.loads(process.stdout.readline())["branch"])
                    head.write_text("ref: refs/heads/changed\n")
                    process.stdin.write(request(self.fixture.main))
                    process.stdin.flush()
                    self.assertEqual("changed", json.loads(process.stdout.readline())["branch"])
                    process.stdin.close()
                    self.assertEqual(0, process.wait(timeout=5))
                finally:
                    head.write_text(original)
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdout.close()
                    process.stderr.close()

    def test_native_wrapper_needs_no_python_git_or_toolchain(self):
        with tempfile.TemporaryDirectory(prefix="checkout-no-path-") as tmp:
            expected = rows(invoke(PYTHON, request(self.fixture.main)))
            self.assertEqual(expected, rows(invoke([str(WRAPPER)], request(self.fixture.main), path=tmp)))
            for root in (self.fixture.detached, self.fixture.base / "empty"):
                self.assert_backends(request(root), path=tmp)

    def test_missing_binary_falls_back_and_explicit_rollback(self):
        with tempfile.TemporaryDirectory(prefix="checkout-wrapper-") as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            wrapper = root / "scripts" / WRAPPER.name
            shutil.copy2(WRAPPER, wrapper)
            shutil.copy2(PROJECT / "scripts/checkout_identity.py", root / "scripts/checkout_identity.py")
            env = environment()
            env["PYTHONPATH"] = str(PROJECT / "scripts")
            result = subprocess.run([str(wrapper)], input=request(self.fixture.main),
                                    capture_output=True, env=env, timeout=5)
            self.assertEqual(rows(invoke(PYTHON, request(self.fixture.main))), rows(result))
            required = invoke([str(wrapper)], request(self.fixture.main), backend="rust")
            self.assertEqual(127, required.returncode)
        self.assertEqual(rows(invoke(PYTHON, request(self.fixture.main))),
                         rows(invoke([str(WRAPPER)], request(self.fixture.main), backend="python")))

    def test_invalid_backend_arguments_and_native_failure_propagation(self):
        self.assertEqual(2, invoke([str(WRAPPER)], backend="unknown").returncode)
        self.assertEqual(2, invoke([str(WRAPPER), "--bad"]).returncode)
        self.assertEqual(0, invoke([str(WRAPPER), "--help"]).returncode)
        with tempfile.TemporaryDirectory(prefix="checkout-native-failure-") as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / ".moru/native/bin").mkdir(parents=True)
            wrapper = root / "scripts" / WRAPPER.name
            shutil.copy2(WRAPPER, wrapper)
            binary = root / ".moru/native/bin" / BINARY.name
            binary.write_text("#!/bin/sh\nexit 23\n")
            binary.chmod(0o755)
            result = invoke([str(wrapper)], request(self.fixture.main))
            self.assertEqual(23, result.returncode)
            self.assertEqual(b"", result.stdout)

    def test_git_fallback_timeout_and_invalid_output(self):
        with tempfile.TemporaryDirectory(prefix="checkout-fake-git-") as tmp:
            git = Path(tmp) / "git"
            git.write_text("#!/bin/sh\nexec /bin/sleep 8\n")
            git.chmod(0o755)
            started = time.monotonic()
            self.assert_backends(request(self.fixture.detached), path=tmp, timeout=5)
            self.assertLess(time.monotonic() - started, 5)
            git.write_text("#!/bin/sh\nprintf '\\377'\n")
            self.assert_backends(request(self.fixture.detached), path=tmp,
                                 expected=[checkout_identity.failure("io_error")])

    def test_git_descendant_open_pipe_still_respects_timeout(self):
        with tempfile.TemporaryDirectory(prefix="checkout-git-pipe-") as tmp:
            pid_file = Path(tmp) / "owned-child.pid"
            git = Path(tmp) / "git"
            git.write_text("#!/bin/sh\n/bin/sleep 8 &\n"
                           + "printf '%s' \"$!\" > " + shlex.quote(str(pid_file)) + "\nexit 0\n")
            git.chmod(0o755)
            for command in (PYTHON, [str(WRAPPER)]):
                with self.subTest(command=command):
                    try:
                        result = invoke(command, request(self.fixture.detached),
                                        backend="rust", path=tmp, timeout=3.5)
                        self.assertEqual("", rows(result)[0]["branch"])
                    finally:
                        if pid_file.exists():
                            try:
                                os.kill(int(pid_file.read_text()), signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            pid_file.unlink()


class CheckoutIdentityAdapterTests(unittest.TestCase):
    def test_invalid_input_does_not_call_lookup(self):
        with patch.object(checkout_identity, "git_common_dir", side_effect=AssertionError("lookup")):
            self.assertEqual(checkout_identity.failure("invalid_request"), checkout_identity.answer(b"{}"))

    def test_input_io_error_is_not_successful_eof(self):
        class BrokenInput:
            buffer = None

            def __init__(self):
                self.buffer = self

            def readline(self, size):
                raise OSError("read failed")

        with patch.object(checkout_identity.sys, "stdin", BrokenInput()), patch.object(checkout_identity.sys, "argv", ["adapter"]):
            with self.assertRaises(OSError):
                checkout_identity.main()


if __name__ == "__main__":
    unittest.main()
