"""Actual callback conformance and proof that native queries do not start Python."""
from __future__ import annotations

import json
import os
import py_compile
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from native_launcher_support import copied_build_root
from native_pretool_support import PROJECT, environment, invoke, prepare, request, result

ALIASES = ("claude-pretool-gate", "codex-pretool-gate")


class NativePretoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-pretool-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare(self.base)
        self.empty_path = self.base / "empty-path"
        self.empty_path.mkdir()

    def same(self, alias, payload, **overrides):
        reference = invoke(self.launcher, self.base, self.project, alias, payload, backend="python", **overrides)
        native = invoke(self.launcher, self.base, self.project, alias, payload, **overrides)
        self.assertEqual(result(reference), result(native))
        return native

    def test_plain_queries_run_with_no_python_or_git_on_path(self):
        other = self.base / "other-query"
        other.mkdir()
        commands = ["pwd", "git status --short", "git status --porcelain", "git diff --stat",
                    "git diff --cached --name-only", "git diff --check", "git rev-parse HEAD",
                    "git branch --show-current", "git rev-parse --show-toplevel",
                    "git -C " + str(other) + " status --short"]
        for alias in ALIASES:
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    payload = request(self.project, command)
                    self.assertEqual((0, b"", b""), result(self.same(alias, payload)))
                    done = invoke(self.launcher, self.base, self.project, alias, payload, PATH=str(self.empty_path))
                    self.assertEqual((0, b"", b""), result(done))

    def test_codex_realistic_transcript_shapes_still_avoid_python(self):
        work = self.base / "other-workdir"
        work.mkdir()
        records = [
            {"type": "function_call", "arguments": json.dumps({"cmd": "pwd", "workdir": str(work)})},
            {"type": "custom_tool_call", "input": 'await tools.exec_command({cmd:"pwd",workdir:"' + str(work) + '"})'},
        ]
        for record in records:
            with self.subTest(record=record["type"]):
                transcript = self.base / "synthetic.jsonl"
                transcript.write_text(json.dumps({"payload": record}) + "\n")
                payload = request(self.project, "pwd", transcript_path=str(transcript), hook_event_name="PreToolUse")
                self.assertEqual((0, b"", b""), result(self.same(ALIASES[1], payload)))
                done = invoke(self.launcher, self.base, self.project, ALIASES[1], payload, PATH=str(self.empty_path))
                self.assertEqual((0, b"", b""), result(done))

    def test_codex_file_operand_only_in_recorded_workdir_avoids_python(self):
        work=self.project/"work only 한글";work.mkdir()
        (work/"only-there.txt").write_text("synthetic\n")
        command="cat only-there.txt"
        records=[{"type":"function_call","arguments":json.dumps({"cmd":command,"workdir":str(work)})},
                 {"type":"custom_tool_call","input":'tools.exec_command({cmd:"'+command+'",workdir:"'+str(work)+'"})'}]
        transcript=self.base/"workdir-only.jsonl"
        for record in records:
            with self.subTest(record=record["type"]):
                transcript.write_text(json.dumps({"payload":record})+"\n")
                payload=request(self.project,command,transcript_path=str(transcript))
                self.assertEqual((0,b"",b""),result(self.same(ALIASES[1],payload)))
                self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path))))

    def test_codex_exact_latest_and_ambiguous_commands_use_reference_scope(self):
        (self.project/"here.txt").write_text("here\n")
        other=self.base/"other matching cwd";other.mkdir()
        second=self.base/"second matching cwd";second.mkdir()
        command="cat here.txt"
        calls=lambda path,cmd=command:'tools.exec_command({cmd:"'+cmd+'",workdir:"'+str(path)+'"})'
        cases=[{"type":"function_call","arguments":json.dumps({"cmd":"pwd","workdir":str(other)})},
            {"type":"custom_tool_call","input":calls(other)+";"+calls(second)},
            {"type":"custom_tool_call","input":calls(other)+";tools.exec_command({cmd:\"cat here.txt\"})"},
            {"type":"custom_tool_call","input":'tools.exec_command({cmd:"cat here.txt",workdir:"relative"})'}]
        transcript=self.base/"scope-cases.jsonl"
        for record in cases:
            with self.subTest(record=record):
                transcript.write_text(json.dumps({"payload":record})+"\n")
                payload=request(self.project,command,transcript_path=str(transcript))
                self.same(ALIASES[1],payload)
                self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path))))
        older={"payload":{"type":"custom_tool_call","input":calls(other)}}
        newest={"payload":{"type":"custom_tool_call","input":calls(second,"pwd")}}
        transcript.write_text(json.dumps(older)+"\n"+json.dumps(newest)+"\n")
        self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[1],
            request(self.project,command,transcript_path=str(transcript)),PATH=str(self.empty_path))))

    def test_codex_duplicate_matching_workdirs_and_cut_utf8_prefix_still_normalize(self):
        work=self.project/"work for latest";work.mkdir();(work/"only.txt").write_text("data")
        command="cat only.txt"
        code='tools.exec_command({cmd:"'+command+'",workdir:"'+str(work)+'"});'
        line=json.dumps({"payload":{"type":"custom_tool_call","input":code+code}}).encode()
        transcript=self.base/"large-scope.jsonl"
        padding=512*1024+33-38-len(line)
        transcript.write_bytes(b"x"*32+b"\xe3\x81\x82\n"+b"x"*padding+b"\n"+line+b"\n")
        payload=request(self.project,command,transcript_path=str(transcript))
        self.same(ALIASES[1],payload)
        self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path))))

    def test_codex_raw_json_control_values_replay_without_selecting_workdir(self):
        work=self.project/"raw\ttab";work.mkdir();(work/"only.txt").write_text("data")
        plain=self.project/"plain work";plain.mkdir();(plain/"only.txt").write_text("data")
        transcript=self.base/"raw-control.jsonl"
        for command,directory in (("cat\tonly.txt",plain),("cat only.txt",work)):
            code='tools.exec_command({cmd:"'+command+'",workdir:"'+str(directory)+'"})'
            transcript.write_text(json.dumps({"payload":{"type":"custom_tool_call","input":code}})+"\n")
            payload=request(self.project,command,transcript_path=str(transcript))
            self.same(ALIASES[1],payload)
            self.assertEqual(127,invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path)).returncode)
            transcript.write_text(json.dumps({"payload":{"type":"function_call",
                "arguments":json.dumps({"cmd":command,"workdir":str(directory)})}})+"\n")
            self.same(ALIASES[1],payload)
            self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path))))

    def test_claude_does_not_adopt_codex_transcript_workdir(self):
        (self.project/"here.txt").write_text("here")
        work=self.base/"claude ignored";work.mkdir();(work/"cat").write_text("shadow")
        transcript=self.base/"claude-isolation.jsonl"
        transcript.write_text(json.dumps({"payload":{"type":"function_call",
            "arguments":json.dumps({"cmd":"cat here.txt","workdir":str(work)})}})+"\n")
        payload=request(self.project,"cat here.txt",transcript_path=str(transcript))
        self.same(ALIASES[0],payload)
        self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,ALIASES[0],payload,PATH=str(self.empty_path))))

    def test_cross_project_mutation_replays_to_selected_read_only_evidence(self):
        from test_claude_pretool_gate import _opt_in_project, _write_preflight
        from agent_block_lessons import block_lesson_id
        session="native-cwd-authority"
        with patch.dict(os.environ,environment(self.base),clear=True):
            other=_opt_in_project(self.base/"authority-b")
            for project in (self.project,other):
                (project/".gitignore").write_text(".moru/\n")
            subprocess.run(["git","init","-q","-b","main",str(other)],
                           check=True,capture_output=True,timeout=5)
            _write_preflight(self.project,session,command="bugfix",runtime="codex")
            _write_preflight(other,session,command="analysis",read_only=True,runtime="codex")
        transcript=self.base/"authority.jsonl"
        transcript.write_text(json.dumps({"payload":{"type":"function_call",
            "arguments":json.dumps({"cmd":"touch blocked.txt","workdir":str(other)})}})+"\n")
        payload=request(self.project,"touch blocked.txt",session_id=session,transcript_path=str(transcript))
        actual=invoke(self.launcher,self.base,self.project,ALIASES[1],payload)
        lesson=self.base/"state/lessons/inbox"/(block_lesson_id("pretool_gate","read_only_run_mutation")+".json")
        self.assertTrue(lesson.is_file(),actual)
        recorded=json.loads(lesson.read_text());self.assertEqual("read_only_run_mutation",recorded["root_cause"])
        self.assertEqual("pretool_gate/read_only_run_mutation",recorded["block_signature"])
        self.assertEqual("deny",json.loads(actual.stdout)["hookSpecificOutput"]["permissionDecision"])
        expected=invoke(self.launcher,self.base,self.project,ALIASES[1],payload,backend="python")
        self.assertEqual(result(expected),result(actual))
        self.assertEqual(127,invoke(self.launcher,self.base,self.project,ALIASES[1],payload,PATH=str(self.empty_path)).returncode)
        self.assertFalse((self.project/"blocked.txt").exists());self.assertFalse((other/"blocked.txt").exists())

    def test_rejected_neighbors_replay_exact_payload_to_policy(self):
        commands = ["touch never-executed", "git diff --stat --output=never-executed", "pwd; touch never-executed",
                    "git status --short > never-executed", "git -c x.y=z status --short", "git status '--short'",
                    "git status --short\n", "git status --short | cat", "claude -p task"]
        for alias in ALIASES:
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    self.same(alias, request(self.project, command))
        self.assertFalse((self.project / "never-executed").exists())

    def test_malformed_metadata_and_json_keep_legacy_errors(self):
        cases = [b"", b"not-json", b"[]", b"{\"tool_input\":null}", request(self.project, cwd=42),
                 request(self.project, cwd="/missing-pretool-dir"), request(self.project, transcript_path="\0")]
        for alias in ALIASES:
            for payload in cases:
                with self.subTest(alias=alias, payload=repr(payload)[:60]):
                    self.same(alias, payload)

    def test_codex_invalid_transcript_records_keep_visible_failure(self):
        transcript = self.base / "synthetic.jsonl"
        for line in ['["function_call"]', '{"payload":{"type":"function_call","arguments":"bad"}}',
                     '{"payload":{"type":"custom_tool_call","input":"cmd:\\"pwd\\",workdir:\\"\\\\u0000\\""}}']:
            with self.subTest(line=line):
                transcript.write_text(line + "\n")
                self.same(ALIASES[1], request(self.project, "pwd", transcript_path=str(transcript)))

    def test_symlink_loop_preserves_legacy_result_and_forces_fallback(self):
        (self.project / "git").symlink_to("git")
        for alias in ALIASES:
            self.same(alias, request(self.project))
            done = invoke(self.launcher, self.base, self.project, alias, request(self.project), PATH=str(self.empty_path))
            self.assertNotEqual(0, done.returncode)

    def test_environment_override_keeps_python_selection(self):
        done = invoke(self.launcher, self.base, self.project, ALIASES[0], request(self.project),
                      PYTHONPATH=str(PROJECT / "scripts"), PATH=str(self.empty_path))
        self.assertNotEqual(0, done.returncode)

    def test_invalid_state_override_keeps_visible_legacy_failure(self):
        for alias in ALIASES:
            done = self.same(alias, request(self.project),
                             MORU_STATE_HOME="~__moru_missing_synthetic_user_9a315__/state")
            unavailable = invoke(self.launcher, self.base, self.project, alias, request(self.project),
                                 MORU_STATE_HOME="~__moru_missing_synthetic_user_9a315__/state", PATH=str(self.empty_path))
            self.assertNotEqual(0, unavailable.returncode)

    def test_changed_policy_source_forces_python(self):
        source = copied_build_root(self.base / "source")
        shutil.copytree(PROJECT / "scripts", source / "scripts", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "index.md"):
            shutil.copy2(PROJECT / name, source / name)
        isolated = self.base / "isolated"
        isolated.mkdir()
        launcher, project = prepare(isolated, source)
        payload = request(project)
        self.assertEqual((0, b"", b""), result(invoke(launcher, isolated, project, ALIASES[0], payload,
                                                      source=source, PATH=str(self.empty_path))))
        policy = source / "scripts/claude_bash_git.py"
        policy.write_bytes(policy.read_bytes() + b"\n# changed contract\n")
        spy_dir = self.base / "spy"
        spy_dir.mkdir()
        marker = self.base / "python-started"
        spy = spy_dir / "python3"
        spy.write_text("#!/bin/sh\nprintf x >> " + shlex.quote(str(marker)) + "\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
        spy.chmod(0o755)
        done = invoke(launcher, isolated, project, ALIASES[0], payload, source=source,
                      PATH=str(spy_dir) + os.pathsep + os.environ["PATH"])
        self.assertEqual((0, b"", b""), result(done))
        self.assertEqual("x", marker.read_text())
        policy.write_bytes(policy.read_bytes().split(b"\n# changed contract\n")[0])
        shadow = source / "scripts/typing.py"
        shadow.write_text("raise RuntimeError('synthetic module shadow')\n")
        reference = invoke(launcher, isolated, project, ALIASES[0], payload, source=source, backend="python")
        native = invoke(launcher, isolated, project, ALIASES[0], payload, source=source)
        self.assertEqual(result(reference), result(native))

        bytecode = source / "scripts/typing.pyc"
        py_compile.compile(str(shadow), cfile=str(bytecode), doraise=True)
        shadow.unlink()
        reference = invoke(launcher, isolated, project, ALIASES[0], payload, source=source, backend="python")
        native = invoke(launcher, isolated, project, ALIASES[0], payload, source=source)
        self.assertEqual(result(reference), result(native))
        unavailable = invoke(launcher, isolated, project, ALIASES[0], payload, source=source, PATH=str(self.empty_path))
        self.assertNotEqual(0, unavailable.returncode)
        bytecode.unlink()
        (source / "index.md").unlink()
        reference = invoke(launcher, isolated, project, ALIASES[0], payload, source=source, backend="python")
        native = invoke(launcher, isolated, project, ALIASES[0], payload, source=source)
        self.assertEqual(result(reference), result(native))

    def test_developer_caches_do_not_disable_native_queries(self):
        source = copied_build_root(self.base / "cache-source")
        shutil.copytree(PROJECT / "scripts", source / "scripts", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "index.md"):
            shutil.copy2(PROJECT / name, source / name)
        existing = source / "scripts/.pytest_cache/v/cache/existing.json"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text('{"existing":true}')
        for name in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
            directory = source / "scripts" / name / "v/cache"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "nodeids.json").write_text('["synthetic"]')
        isolated = self.base / "cache-home"
        isolated.mkdir()
        launcher, project = prepare(isolated, source)
        for alias in ALIASES:
            done = invoke(launcher, isolated, project, alias, request(project),
                          source=source, PATH=str(self.empty_path))
            self.assertEqual((0, b"", b""), result(done))
        self.assertEqual('{"existing":true}', existing.read_text())
        cache = source / "scripts/.pytest_cache"
        shutil.rmtree(cache)
        cache.symlink_to(self.base, target_is_directory=True)
        for alias in ALIASES:
            done = invoke(launcher, isolated, project, alias, request(project),
                          source=source, PATH=str(self.empty_path))
            self.assertNotEqual(0, done.returncode)
        cache.unlink()
        (source / "scripts/unrecognized-cache").mkdir()
        for alias in ALIASES:
            done = invoke(launcher, isolated, project, alias, request(project),
                          source=source, PATH=str(self.empty_path))
            self.assertNotEqual(0, done.returncode)


if __name__ == "__main__":
    unittest.main()
