"""A provider CLI worker started through Claude's Bash tool runs in the background.

Reproduces a Codex comparison cut off by the Bash tool's default timeout: the
lead ran `codex exec` in the foreground although the comparison may run long.
The gate now holds that call and names the background form; mentions of the
CLI in data, heredoc bodies and help/version calls stay allowed.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_claude_pretool_gate import _decide, _opt_in_project, gate  # also puts scripts/ on sys.path
from agent_block_lessons import NEXT_ACTIONS
from claude_pretool_cli_worker import foreground_cli_worker_denial


def _payload(command: str, cwd: str = "/tmp", **tool_input: object) -> dict:
    return {
        "tool_name": "Bash",
        "cwd": cwd,
        "session_id": "cli-worker-guard",
        "tool_input": {"command": command, **tool_input},
    }


class ForegroundCliWorkerDenialTests(unittest.TestCase):
    def test_foreground_workers_are_held(self) -> None:
        for command, worker in (
            ("codex exec -o last.md - < brief.md > stream.log 2>&1", "codex exec"),
            ("cd /tmp/x && env -u CLAUDECODE SPILL_AI_TOOL=codex codex exec -C . - < b.md; echo done", "codex exec"),
            ("/opt/bin/codex e 'review this'", "codex exec"),
            ("codex -C /tmp exec review", "codex exec"),
            ("codex --profile demo -c model=x exec review", "codex exec"),
            ("timeout 600 codex exec review", "codex exec"),
            ("npx codex exec review", "codex exec"),
            ("bash -c 'codex exec review'", "codex exec"),
            ("zsh -lc 'cd /tmp && codex exec review'", "codex exec"),
            ("echo $(date); codex exec review", "codex exec"),
            ('echo "$(codex exec review)"', "codex exec"),
            ("echo `codex exec review`", "codex exec"),
            ("codex exec -- --help", "codex exec"),
            ("claude -p 'compare' > out.log 2>&1", "claude -p"),
            ("nohup claude --print 'compare'", "claude -p"),
            ("claude --model opus -p compare", "claude -p"),
            ('claude -p -- "--help"', "claude -p"),
        ):
            with self.subTest(command=command):
                reason = foreground_cli_worker_denial(_payload(command))
                self.assertIn(f"`{worker}`", reason)
                self.assertIn("run_in_background: true", reason)

    def test_background_and_non_worker_calls_pass(self) -> None:
        self.assertEqual("", foreground_cli_worker_denial(_payload("codex exec - < b.md", run_in_background=True)))
        for command in (
            'grep -rn "codex exec" scripts',
            "echo 'codex exec review'",
            "echo '$(codex exec review)'",
            "cat <<'EOF' > brief.md\ncodex exec review\nclaude -p compare\nEOF",
            "codex --version",
            "codex exec --help",
            "codex exec --version",
            "codex exec help",
            "codex login",
            "claude --help",
            "claude -p --version",
            "claude mcp list",
            "claude mcp add my-server -- my-command -p 3000",
        ):
            with self.subTest(command=command):
                self.assertEqual("", foreground_cli_worker_denial(_payload(command)))


class GateForegroundCliWorkerTests(unittest.TestCase):
    def _gate(self, command: str, cwd: Path, runtime: str = "claude", **tool_input: object) -> tuple[str, dict]:
        with patch.dict(os.environ, {"MORU_PRETOOL_RUNTIME": runtime}), patch.object(gate, "_learn_block") as learn:
            code, out = _decide(_payload(command, cwd=str(cwd), **tool_input))
        self.assertEqual(0, code)
        self.learned = [call.args[0] for call in learn.call_args_list]
        return out, (json.loads(out)["hookSpecificOutput"] if out.strip() else {})

    def test_gate_denies_foreground_worker_outside_a_project_and_records_the_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _out, output = self._gate("codex exec - < brief.md > stream.log 2>&1", Path(directory))
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("run_in_background: true", output["permissionDecisionReason"])
        self.assertEqual(["foreground_cli_worker"], self.learned)
        self.assertEqual("run_cli_workers_in_the_background", NEXT_ACTIONS["pretool_gate"]["foreground_cli_worker"])

    def test_gate_denies_foreground_worker_inside_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = _opt_in_project(Path(directory))
            _out, output = self._gate("codex exec - < brief.md", project)
        self.assertEqual("deny", output["permissionDecision"])
        self.assertIn("`codex exec`", output["permissionDecisionReason"])

    def test_gate_passes_background_worker_and_codex_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out, _output = self._gate("codex exec - < brief.md", Path(directory), run_in_background=True)
            self.assertNotIn("run_in_background: true", out)
            self.assertNotIn("foreground_cli_worker", self.learned)
            out, _output = self._gate("codex exec - < brief.md", Path(directory), runtime="codex")
            self.assertNotIn("run_in_background: true", out)
            self.assertNotIn("foreground_cli_worker", self.learned)


if __name__ == "__main__":
    unittest.main()
