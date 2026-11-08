"""Observe native report computation, exact Python parity and all-or-nothing decline."""
import collections
import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import moru_overhead_report as report
from native_pretool_support import environment, prepare
from support.native_overhead_report import NativeOverheadReport


class NativeOverheadReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-report-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()
        self.env["PATH"] = str(self.empty)
        self.timings = self.base / "timings.jsonl"

    def row(self, count=1, core=False, **fields):
        return {**dict.fromkeys((*report.NUMERIC, "tok_input"), count),
                "tools": collections.Counter({"Read": count, "Bash": count}),
                "lifecycle_calls": collections.Counter({"start": count}),
                "moru_core": core, "cwd": "private-path-must-not-leave-adapter", **fields}

    def raw(self, operation, payload, **overrides):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--overhead-probe", operation], input=json.dumps(payload).encode(),
            env={**self.env, **overrides}, cwd=self.project, capture_output=True, timeout=8)

    def equivalent(self, expected, actual):
        self.assertIs(type(expected), type(actual), (expected, actual))
        if isinstance(expected, dict):
            self.assertEqual(list(expected), list(actual))
            for key in expected:
                self.equivalent(expected[key], actual[key])
        elif isinstance(expected, list):
            self.assertEqual(len(expected), len(actual))
            for a, b in zip(expected, actual):
                self.equivalent(a, b)
        else:
            self.assertEqual(expected, actual)
            if isinstance(expected, float) and expected == 0:
                self.assertEqual(math.copysign(1, expected), math.copysign(1, actual))

    def expected(self, rows, hooks):
        with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
            return {"all": report.aggregate(rows),
                "moru_core": report.aggregate([r for r in rows if r["moru_core"]]),
                "other_projects": report.aggregate([r for r in rows if not r["moru_core"]]),
                "moru_hook_latency_ms_from_transcripts": {k: report.summarize(v) for k,v in sorted(hooks.items())}}

    def test_native_groups_preserve_types_key_order_and_empty_results(self):
        for rows in ([], [self.row(1, True)], [self.row(0), self.row(1, True), self.row(2)]):
            hooks = {"z": [2.675, -0.0, 0.0, 0.005], "a": [], "한글": [None, 1.0, 2.0]}
            expected = self.expected(rows, hooks)
            before = copy.deepcopy((rows, hooks))
            with patch.dict(os.environ, self.env, clear=True):
                actual = NativeOverheadReport.analyze(rows, hooks)
            self.assertIsNotNone(actual)
            self.equivalent(expected, actual)
            self.assertEqual(before, (rows, hooks))

    def test_random_integer_aggregates_and_finite_float_statistics(self):
        rng = random.Random(7321)
        rows = [self.row(rng.randrange(1000000), bool(i % 2)) for i in range(37)]
        hooks = {f"hook-{i:03}": [rng.uniform(-1e8, 1e8) for _ in range(rng.randrange(1,40))]
                 for i in range(100)}
        hooks.update({f"binary-{i:03}": [math.ldexp(rng.uniform(-1,1),rng.randrange(-300,301))
                       for _ in range(rng.randrange(1,20))] for i in range(100)})
        hooks.update(cancellation=[1e16, 1.0, -1e16],
            large_float=[1e100],
            decimal_ties=[2.675, 2.685, 0.125, -0.125],
            subnormal=[float.fromhex("0x0.0000000000001p-1022"), -0.0],
            double_rounding=[1.0, 1.0, 1e-16], signed_zero=[-0.0, 0.0])
        expected = self.expected(rows, hooks)
        with patch.dict(os.environ, self.env, clear=True):
            actual = NativeOverheadReport.analyze(rows, hooks)
        self.assertIsNotNone(actual)
        self.equivalent(expected, actual)

    def test_counter_ties_limit_and_negative_zero_counts(self):
        names = {f"tool-{i:02}": 3 for i in range(30)}
        rows = [self.row(3, tools=collections.Counter(names),
                         lifecycle_calls=collections.Counter({"zero":0,"negative":-1,"start":3})),
                self.row(-1, tools=collections.Counter({"tool-29":4,"Read":0}))]
        expected = self.expected(rows,{})["all"]
        with patch.dict(os.environ, self.env, clear=True), patch.object(report,"summarize",side_effect=AssertionError("Python replay")):
            actual = report.aggregate(rows)
        self.equivalent(expected,actual)
        self.assertEqual(25,len(actual["tool_calls_by_name_total"]))
        self.assertEqual(["tool-29","tool-00"],list(actual["tool_calls_by_name_total"])[:2])

    def test_timing_lines_coercions_invalid_values_and_empty_key_order(self):
        entries = [None, [], {"hook":"empty"}, {"hook":"empty","timings":[]},
            {"hook":"bad","timings":{"hook_total":"bad"}},
            {"hook":"bool","status":True,"timings":{"a":True,"b":False,"ignored":"10"}},
            {"hook":"numeric","status":"ok","timings":{"hook_total":" ١_٢.٥ "}},
            {"hook":{"b":[True,None],"a":"한글"},"timings":{"hook_total":2.675}},
            {"hook":"sum","timings":{"one":1e16,"two":1.0,"three":-1e16}},
            {"hook":"empty","status":None,"timings":{"hook_total":-0.0}},
            {"hook":"wrong","timings":[1]}]
        self.timings.write_bytes(b"garbage\r" + b"\r\n".join(json.dumps(e,ensure_ascii=False).encode() for e in entries)
            + b'\r{"hook":"replace-\xff","timings":{"hook_total":1}}\n')
        before = self.timings.read_bytes()
        with patch.dict(os.environ,{"MORU_LAUNCHER_BACKEND":"python"}):
            expected = report.read_timings(str(self.timings))
        with patch.dict(os.environ,self.env,clear=True), patch.object(report,"summarize",side_effect=AssertionError("Python timing replay")):
            actual = report.read_timings(str(self.timings))
        self.equivalent(expected,actual)
        self.assertEqual({"n":0},actual["per_hook_ms"]["bad"])
        self.assertEqual(before,self.timings.read_bytes())

    def test_report_connects_native_analysis_and_timings_without_python_statistics(self):
        projects = self.base / "projects" / "p"
        projects.mkdir(parents=True)
        (projects/"session.jsonl").write_text(json.dumps({"type":"assistant","cwd":"/work/core",
            "timestamp":"2026-10-10T00:00:00Z","message":{"id":"a","usage":{"input_tokens":12},"content":[]}})+"\n")
        self.timings.write_text(json.dumps({"hook":"start","timings":{"hook_total":12.5}})+"\n")
        args = report.parse_args(["--projects-dir",str(projects.parent),"--timings",str(self.timings),"--moru-root","/work/core"])
        now = dt.datetime(2026,10,18,tzinfo=dt.timezone.utc)
        with patch.dict(os.environ,{"MORU_LAUNCHER_BACKEND":"python"}):
            expected = report.build_report(args,now)
        with patch.dict(os.environ,self.env,clear=True), patch.object(report,"aggregate",side_effect=AssertionError("Python aggregate")), patch.object(report,"summarize",side_effect=AssertionError("Python statistics")):
            actual = report.build_report(args,now)
        self.equivalent(expected,actual)
        self.assertEqual(report.render_markdown(expected),report.render_markdown(actual))

    def test_missing_timings_native_and_streams_decline_without_consumption(self):
        done = self.raw("timings",{"path":str(self.timings)})
        self.assertEqual((0,b""),(done.returncode,done.stderr))
        self.assertEqual({"records":0,"per_hook_ms":{},"status":{}},json.loads(done.stdout)["result"])
        self.timings.write_text("{}\n")
        link = self.base/"link"
        link.symlink_to(self.timings)
        fifo = self.base/"fifo"
        os.mkfifo(fifo)
        for path in (link,fifo,"/dev/stdin"):
            done = self.raw("timings",{"path":str(path)})
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        with self.timings.open("rb",buffering=0) as handle:
            handle.read(1)
            done = subprocess.run([str(self.entry.with_name("moru-hook-native")),str(self.entry),"--overhead-probe","timings"],
                input=json.dumps({"path":f"/dev/fd/{handle.fileno()}"}).encode(), pass_fds=(handle.fileno(),),
                env=self.env,capture_output=True,timeout=8)
            self.assertEqual(125,done.returncode)
            self.assertEqual(1,os.lseek(handle.fileno(),0,os.SEEK_CUR))

    def test_unsupported_numeric_inputs_and_environment_decline_atomically(self):
        for rows,hooks in (([self.row(10**30)],{}),([self.row(True)],{}),
                ([self.row(1<<53)],{}),([],{"x":[math.inf]}),([],{"x":[10**100]})):
            before = copy.deepcopy(rows)
            with patch.dict(os.environ,self.env,clear=True):
                self.assertIsNone(NativeOverheadReport.analyze(rows,hooks))
            self.assertEqual(before,rows)
        payload = {"sessions":[],"hook_latency":{}}
        for env in ({"MORU_HOME":str(self.project)}, {"PYTHONVERBOSE":"1"}):
            done = self.raw("analyze",payload,**env)
            self.assertEqual((125,b"",b""),(done.returncode,done.stdout,done.stderr))
        self.timings.write_text(json.dumps({"timings":{"hook_total":10**310}}))
        with patch.dict(os.environ,self.env,clear=True):
            self.assertIsNone(NativeOverheadReport.timings(str(self.timings)))
            with self.assertRaises(OverflowError):
                report.read_timings(str(self.timings))

    def test_malformed_native_results_are_not_accepted(self):
        rows = [self.row()]
        before = copy.deepcopy(rows)
        for value in (None,{}, {"records":True,"per_hook_ms":{},"status":{}},
                {"records":1,"per_hook_ms":{"bad":{"n":0}},"status":{"x":1}}):
            with patch("support.native_overhead_report.NativeProbe.request",return_value=value):
                self.assertIsNone(NativeOverheadReport.aggregate(rows))
                self.assertIsNone(NativeOverheadReport.analyze(rows,{}))
                self.assertIsNone(NativeOverheadReport.timings(str(self.timings)))
        self.assertEqual(before,rows)

    def test_large_malformed_response_numbers_decline_and_payload_omits_private_fields(self):
        rows = [self.row()]
        expected = self.expected(rows,{})
        with patch("support.native_overhead_report.NativeProbe.request",return_value=expected["all"]) as request:
            self.assertEqual(expected["all"],NativeOverheadReport.aggregate(rows))
        sent = json.dumps(request.call_args.args[2])
        self.assertNotIn("private-path",sent)
        self.assertNotIn("cwd",sent)
        invalid = copy.deepcopy(expected)
        invalid["all"]["assistant_turns"]["mean"] = 10**310
        for value, operation in ((invalid["all"],lambda: NativeOverheadReport.aggregate(rows)),
                (invalid,lambda: NativeOverheadReport.analyze(rows,{})),
                ({"records":1,"per_hook_ms":{"x":invalid["all"]["assistant_turns"]},"status":{"x":1}},
                 lambda: NativeOverheadReport.timings(str(self.timings)))):
            with patch("support.native_overhead_report.NativeProbe.request",return_value=value):
                self.assertIsNone(operation())


if __name__ == "__main__":
    unittest.main()
