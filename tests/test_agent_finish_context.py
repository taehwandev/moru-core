"""Context advice stays optional, numeric-only and scoped to the finishing session."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_finish_context import context_nudge, MAX_TAIL_BYTES

RUN_ID = "a" * 32
SESSION = {"runtime": "claude", "session_id": "session-1"}


def assistant(tokens=200_000, **extra):
    return {"type": "assistant", "message": {"usage": {"input_tokens": tokens},
            "content": "PRIVATE TRANSCRIPT CONTENT"}, **extra}


class FinishContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name)
        self.path = self.config / "projects" / "project" / "session-1.jsonl"
        self.path.parent.mkdir(parents=True)
        self.env = patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(self.config)})
        self.env.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.env.stop)

    def write(self, *entries):
        self.path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")

    def test_threshold_and_single_line_advice(self):
        for tokens, expected in ((199_999, False), (200_000, True), (200_001, True)):
            with self.subTest(tokens=tokens):
                self.write(assistant(tokens))
                line = context_nudge(SESSION, RUN_ID)
                self.assertEqual(expected, bool(line))
                if line:
                    self.assertTrue(line.startswith("For the user: "))
                    self.assertEqual(1, len(line.splitlines()))
                    for part in ("unrelated", "/compact", "related follow-up", "keep",
                                 f"start --continue-from {RUN_ID}"):
                        self.assertIn(part, line)
                    self.assertNotIn("PRIVATE", line)
                    self.assertNotIn(str(self.path), line)

    def test_cache_input_is_included_but_output_is_not(self):
        entry = assistant(1)
        entry["message"]["usage"].update(cache_creation_input_tokens=9,
            cache_read_input_tokens=199_990, output_tokens=999_999)
        self.write(entry)
        self.assertTrue(context_nudge(SESSION, RUN_ID))
        self.assertFalse(context_nudge(SESSION, RUN_ID, threshold=200_001))

    def test_latest_usage_and_compaction_replace_older_large_context(self):
        for latest in (assistant(10), {"type": "assistant", "message": {}},
                       {"type": "system", "subtype": "compact_boundary"}):
            with self.subTest(latest=latest):
                self.write(assistant(), latest)
                self.assertEqual("", context_nudge(SESSION, RUN_ID))

    def test_unknown_or_invalid_usage_is_silent(self):
        for tokens in (None, "200000", -1, True, 200_000.0):
            self.write(assistant(tokens))
            self.assertEqual("", context_nudge(SESSION, RUN_ID))
        self.write({"type": "assistant", "message": []}, [], "bad entry")
        self.assertEqual("", context_nudge(SESSION, RUN_ID))

    def test_other_runtimes_never_read_transcripts(self):
        with patch("agent_finish_context._latest_context_tokens") as read:
            for runtime in ("codex", "antigravity", "gemini", "cli", ""):
                self.assertEqual("", context_nudge({**SESSION, "runtime": runtime}, RUN_ID))
            read.assert_not_called()

    def test_missing_unreadable_ambiguous_or_unsafe_session_is_silent(self):
        self.assertEqual("", context_nudge(SESSION, RUN_ID))
        self.write(assistant())
        with patch.object(Path, "open", side_effect=OSError):
            self.assertEqual("", context_nudge(SESSION, RUN_ID))
        other = self.config / "projects" / "other" / self.path.name
        other.parent.mkdir()
        other.write_text(self.path.read_text())
        self.assertEqual("", context_nudge(SESSION, RUN_ID))
        for session_id in ("../session-1", "*", ""):
            self.assertEqual("", context_nudge({**SESSION, "session_id": session_id}, RUN_ID))
        self.assertEqual("", context_nudge(SESSION, "unsafe\nrun"))

    def test_tail_only_ignores_sidechains_and_malformed_trailing_records(self):
        self.write(assistant(), assistant(1, isSidechain=True))
        with self.path.open("a") as stream:
            stream.write('{"unfinished":\n')
        self.assertTrue(context_nudge(SESSION, RUN_ID))
        self.path.write_bytes(b"x" * (MAX_TAIL_BYTES + 1) + b"\n" +
                              json.dumps(assistant()).encode() + b"\n")
        self.assertTrue(context_nudge(SESSION, RUN_ID))
