"""Observe exact native text merging through the real temporary setup path."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from native_launcher_support import copied_build_root, install
from native_pretool_support import environment
from support import codex_statusline_setup as source
from support.native_probe_transport import NativeProbe

BASELINE = "159bd28e87778fb144d5af24cb5e4784bf3f53af"


class NativeCodexStatuslineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="moru-statusline-test-")
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name).resolve()
        home = cls.base / "home"
        home.mkdir()
        with patch.dict(os.environ, environment(cls.base), clear=True):
            install(home)
        empty = cls.base / "empty"
        empty.mkdir()
        cls.env = {**environment(cls.base), "PATH": str(empty)}
        cls.launcher = home / ".moru/bin/moru-hook"
        assert cls.launcher.with_name("moru-hook-native").is_file(), "source-bound debug fixture required"
        original = subprocess.run(["git", "show", BASELINE + ":scripts/support/codex_statusline_setup.py"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, check=True).stdout
        cls.oracle = types.ModuleType("original_statusline")
        exec(compile(original, "original_statusline.py", "exec"), cls.oracle.__dict__)

    def call(self, text, *, dry=True, native=True, reference=False):
        with tempfile.TemporaryDirectory(dir=self.base) as directory:
            path = Path(directory) / "config.toml"
            path.write_text(text, encoding="utf-8")
            before = path.read_bytes()
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "auto" if native else "python"}, clear=True):
                result = (self.oracle if reference else source).merge_codex_status_line(path, dry)
            return result, path.read_bytes(), before

    def profile(self, action):
        codes = {fn.__code__ for fn, _, _ in source._NATIVE_PROFILE.values()}
        calls = []
        def observe(frame, event, arg):
            if event == "call" and frame.f_code in codes:
                calls.append(frame.f_code.co_name)
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            result = action()
        finally:
            sys.setprofile(previous)
        return result, calls

    def test_real_setup_uses_one_native_merge_without_python_scanner_or_renderer(self):
        text = '[tui]\nstatus_line = [\n  "한글" # keep\n]\n'
        with patch.object(NativeProbe, "request", wraps=NativeProbe.request) as request:
            actual, calls = self.profile(lambda: self.call(text, dry=False))
        self.assertEqual(self.call(text, dry=False, reference=True), actual)
        self.assertEqual([], calls)
        self.assertEqual(1, request.call_count)
        self.assertEqual(("--setup-probe", "codex-status-line"), request.call_args.args[:2])

    def test_negative_control_detects_reference_replay(self):
        text = '[tui]\nstatus_line=[]\n'
        actual, calls = self.profile(lambda: self.call(text, dry=False, native=False))
        self.assertEqual(self.call(text, dry=False, reference=True), actual)
        self.assertIn("_merge_text_reference", calls)
        self.assertIn("_status_line_assignment", calls)

    def test_original_source_parity_for_comments_tables_conflicts_and_unicode(self):
        cases = ["", "# only", "[tui]", "[tui]\n", "[tui]\r\n", "tui={}\n", "[tui]\n[tui]\n",
            "[tui.child]\nx=7\n", '[other]\nstatus_line=[]\n', "tui.status_line=[]\n[other]\n",
            '[tui]\nstatus_line = ["five-hour-limit", "weekly-limit"] # keep\n',
            '[tui]\nstatus_line=["x" # comment\n]\n', '[tui]\nstatus_line=["x",\n # only\n ]\n',
            '[tui]\nstatus_line=["x",]\n', '[tui]\nstatus_line=["x" "y"]\n',
            '[tui]\nstatus_line=[1]\n', '[tui]\nstatus_line=[[["x"]]]\n',
            '[tui]\nstatus_line=["""x"""]\n', "[tui]\nstatus_line=['''x''']\n",
            '[tui]\nstatus_line=["x\\\"#]"]\n', '[tui]\nstatus_line=["x", #comment]',
            '[tui]\nstatus_line=["x"]\nstatus_line=[]\n', "tui.status_line=[]\ntui.status_line=[]\n",
            "[\u1c00]\nx=1\n", '[\x1ctui\x1f]\nstatus_line=\x1c[\u00a0"한글",\n]\n',
            '[tui]\nstatus_line=[\n\u2028  "한글",\u2029# note\n]\n',
            '[tui]\nstatus_line=["five\\u002dhour-limit"]\n', "[[tui]]\n", "[tui] junk\n",
            '[tui]\nstatus_line=["x\n\n', '[tui]\nstatus_line=[#empty\n]\n']
        for text in cases:
            for dry in (True, False):
                with self.subTest(text=text, dry=dry):
                    self.assertEqual(self.call(text, dry=dry, reference=True), self.call(text, dry=dry))

    def test_seeded_original_source_text_oracle(self):
        rng = random.Random(187023)
        rows = ["\"x\"", "'한글'", "\"five-hour-limit\"", "\"weekly-limit\"", '"a\\\"#]"', '""', '7', "'unterminated"]
        for index in range(160):
            body = rng.choice([", ", ",\n  ", " #comment\n", " \t"]).join(rng.choices(rows, k=rng.randrange(5)))
            text = rng.choice(["[tui]\n", "tui.status_line = []\n[tui]\n", "[other]\n", ""]) + "status_line = [" + body + "]" + rng.choice(["", "\n", "\n[tui.next]\nx=1\n"])
            with self.subTest(index=index):
                self.assertEqual(self.call(text, dry=False, reference=True), self.call(text, dry=False))

    def test_dry_run_and_ok_missing_never_write_or_create_parents(self):
        for text in ("", '[tui]\nstatus_line=[1]\n', '[tui]\nstatus_line=["five-hour-limit","weekly-limit"]'):
            with self.subTest(text=text):
                result, after, before = self.call(text)
                self.assertEqual(before, after)
        target = self.base / "missing parent" / "config.toml"
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual("would_update", source.merge_codex_status_line(target, True))
        self.assertFalse(target.parent.exists())

    def test_custom_callbacks_constants_and_json_rendering_defer(self):
        cases = [("QUOTA_STATUS_ITEMS", ("new-quota",)), ("DEFAULT_STATUS_ITEMS", ("custom",)),
            ("_insert_status_line", lambda text, items: "custom\n")]
        for name, value in cases:
            with patch.object(source, name, value), patch.object(NativeProbe, "request", side_effect=AssertionError("custom native")):
                self.assertEqual(self.call("", dry=False, native=False), self.call("", dry=False))
        with patch.object(source.json, "dumps", lambda value: "'custom'"):
            self.assertEqual(self.call("", dry=False, native=False), self.call("", dry=False))
        with patch.object(source.re, "search", lambda *args: True):
            self.assertEqual(self.call("", native=False), self.call(""))
        function = source._quoted_items
        original = function.__code__
        def changed(body):
            return None
        try:
            function.__code__ = changed.__code__
            self.assertEqual(self.call('[tui]\nstatus_line=[]', native=False), self.call('[tui]\nstatus_line=[]'))
        finally:
            function.__code__ = original

    def test_bad_or_unavailable_protocol_falls_back_once_without_extra_writes(self):
        text = "[tui]\nstatus_line=[]\n"
        for packet in (None, {}, {"status": "ok", "text": "wrong"}, {"status": "changed", "text": text},
                       {"status": "installed", "text": text}, {"status": "missing", "text": text, "extra": 1}):
            with self.subTest(packet=packet), patch.object(NativeProbe, "request", return_value=packet) as request:
                self.assertEqual(self.call(text, dry=False, reference=True), self.call(text, dry=False))
                self.assertEqual(1, request.call_count)

    def test_private_protocol_rejects_schema_and_changed_source_without_python(self):
        executable = self.launcher.with_name("moru-hook-native")
        for payload in ({}, {"text": 3}, {"text": "", "extra": 1}, {"text": "\ud800"}):
            done = subprocess.run([str(executable), str(self.launcher), "--setup-probe", "codex-status-line"],
                env=self.env, input=json.dumps(payload).encode(), capture_output=True, timeout=10)
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        done = subprocess.run([str(executable), str(self.launcher), "--setup-probe", "unknown"],
            env={**self.env, "MORU_HOOK_SOFT_FAIL": "1"}, input=b'{}', capture_output=True, timeout=10)
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        copied = copied_build_root(self.base / "changed source")
        other_home = self.base / "other home"
        other_home.mkdir()
        other_env = {**self.env, "HOME": str(other_home), "MORU_HOME": str(copied)}
        with patch.dict(os.environ, other_env, clear=True):
            install(other_home, copied)
        changed = copied / "scripts/support/codex_statusline_setup.py"
        changed.write_bytes(changed.read_bytes() + b"\n# mismatched source\n")
        entry = other_home / ".moru/bin/moru-hook"
        done = subprocess.run([str(entry.with_name("moru-hook-native")), str(entry), "--setup-probe", "codex-status-line"],
            env=other_env, input=b'{"text":""}', capture_output=True, timeout=10)
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))

    def test_missing_json_binding_keeps_original_no_render_success(self):
        text = '[tui]\nstatus_line=["five-hour-limit","weekly-limit"]'
        original = source.json
        del source.json
        try:
            self.assertEqual("ok", self.call(text)[0])
        finally:
            source.json = original

    def test_file_errors_precede_any_native_request(self):
        target = self.base / "invalid utf8.toml"
        target.write_bytes(b'\xff')
        with patch.object(NativeProbe, "request", side_effect=AssertionError("read failed")):
            for module in (self.oracle, source):
                with self.assertRaises(UnicodeDecodeError):
                    module.merge_codex_status_line(target, False)
        target.unlink()
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(Path, "write_text", side_effect=PermissionError("synthetic write denial")):
            with self.assertRaisesRegex(PermissionError, "synthetic write denial"):
                source.merge_codex_status_line(target, False)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
