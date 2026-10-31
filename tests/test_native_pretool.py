"""Actual callback conformance and proof that native queries do not start Python."""
from __future__ import annotations

import json
import os
import py_compile
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

from native_launcher_support import copied_build_root
from native_pretool_support import PROJECT, invoke, prepare, request, result

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


if __name__ == "__main__":
    unittest.main()
