"""Real native report formatting preserves lossless Python numbers and refusals."""
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import moru_overhead_report as reference
from native_pretool_support import environment, prepare
from support.native_overhead_report import NativeOverheadReport


class NativeOverheadFormatTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-report-format-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        (self.base / "empty").mkdir()
        self.env["PATH"] = str(self.base / "empty")

    def raw(self, payload):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--overhead-probe", "format"], input=json.dumps(payload).encode(),
            env=self.env, cwd=self.project, capture_output=True, timeout=8)

    def render(self, report, style):
        with patch.dict(os.environ, self.env, clear=True):
            result = NativeOverheadReport.render(report, style)
        self.assertIsNotNone(result, "native formatter must execute with no Python on PATH")
        return result

    def report(self):
        return {"generated_at": "now", "window": {"since": "then", "until": "now"},
                "all": {"sessions": 10**100}, "moru_core": {"sessions": True},
                "other_projects": {"sessions": 0}, "moru_hook_latency_ms_from_transcripts": {},
                "top_policy_notes": [], "top_hook_denials": []}

    def test_json_preserves_arbitrary_integers_nonfinite_and_nested_order(self):
        value = {"한😀\x7f": [10**100, -(10**100), 2**64, 2**63-1, -0.0, 1.0,
                    math.nan, math.inf, -math.inf, 1e-5, True, None],
                 "last": {"empty": [], "float": 1e16}}
        before = json.dumps(value)
        self.assertEqual(json.dumps(value, ensure_ascii=False, indent=2), self.render(value, "json"))
        self.assertEqual(before, json.dumps(value))

    def test_markdown_keeps_python_display_and_compact_json_number_spelling(self):
        report = self.report()
        report["all"].update(assistant_turns={"n": True, "median": math.nan, "p90": math.inf},
            lifecycle_share_of_tool_calls_pct=-math.inf,
            injected_tokens_vs_new_input_pct=[True, None, "한"],
            lifecycle_calls_by_subcommand_total={"한😀\x7f": 10**100, "float": math.inf})
        report["moru_hook_latency_ms_from_transcripts"] = {
            "hook": {"n": 10**100, "median": -0.0, "p90": -math.inf}}
        report["top_policy_notes"] = [{"count": 10**100, "message": "synthetic"}]
        before = json.dumps(report)
        with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
            expected = reference.render_markdown(report)
        self.assertEqual(expected, self.render(report, "markdown"))
        self.assertEqual(before, json.dumps(report))

    def test_legacy_probe_and_new_envelope_both_render_without_python(self):
        value = [10**100, math.nan, math.inf, -math.inf, -0.0]
        expected = json.dumps(value, indent=2)
        for payload in ({"report": value, "format": "json"},
                        {"report_json": json.dumps(value), "format": "json"}):
            done = self.raw(payload)
            self.assertEqual((0, b""), (done.returncode, done.stderr))
            self.assertEqual(expected, json.loads(done.stdout)["result"]["text"])

    def test_malformed_envelopes_and_unsupported_depth_decline_silently(self):
        for payload in ({"report_json": 1, "format": "json"},
                        {"report_json": "[1,", "format": "json"},
                        {"report_json": '"\\ud800"', "format": "json"},
                        {"report_json": "["*130+"0"+"]"*130, "format": "json"},
                        {"report_json": "{}", "format": "markdown"},
                        {"report_json": "{}", "format": "unknown"}):
            done = self.raw(payload)
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))

    def test_adapter_rejects_custom_objects_cycles_and_forced_python(self):
        class Custom(dict):
            def items(self):
                raise AssertionError("custom serialization side effect")

        cycle = []
        cycle.append(cycle)
        with patch.dict(os.environ, self.env, clear=True):
            for report in (Custom(), {"nested": Custom()}, cycle):
                self.assertIsNone(NativeOverheadReport.render(report, "json"))
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            self.assertIsNone(NativeOverheadReport.render({"number": 10**100}, "json"))


if __name__ == "__main__":
    unittest.main()
