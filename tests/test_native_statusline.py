"""Real generated-entrypoint parity, compatibility and one-shot chain behavior."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from checkout_identity_support import PROJECT
from native_launcher_support import NATIVE, fixture_root, install, run_launcher
from support.statusline import render


class NativeStatuslineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NATIVE.is_file():
            raise AssertionError("build actual native runtime before testing")
        cls.temp = tempfile.TemporaryDirectory(prefix="native-statusline-")
        cls.base = Path(cls.temp.name)
        cls.home = cls.base / "home 한글"
        install(cls.home)
        cls.launcher = cls.home / ".moru/bin/moru-hook"
        cls.empty = cls.base / "empty"
        cls.empty.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cli(self, data, *args, alias="claude-statusline", **kwargs):
        return run_launcher(self.launcher, self.home, alias, *args, data=data,
                            NO_COLOR=kwargs.pop("NO_COLOR", "1"), **kwargs)

    def expected(self, text, color=False):
        with patch.dict(os.environ, HOME=str(self.home)):
            return render(text, color=color).encode()

    def assert_native(self, payload, color=False):
        text = json.dumps(payload, ensure_ascii=False)
        actual = self.cli(text.encode(), path=self.empty, NO_COLOR="" if color else "1")
        self.assertEqual((0, self.expected(text, color), b""),
                         (actual.returncode, actual.stdout, actual.stderr), text)

    def test_both_aliases_run_without_python_and_share_output(self):
        payload = b'{"model":"Example","rate_limits":{"session":{"percent":65}}}'
        for alias in ("claude-statusline", "agy-statusline"):
            result = self.cli(payload, alias=alias, path=self.empty)
            self.assertEqual((0, self.expected(payload.decode()), b""),
                             (result.returncode, result.stdout, result.stderr))

    def test_bankers_rounding_gauges_colors_and_numeric_precedence(self):
        values = [i + .5 for i in range(-2, 103)] + [i * 1.5625 for i in range(65)]
        values += [random.Random(i).uniform(-100, 200) for i in range(100)]
        for i, value in enumerate(values):
            with self.subTest(value=value):
                self.assert_native({"rate_limits": {"session": {"percent": value},
                    "week": {"used_percentage": False, "used_percent": "bad", "percent": value}}},
                    color=bool(i % 2))

    def test_paths_truthiness_unicode_and_prefix_boundaries(self):
        paths = [str(self.home), str(self.home) + "/", str(self.home) + "/a",
                 str(self.home) + "sibling/a", "/a/b/한글😀" * 5,
                 "/a/b/" + "한" * 12 + "/leaf", "a/b/" + "x" * 50 + "/c/d",
                 "/a//b/" + "x" * 50 + "/leaf", " " * 40, "/" + "x" * 90]
        for path in paths:
            self.assert_native({"model": {"display_name": [], "id": "\u001c Model \u001f"},
                                "workspace": {"project_dir": "", "current_dir": path}}, color=True)
        for model in (None, False, 42, [], {}, "", " model "):
            self.assert_native({"model": model, "workspace": {}, "cwd": "/a"})

    def test_window_order_duplicate_keys_and_stated_minutes(self):
        for entries in [
            [("seven_day", {"percent": 1}), ("week", {"percent": 90})],
            [("week", {"percent": 90}), ("seven_day", {"percent": 1})],
        ]:
            self.assert_native({"rate_limits": dict(entries)})
        for minutes in ("300", "10080", "301", 299.5, 300.5, -1, True, "invalid"):
            self.assert_native({"rate_limits": [{"kind": "session", "percent": "65.5",
                                                  "window_minutes": minutes}]})
        text = '{"rate_limits":{"week":{"percent":1},"week":{"percent":90},"seven_day":{"percent":2}}}'
        result = self.cli(text.encode(), path=self.empty)
        self.assertEqual((0, self.expected(text)), (result.returncode, result.stdout))

    def test_numeric_strings_run_without_python_for_both_runtimes(self):
        values = ["٦٥", "６５.５", "𝟞𝟝.𝟝", "+٦_٥.٥e-٠", "6_5", "6_5.5_0",
                  "6.5e+1", "\u200365.5\u3000", "\u008565\u00a0", "-0", "1e-999",
                  "_65", "65_", "6__5", "6_.5", "6._5", "6e_1", "6e+_1",
                  "٦٫٥", "²", "Ⅵ", "−65", "65\x00", "\x1c65", "65\x1f",
                  "\u200b65", "", "bad", "nanx", "infinityx"]
        for alias in ("claude-statusline", "agy-statusline"):
            for value in values:
                with self.subTest(alias=alias, value=value):
                    text = json.dumps({"rate_limits": {"session": {
                        "used_percentage": value, "percent": 25}}}, ensure_ascii=False)
                    actual = self.cli(text.encode(), alias=alias, path=self.empty)
                    self.assertEqual((0, self.expected(text), b""),
                                     (actual.returncode, actual.stdout, actual.stderr))
        for minutes in ("٣_٠٠", "１_００８０", "𝟛𝟘𝟘.𝟝", "\x1c300", "300_", "\u2003300"):
            self.assert_native({"rate_limits": {"session": {
                "percent": "٦٥", "window_minutes": minutes}}})
        self.assert_native({"rate_limits": {"unknown": {"percent": "NaN"}}})
        self.assert_native({"rate_limits": [
            {"kind": "session", "percent": "NaN"}, {"kind": "session", "percent": "٦٥"}]})
        for minutes in ("NaN", "-Infinity"):
            self.assert_native({"rate_limits": {"session": {
                "percent": "٦٥", "window_minutes": minutes}}})

    def test_native_numeric_chain_executes_once(self):
        count = self.base / "numeric-chain-count"
        count.write_bytes(b"")
        command = f"printf x >> {shlex.quote(str(count))}; printf chained"
        text = '{"rate_limits":{"session":{"percent":"٦_٥"}}}'
        actual = self.cli(text.encode(), "--chain", command, path=self.empty)
        self.assertEqual((0, self.expected(text) + b"  chained", b""),
                         (actual.returncode, actual.stdout, actual.stderr))
        self.assertEqual(b"x", count.read_bytes())

    def test_nonfinite_numeric_exception_does_not_execute_chain(self):
        count = self.base / "nonfinite-chain-count"
        count.write_bytes(b"")
        command = f"printf x >> {shlex.quote(str(count))}"
        for value in ("NaN", "+inf", "-Infinity", "1e999"):
            text = json.dumps({"rate_limits": {"session": {"percent": value}}}).encode()
            expected = self.cli(text, "--chain", command, backend="python")
            actual = self.cli(text, "--chain", command)
            self.assertEqual(1, expected.returncode)
            self.assertEqual((expected.returncode, expected.stdout, expected.stderr),
                             (actual.returncode, actual.stdout, actual.stderr))
            self.assertEqual(127, self.cli(text, "--chain", command, path=self.empty).returncode)
        self.assertEqual(b"", count.read_bytes())

    def test_json_values_and_python_coercion_run_without_python(self):
        values = [True, 42, -0.0, 1e-7, 1e-5, 1e-4, 1e15, 1e16, 1e20, 1e23,
                  1.2345678901234567, 5e-324, sys.float_info.max, 10**80, -10**100,
                  float("nan"), float("inf"), -float("inf"),
                  [None, True, False, "it's", '"quoted"', "\u200b", "한글"],
                  {"b": [1, -0.0, {"nested": "line\n"}], "a": None},
                  {}, [], 0, False, None]
        for alias in ("claude-statusline", "agy-statusline"):
            for value in values:
                payload = {"model": {"display_name": value, "id": "fallback"},
                           "workspace": {"project_dir": value, "current_dir": "/fallback"},
                           "unused": float("nan")}
                text = json.dumps(payload, ensure_ascii=False)
                with self.subTest(alias=alias, value=repr(value)):
                    actual = self.cli(text.encode(), alias=alias, path=self.empty)
                    self.assertEqual((0, self.expected(text), b""),
                                     (actual.returncode, actual.stdout, actual.stderr))
        for value in (10**80, -10**80, 0, -0.0):
            self.assert_native({"rate_limits": {"session": {"percent": value}}})
        for kind in (True, 42, ["session"], {"week": None}):
            self.assert_native({"rate_limits": [{"kind": kind, "percent": 25}]})
        self.assert_native({"rate_limits": {"unknown": {"percent": float("nan")}}})

    def test_coercion_chain_keeps_original_input_once_without_python(self):
        count = self.base / "coercion-chain-count"
        count.write_bytes(b"")
        command = f"printf x >> {shlex.quote(str(count))}; /bin/cat"
        text = '{"model":{"display_name":{"b":1,"a":null,"b":2}},"unused":Infinity}'
        actual = self.cli(text.encode(), "--chain", command, path=self.empty)
        self.assertEqual((0, self.expected(text) + b"  " + text.encode(), b""),
                         (actual.returncode, actual.stdout, actual.stderr))
        self.assertEqual(b"x", count.read_bytes())

    def test_huge_integer_float_overflow_defers_before_chain(self):
        count = self.base / "integer-overflow-chain-count"
        count.write_bytes(b"")
        command = f"printf x >> {shlex.quote(str(count))}"
        for field in ("percent", "window_minutes"):
            text = json.dumps({"rate_limits": {"session": {"percent": 1, field: 10**400}}}).encode()
            expected = self.cli(text, "--chain", command, backend="python")
            actual = self.cli(text, "--chain", command)
            self.assertEqual(1, expected.returncode)
            self.assertEqual((expected.returncode, expected.stdout, expected.stderr),
                             (actual.returncode, actual.stdout, actual.stderr))
            self.assertEqual(127, self.cli(text, "--chain", command, path=self.empty).returncode)
        self.assertEqual(b"", count.read_bytes())

    def test_fallback_retains_raw_pipe_input_before_chain(self):
        counter = self.base / "fallback-count"
        counter.write_bytes(b"")
        command = f"printf x >> {shlex.quote(str(counter))}; /bin/cat"
        # Unsupported coercion/JSON forms retain input; numeric text is native.
        for text in ('{ "model": {"display_name": 42} }\r\n',
                     '{"model":"M","unused":NaN}',
                     '{"rate_limits":{"session":{"percent":"٦٥"}}}',
                     '\u001c{"model":"must not appear"}',
                     '{"model":"\\ud800"}'):
            raw = text.encode()
            expected = self.cli(raw, "--chain", command, backend="python")
            actual = self.cli(raw, "--chain", command)
            self.assertEqual(expected.returncode, actual.returncode)
            self.assertEqual(expected.stdout, actual.stdout)
        self.assertEqual(b"x" * 10, counter.read_bytes())

    def test_help_unsupported_cli_and_custom_root_use_python_before_read(self):
        for args in [("--help",), ("--invalid",), ("--cha", "printf abbreviated")]:
            actual = self.cli(b'{"model":"kept"}', *args)
            reference = self.cli(b'{"model":"kept"}', *args, backend="python")
            self.assertEqual((reference.returncode, reference.stdout, reference.stderr),
                             (actual.returncode, actual.stdout, actual.stderr))
        root = fixture_root(self.base / "custom", "")
        (root / "scripts/claude_statusline.py").write_text("import sys;sys.stdout.write(sys.stdin.read())\n")
        actual = self.cli(b"custom payload", MORU_HOME=str(root))
        self.assertEqual((0, b"custom payload"), (actual.returncode, actual.stdout))
        other_home = self.base / "other-home"
        (other_home / ".moru").mkdir(parents=True)
        (other_home / ".moru/moru-root").write_text(str(root))
        actual = self.cli(b"other home payload", HOME=str(other_home), MORU_HOME="")
        self.assertEqual((0, b"other home payload"), (actual.returncode, actual.stdout))

    def test_chain_receives_universal_newlines_and_keeps_nonzero_stdout(self):
        raw = b'{"model":"M"}\r\n\r'
        command = "/bin/cat; printf '\\r\\n  suffix\\034 '; exit 7"
        for backend in ("auto", "python", "rust"):
            actual = self.cli(raw, "--chain", command, backend=backend)
            self.assertEqual((0, b'M  {"model":"M"}\n\n\n  suffix'),
                             (actual.returncode, actual.stdout))
        actual = self.cli(b'{"model":"M"}', "--chain=printf builtin", path=self.empty)
        self.assertEqual((0, b"M  builtin"), (actual.returncode, actual.stdout))

    def test_decode_failure_does_not_replay_and_honors_soft_fail(self):
        count = self.base / "decode-count"
        count.write_bytes(b"")
        for pipe in ("", " >&2"):
            command = f"printf x >> {shlex.quote(str(count))}; printf '\\377'{pipe}"
            self.assertEqual(1, self.cli(b'{}', "--chain", command).returncode)
            self.assertEqual(0, self.cli(b'{}', "--chain", command, soft="1").returncode)
        self.assertEqual(b"xxxx", count.read_bytes())

    def test_timeout_bounds_inherited_pipes_and_cleans_own_process_group(self):
        pidfile = self.base / "grandchild.pid"
        command = f"/bin/sleep 20 & printf '%s' $! > {shlex.quote(str(pidfile))}; printf chain"
        started = time.monotonic()
        actual = self.cli(b'{"model":"M"}', "--chain", command)
        self.assertLess(time.monotonic() - started, 3.5)
        self.assertEqual((0, b"M"), (actual.returncode, actual.stdout))
        pid = int(pidfile.read_text())
        # A killed orphan may briefly remain a zombie; it must not be sleeping.
        proc = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True)
        self.assertEqual(b"", proc.stderr, "process inspection must be available to verify cleanup")
        self.assertTrue(proc.returncode != 0 or proc.stdout.strip().startswith(b"Z"), proc.stdout)

    def test_normal_empty_malformed_and_large_chain_input(self):
        for raw in (b"", b" \t\n", b"[]", b"null", b"broken"):
            actual = self.cli(raw)
            self.assertEqual((0, b""), (actual.returncode, actual.stdout))
        raw = json.dumps({"model": "M", "unused": "x" * 200000}).encode()
        actual = self.cli(raw, "--chain", "/usr/bin/wc -c")
        self.assertEqual(f"M  {len(raw)}".encode(), actual.stdout)


if __name__ == "__main__":
    unittest.main()
