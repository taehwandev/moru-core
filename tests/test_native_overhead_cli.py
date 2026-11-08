"""Observe native report CLI and formatting without Python, with exact reference parity."""
import collections
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import moru_overhead_report as reference
from native_pretool_support import environment, prepare
from support.native_overhead_report import NativeOverheadReport

ROOT=Path(__file__).resolve().parents[1]
STAMP="2026-10-10T00:00:00Z"

def message(identifier,cwd="/work/core",stamp=STAMP):
    return {"type":"assistant","cwd":cwd,"timestamp":stamp,"message":{"id":identifier,
        "usage":{"input_tokens":5,"output_tokens":7},"content":[{"type":"tool_use","id":identifier,
        "name":"Bash","input":{"command":"moru-hook start"}}]}}

class NativeOverheadCliTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="native-report-cli-")
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve()
        self.entry,self.project=prepare(self.base)
        self.env=environment(self.base)
        self.env["COLUMNS"]="80"
        self.empty=self.base/"empty"
        self.empty.mkdir()
        self.projects=self.base/"projects"
        self.projects.mkdir()
        self.timings=self.base/"timings.jsonl"
        self.timings.write_text('{"hook":"start","timings":{"hook_total":2.675}}\n')

    def write(self,path,entries):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("\n".join(json.dumps(e,ensure_ascii=False) for e in entries)+"\n")
        return path

    def args(self,*extra):
        return ["--projects-dir",str(self.projects),"--timings",str(self.timings),
                "--moru-root","/work/core","--until","2026-11-08T00:00:00Z",*extra]

    def invoke(self,args,*,backend="auto",empty=True,**env):
        return subprocess.run([str(self.entry),"overhead-report",*args],capture_output=True,cwd=self.project,
            env={**self.env,"MORU_LAUNCHER_BACKEND":backend,
                 "PATH":str(self.empty) if empty else os.environ.get("PATH",""),**env},timeout=12)

    def parity(self,args):
        done=self.invoke(args)
        self.assertEqual((0,b""),(done.returncode,done.stderr))
        actual=json.loads(done.stdout)
        now=dt.datetime.fromisoformat(actual["generated_at"])
        previous=Path.cwd()
        try:
            os.chdir(self.project)
            with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
                expected=reference.build_report(reference.parse_args(args),now)
        finally:
            os.chdir(previous)
        self.assertEqual(json.dumps(expected,indent=2,ensure_ascii=False)+"\n",done.stdout.decode())
        return actual,expected

    def test_complete_report_collection_order_filtering_and_subagents(self):
        self.write(self.projects/"p/z.jsonl",[message("z"),message("z")])
        self.write(self.projects/"p/a.jsonl",[message("a",cwd="/work/other")])
        self.write(self.projects/"p/hook-only.jsonl",[{"type":"attachment","attachment":{
            "type":"hook_success","hookEvent":"PreToolUse","command":"moru-hook next",
            "durationMs":3.5,"stdout":"Moru policy note /Users/private"}}])
        self.write(self.projects/"p/.hidden.jsonl",[message("hidden")])
        self.write(self.projects/".hidden/a.jsonl",[message("hidden-project")])
        self.write(self.projects/"p/exclude.jsonl",[message("exclude")])
        self.write(self.projects/"p/session/subagents/agent.jsonl",[message("agent")])
        before={p:p.read_bytes() for p in self.projects.rglob("*.jsonl")}
        actual,_=self.parity(self.args("--include-subagents","--exclude-session","exclude"))
        self.assertEqual(3,actual["all"]["sessions"])
        self.assertEqual(2,actual["moru_core"]["sessions"])
        self.assertEqual(3.5,actual["moru_hook_latency_ms_from_transcripts"]["PreToolUse:next"]["mean"])
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_default_now_window_and_calendar_offset_boundaries(self):
        args=["--projects-dir",str(self.projects),"--timings",str(self.base/"missing"),"--days","1"]
        actual,_=self.parity(args)
        generated=dt.datetime.fromisoformat(actual["generated_at"])
        self.assertEqual(generated,dt.datetime.fromisoformat(actual["window"]["until"]))
        self.assertEqual(generated-dt.timedelta(days=1),dt.datetime.fromisoformat(actual["window"]["since"]))
        for until,days in (("2024-03-01T03:04:05.123+09:00","1"),("2100-03-01T00:00:00Z","1"),
                           ("2000-02-28","-1"),("0001-01-01","0")):
            self.parity([*args,"--until",until,"--days",days])

    def test_mtime_microsecond_boundaries_match_python(self):
        for epoch in (0,1791504000):
            stamp=dt.datetime.fromtimestamp(epoch,dt.timezone.utc).isoformat()
            for i,delta in enumerate((-1001,-999,-501,-500,-499,-1,0,1,499,500,501,999,1001)):
                path=self.write(self.projects/f"p/m{i}.jsonl",[message(str(i),stamp=stamp)])
                os.utime(path,ns=(epoch*10**9+delta,epoch*10**9+delta))
            self.parity(self.args("--since",stamp))

    def test_empty_projects_path_collects_current_directory(self):
        self.write(self.project/"p/a.jsonl",[message("cwd")])
        actual,_=self.parity(self.args("--projects-dir",""))
        self.assertEqual(1,actual["all"]["sessions"])

    def test_oversized_columns_defers_before_help_output(self):
        for width in ("9223372036854775808","-9223372036854775809"):
            native=self.invoke(["--help"],empty=False,COLUMNS=width)
            python=self.invoke(["--help"],backend="python",empty=False,COLUMNS=width)
            self.assertEqual((python.returncode,python.stdout,python.stderr),
                             (native.returncode,native.stdout,native.stderr))
            native=self.invoke(["--help"],COLUMNS=width)
            self.assertEqual((127,b""),(native.returncode,native.stdout))

    def test_help_and_argument_errors_are_native_and_identical(self):
        cases=[["--help"],["-h"],["--m","--help"],["--days","bad"],
               ["--include-subagents=yes"],["--min-turns"],["--unknown"],["--","value"]]
        for args in cases:
            with self.subTest(args=args):
                native=self.invoke(args)
                python=self.invoke(args,backend="python",empty=False)
                self.assertEqual((python.returncode,python.stdout,python.stderr),
                                 (native.returncode,native.stdout,native.stderr))
        self.parity(self.args("--days","٠_٣٠","--min-turns","+0"))

    def test_json_markdown_formatters_run_without_python(self):
        self.write(self.projects/"p/a.jsonl",[message("a")])
        actual,expected=self.parity(self.args())
        with patch.dict(os.environ,{**self.env,"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            markdown=reference.render_markdown(expected)
        with patch.dict(os.environ,{**self.env,"PATH":str(self.empty)},clear=True):
            native_json=NativeOverheadReport.render(actual,"json")
            native_markdown=NativeOverheadReport.render(actual,"markdown")
        self.assertEqual(json.dumps(expected,indent=2,ensure_ascii=False),native_json)
        self.assertEqual(markdown,native_markdown)

    def test_output_files_use_legacy_once_and_keep_partial_failure_order(self):
        self.write(self.projects/"p/a.jsonl",[message("a")])
        wrapper=self.base/"bin"
        wrapper.mkdir()
        count=self.base/"python-count"
        executable=wrapper/"python3"
        executable.write_text(f'#!/bin/sh\nprintf x >> "{count}"\nexec "{sys.executable}" "$@"\n')
        executable.chmod(0o700)
        out,md=self.base/"report.json",self.base/"report.md"
        done=self.invoke(self.args("--out",str(out),"--md",str(md)),empty=False,
                         PATH=str(wrapper)+os.pathsep+os.environ.get("PATH",""))
        self.assertEqual((0,b"",b""),(done.returncode,done.stdout,done.stderr))
        self.assertEqual("x",count.read_text())
        data=json.loads(out.read_text())
        with patch.dict(os.environ,{"MORU_LAUNCHER_BACKEND":"python"}):
            self.assertEqual(reference.render_markdown(data),md.read_text())
        count.write_text("")
        missing=self.base/"missing/report.md"
        done=self.invoke(self.args("--out",str(out),"--md",str(missing)),empty=False,
                         PATH=str(wrapper)+os.pathsep+os.environ.get("PATH",""))
        self.assertEqual(1,done.returncode)
        self.assertEqual(b"",done.stdout)
        self.assertIn(b"FileNotFoundError",done.stderr)
        self.assertTrue(json.loads(out.read_text())["all"]["sessions"])
        self.assertEqual("x",count.read_text())

    def test_unsupported_regular_inputs_fall_back_once_before_stdout(self):
        path=self.write(self.projects/"p/a.jsonl",[message("a")])
        link=self.projects/"p/link.jsonl"
        link.symlink_to(path)
        native=self.invoke(self.args(),empty=False)
        self.assertEqual((0,b""),(native.returncode,native.stderr))
        self.assertEqual(2,json.loads(native.stdout)["all"]["sessions"])
        native=self.invoke(self.args())
        self.assertEqual(127,native.returncode)
        self.assertEqual(b"",native.stdout)


if __name__=="__main__":
    unittest.main()
