"""Per-session overhead counts come from a transcript without leaking its text."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from claude_transcript_overhead import measure_session, new_shared_counters, normalize_message

ROOT = "/work/moru-core"


def _assistant(message_id: str, tools: list[tuple[str, str, dict]], output_tokens: int = 10) -> dict:
    return {
        "type": "assistant", "timestamp": "2026-10-10T00:00:00Z", "cwd": f"{ROOT}",
        "message": {
            "id": message_id,
            "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": output_tokens},
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}
                        for tool_id, name, tool_input in tools],
        },
    }


class TranscriptOverheadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "project" / "session.jsonl"
        self.path.parent.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _measure(self, entries: list) -> tuple[dict, dict]:
        lines = [json.dumps(entry) if isinstance(entry, dict) else entry for entry in entries]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        shared = new_shared_counters()
        return measure_session(str(self.path), [ROOT], shared), shared

    def test_lifecycle_calls_tokens_and_guidance_reads_are_counted_once(self) -> None:
        start = ("t1", "Bash", {"command": "/home/u/.moru/bin/moru-hook start --project . --request secret"})
        read = ("t2", "Read", {"file_path": f"{ROOT}-worktrees/task/common/skills/x/SKILL.md"})
        grep = ("t3", "Bash", {"command": "grep moru-hook start notes.txt"})
        row, _ = self._measure([
            _assistant("m1", [start, read]),
            _assistant("m1", [start, read]),  # streamed duplicate of the same message
            _assistant("m2", [grep]),
            {"type": "user", "message": {"content": "do the task"}},
            "not json",
        ])
        self.assertEqual(2, row["assistant_turns"])
        self.assertEqual(3, row["tool_calls"])
        self.assertEqual({"start": 1}, dict(row["lifecycle_calls"]))
        self.assertEqual(1, row["guidance_reads"])
        self.assertEqual(1, row["user_prompts"])
        self.assertEqual(2 * (5 + 100 + 10), row["tok_total"])
        self.assertTrue(row["moru_core"])
        self.assertNotIn("secret", json.dumps(row, default=str))

    def test_policy_notes_denials_and_hook_latency_are_aggregated(self) -> None:
        note = "Moru policy note: /Users/me/repo unknown effect 0123456789abcdef0123"
        denial = "PreToolUse:Bash hook error: Moru Core: run the workflow start hook first"
        row, shared = self._measure([
            {"type": "attachment", "attachment": {"type": "hook_additional_context", "content": [note]}},
            {"type": "user", "toolDenialKind": "hook",
             "message": {"content": [{"type": "tool_result", "is_error": True, "content": denial}]}},
            {"type": "attachment", "attachment": {
                "type": "hook_success", "hookEvent": "PreToolUse", "durationMs": 61,
                "command": "/x/moru-hook claude-pretool-gate", "stdout": "{}"}},
            {"type": "system", "subtype": "stop_hook_summary", "preventedContinuation": True,
             "hookInfos": [{"command": "/x/moru-hook claude-stop-gate", "durationMs": 40}]},
        ])
        self.assertEqual(1, row["policy_notes"])
        self.assertEqual(1, row["moru_hook_denials"])
        self.assertEqual(1, row["stop_hook_blocks"])
        self.assertEqual(len(note) + len(denial), row["moru_injected_chars"])
        self.assertEqual({"PreToolUse:claude-pretool-gate": [61.0], "Stop:claude-stop-gate": [40.0]},
                         dict(shared["hook_latency"]))
        (message,) = shared["notes"]
        self.assertNotIn("/Users", message)
        self.assertIn("<id>", message)

    def test_pre_rename_brand_is_normalized(self) -> None:
        self.assertEqual("Moru Core gate: <path>", normalize_message("Tao Agent OS gate: /Users/a/b"))


if __name__ == "__main__":
    unittest.main()
