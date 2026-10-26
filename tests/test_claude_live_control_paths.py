"""Live controls read their trusted program and still govern the project they act on."""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claude_bash_readonly import bash_command_kind, bash_invocation, read_only_path_token_indices
from tests import test_claude_pretool_gate as gate_tests
from tests.test_claude_pretool_gate import (
    _decide, _decision_of, _reason, _write_preflight,
)
from support.global_state import STATE_HOME_ENV


class LiveControlPathTests(unittest.TestCase):
    def command(self, project, operation="start", *options, bytecode_flag=True):
        prefix = ["python3", "-B"] if bytecode_flag else ["python3"]
        return shlex.join([*prefix, str(ROOT / "scripts/live_device.py"),
                           operation, "--project", str(project), *options])

    def targets(self, command):
        _, tokens, _ = bash_invocation({"tool_input": {"command": command}}, ROOT)
        reads = read_only_path_token_indices(tokens, ROOT)
        return [word for index, word in enumerate(tokens) if index not in reads]

    def test_only_explicit_project_remains_a_write_operand(self):
        for operation, options in (
            ("start", ["--platform", "android", "--wait", "0"]),
            ("start", ["--platform=ios", "--link", "example://screen", "--wait=1.5"]),
            ("open", ["--link", "example://screen"]),
            ("stop", []),
        ):
            for bytecode_flag in (True, False):
                with self.subTest(operation=operation, bytecode_flag=bytecode_flag):
                    command = self.command("/worktree", operation, *options, bytecode_flag=bytecode_flag)
                    self.assertEqual(self.targets(command), ["/worktree"])

    def test_controls_are_not_read_only_or_lifecycle_exempt(self):
        for operation, options in (("start", []), ("open", ["--link", "example://screen"]), ("stop", [])):
            command = self.command("/worktree", operation, *options)
            _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, ROOT)
            self.assertNotIn(bash_command_kind(tokens, simple, ROOT), {"read_only", "runtime_control", "bootstrap"})

    def test_equals_project_option_is_still_a_write_operand(self):
        command = shlex.join(["python3", str(ROOT / "scripts/live_device.py"),
                              "start", "--project=/worktree", "--wait=0"])
        self.assertEqual(self.targets(command), ["--project=/worktree"])

    def test_unvalidated_commands_keep_the_script_governed(self):
        program = str(ROOT / "scripts/live_device.py")
        for arguments in (
            ["start"], ["start", "--project", "relative"],
            ["start", "--project", "/one", "--project", "/two"],
            ["start", "--project", "/repo", "--output", "/protected/file"],
            ["start", "--project", "/repo", "--platform", "other"],
            ["start", "--project", "/repo", "--wait", "nan"],
            ["start", "--project", "/repo", "--wait", "-1"],
            ["open", "--project", "/repo"], ["stop", "--project", "/repo", "--link", "example://screen"],
        ):
            with self.subTest(arguments=arguments):
                command = shlex.join(["python3", "-B", program, *arguments])
                self.assertIn(program, self.targets(command))
        impostor = "python3 -B /tmp/live_device.py start --project /repo --wait 0"
        self.assertIn("/tmp/live_device.py", self.targets(impostor))

    def test_gate_uses_target_workflow_and_preserves_isolation_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: directory + "/state"}
        ):
            fixture = gate_tests.CodexRepairableApprovalTests()
            project = fixture._project(Path(directory))
            payload = {"tool_name": "Bash", "cwd": str(project), "session_id": "live-control",
                       "tool_input": {"command": self.command(project, "start", "--wait", "0")}}

            _, missing = _decide(payload)
            self.assertEqual(_decision_of(missing), "deny")
            self.assertIn("workflow", _reason(missing).lower())

            _write_preflight(project, "live-control", command="test", runtime="codex")
            _, entered = _decide(payload)
            self.assertEqual(_decision_of(entered), "allow", entered)

            main = Path(directory) / "proj"
            payload["cwd"] = str(main)
            payload["tool_input"]["command"] = (
                "cd " + shlex.quote(str(project)) + " && "
                + self.command(project, "start", "--wait", "0", bytecode_flag=False)
            )
            _, explicit_worktree = _decide(payload)
            self.assertEqual(_decision_of(explicit_worktree), "allow", explicit_worktree)
            payload["cwd"] = str(project)
            payload["tool_input"]["command"] = self.command(main, "start", "--wait", "0")
            _, protected = _decide(payload)
            self.assertEqual(_decision_of(protected), "deny")
            self.assertIn("main checkout", _reason(protected))

            _write_preflight(project, "lookup", command="analysis", read_only=True, runtime="codex")
            payload["session_id"] = "lookup"
            payload["tool_input"]["command"] = self.command(project, "start", "--wait", "0")
            _, read_only = _decide(payload)
            self.assertEqual(_decision_of(read_only), "deny")
            self.assertIn("read-only", _reason(read_only))

            payload["session_id"] = "live-control"
            payload["tool_input"]["command"] += " && touch " + str(main / "changed")
            _, composed_write = _decide(payload)
            self.assertEqual(_decision_of(composed_write), "deny")
