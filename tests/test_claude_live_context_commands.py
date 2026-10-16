"""Live inspection must work without turning arbitrary scripts into trusted commands."""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claude_bash_readonly import bash_command_kind, bash_invocation


class LiveContextCommandTests(unittest.TestCase):
    def kind(self, command):
        cwd, tokens, simple = bash_invocation({"tool_input": {"command": command}}, ROOT)
        return bash_command_kind(tokens, simple, cwd)

    def command(self, script, *arguments):
        return shlex.join(["python3", "-B", str(ROOT / "scripts" / script), *arguments])

    def test_live_status_and_save_checks_are_read_only(self):
        for arguments in (
            ["status"], ["status", "--project", "/repo", "--json"],
            ["check", "--project=/repo", "--files", "app/A.kt", "app/B.kt", "--since", "2026-10-16T04:26:19Z"],
            ["check", "--json"],
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.kind(self.command("live_device.py", *arguments)), "read_only")

    def test_claims_are_bounded_local_context_and_web_checks_only_read(self):
        for arguments in (
            ["status", "--project", "/repo", "--json"],
            ["claim", "--project", "/repo", "--path", "src/A.kt", "--path=src/B.kt", "--holder", "session", "--ttl", "60", "--wait", "0"],
            ["release", "--project", "/repo", "--path", "src/A.kt"],
            ["release", "--project", "/repo", "--all"],
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.kind(self.command("path_claims.py", *arguments)), "runtime_control")
        self.assertEqual(self.kind(self.command(
            "path_claims.py", "check", "--project", "/repo", "--files", "src/A.tsx", "--json",
        )), "read_only")

    def test_observed_lookups_work_on_protected_checkout_for_both_runtimes(self):
        from tests.test_claude_pretool_gate import _decide, _opt_in_project, _require_linked_worktree
        with tempfile.TemporaryDirectory() as directory:
            project = _opt_in_project(Path(directory))
            _require_linked_worktree(project)
            for runtime in ("codex", "claude"):
                with self.subTest(runtime=runtime), patch.dict(os.environ, {"MORU_PRETOOL_RUNTIME": runtime}):
                    for script in ("live_device.py", "path_claims.py"):
                        command = self.command(script, "status", "--project", str(project))
                        for spelling in (command, command.replace("python3 -B", "python3")):
                            payload = {"tool_name": "Bash", "cwd": str(project), "session_id": "live-lookup",
                                       "tool_input": {"command": spelling}}
                            self.assertEqual(_decide(payload), (0, ""))

    def test_unknown_syntax_impostors_and_composed_writes_gain_no_exemption(self):
        valid = self.command("live_device.py", "status", "--project", "/repo")
        for command in (
            self.command("live_device.py", "status", "--output", "/repo/file"),
            self.command("live_device.py", "status", "extra"),
            self.command("live_device.py", "status", "--project"),
            self.command("live_device.py", "status", "--project", "/one", "--project", "/two"),
            self.command("live_device.py", "check", "--files"),
            self.command("live_device.py", "status", "--files", "src/A.kt"),
            self.command("live_device.py", "start", "--project", "/repo"),
            self.command("path_claims.py", "status"),
            self.command("path_claims.py", "claim", "--project", "/repo"),
            self.command("path_claims.py", "release", "--project", "/repo", "--all", "--path", "src/A.kt"),
            self.command("path_claims.py", "release", "--project", "/repo"),
            self.command("path_claims.py", "record", "--from-hook"),
            "python3 /tmp/live_device.py status --project /repo",
            "python3 /tmp/path_claims.py status --project /repo",
            valid + " > /repo/result", valid + " && touch /repo/changed",
            valid.replace("python3 -B", "python3 -c"),
        ):
            with self.subTest(command=command):
                self.assertNotIn(self.kind(command), {"read_only", "runtime_control"})
