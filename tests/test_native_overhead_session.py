"""Synthetic session parity, native execution and atomic fallback boundaries."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import claude_transcript_overhead as reference
from native_pretool_support import environment, prepare
from support.native_overhead import NativeOverhead


def assistant(identifier="m1", **fields):
    return {"type": "assistant", "timestamp": "2026-10-10T00:00:00Z", "cwd": "/work/core",
            "message": {"id": identifier, "usage": {"input_tokens": 5, "output_tokens": 7},
                        "content": [], **fields}}


class NativeOverheadSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-overhead-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()
        self.path = self.base / "session.jsonl"
        self.roots = ["/work/core"]

    def write(self, entries):
        self.path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n")

    def raw(self, payload=None, **env):
        payload = payload or {"path": str(self.path), "roots": self.roots, "window": [None, None]}
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
            "--overhead-probe", "session"], input=json.dumps(payload).encode(),
            env={**self.env, "PATH": str(self.empty), **env}, cwd=self.project,
            capture_output=True, timeout=8)

    def parity(self, *, window=(None, None), required=True):
        initial = reference.new_shared_counters()
        initial["notes"]["existing"] = 2
        initial["hook_latency"]["existing"].append(4.0)
        expected_shared, actual_shared = copy.deepcopy(initial), copy.deepcopy(initial)
        before = self.path.read_bytes()
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = reference.measure_session(str(self.path), self.roots, expected_shared, window)
        with patch.dict(os.environ, self.env, clear=True):
            if required:
                with patch.object(reference, "SessionTally", side_effect=AssertionError("Python replay")):
                    actual = reference.measure_session(str(self.path), self.roots, actual_shared, window)
            else:
                actual = reference.measure_session(str(self.path), self.roots, actual_shared, window)
        self.assertEqual(expected, actual)
        self.assertEqual(expected_shared, actual_shared)
        for name in ("notes", "denials", "hook_latency"):
            self.assertEqual(list(expected_shared[name]), list(actual_shared[name]))
        self.assertEqual(before, self.path.read_bytes())
        return actual, actual_shared

    def test_streamed_messages_tools_and_empty_path_protocol(self):
        tools = [{"type": "tool_use", "id": "t1", "name": "Bash",
                  "input": {"command": "moru-hook start --request private-marker"}},
                 {"type": "tool_use", "id": "t2", "name": "Read",
                  "input": {"file_path": "/work/core/.moru/worktrees/branch/common/skills/x.md"}}]
        self.write([assistant(content=tools), assistant(content=tools),
                    {"type": "user", "message": {"content": "private-prompt-marker"}}])
        row, _ = self.parity()
        self.assertEqual((1, 2, 1), (row["assistant_turns"], row["tool_calls"], row["guidance_reads"]))
        done = self.raw()
        self.assertEqual((0, b""), (done.returncode, done.stderr))
        self.assertEqual(1, json.loads(done.stdout)["schema_version"])
        self.assertNotIn(b"private-marker", done.stdout)
        self.assertNotIn(b"private-prompt-marker", done.stdout)

    def test_hook_notes_denials_and_latencies_merge_once(self):
        self.write([
            {"type": "attachment", "attachment": {"type": "hook_additional_context",
             "content": ["Tao Agent OS policy note: /Users/person/repo toolu_abc 0123456789abcdef"]}},
            {"type": "user", "toolDenialKind": "hook", "message": {"content": [
             {"type": "tool_result", "is_error": True,
              "content": "PreToolUse:Bash hook error: Moru gate /home/person/repo"}]}},
            {"type": "attachment", "attachment": {"type": "hook_success", "command": "moru-hook gate",
             "hookEvent": "PreToolUse", "durationMs": "1_2.5", "stdout": "Moru ready"}},
            {"type": "system", "subtype": "stop_hook_summary", "preventedContinuation": True,
             "hookInfos": [{"command": "moru-hook finish", "durationMs": 5}]},
            *[{"type": "attachment", "attachment": {"type": "hook_success", "command": "moru-hook gate",
               "hookEvent": f"Invalid{index}", "durationMs": value}}
              for index, value in enumerate((None, "bad", [], {}))],
            {"type": "system", "subtype": "stop_hook_summary",
             "hookInfos": [{"command": "moru-hook next"}]},
        ])
        row, shared = self.parity()
        self.assertEqual(1, row["stop_hook_blocks"])
        self.assertEqual([12.5], shared["hook_latency"]["PreToolUse:gate"])
        self.assertEqual([], shared["hook_latency"]["Invalid0:gate"])
        self.assertEqual([], shared["hook_latency"]["Stop:next"])
        self.assertNotIn("/Users", json.dumps(shared))

    def test_inclusive_windows_offset_comparison_and_cwd_before_window(self):
        entries = [assistant("before"), assistant("edge"), assistant("after")]
        entries[1]["timestamp"] = "2026-10-11T09:00:00+09:00"
        entries[2]["timestamp"] = "2026-10-12T00:00:00.123456Z"
        self.write(entries)
        edge = dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc)
        row, _ = self.parity(window=(edge, edge))
        self.assertEqual(1, row["assistant_turns"])
        self.assertEqual(edge, row["first_ts"])
        self.assertTrue(row["moru_core"])

    def test_python_scalar_id_equality_and_missing_ids(self):
        self.write([assistant(v) for v in (True, 1, 1.0, False, 0, 0.0, None, None, "1")])
        row, _ = self.parity(required=False)
        self.assertEqual(3, row["assistant_turns"])

    def test_malformed_entry_partial_updates_replay_exactly(self):
        self.write([assistant(usage={"input_tokens": 5, "output_tokens": "bad"}), assistant(),
                    assistant("m2", content=[{"type": "tool_use", "id": "t", "name": ["bad"], "input": {}}]),
                    assistant("m3", usage={"input_tokens": 10 ** 80})])
        self.parity(required=False)

    def test_jsonl_replacement_decoding_and_newlines(self):
        self.path.write_bytes(b'not json\rnull\r\n{"type":"user","message":{"content":"\xff"}}\n')
        row, _ = self.parity()
        self.assertEqual(1, row["user_prompts"])

    def test_builder_integer_string_digit_limit_replays_partial_entry(self):
        limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if not limit:
            self.skipTest("builder Python has no integer string digit limit")
        for value in ("0" * limit + "1", "٠_" * limit + "١"):
            self.write([assistant(usage={"input_tokens": value, "output_tokens": 7}), assistant()])
            row, _ = self.parity(required=False)
            self.assertEqual(0, row["tok_total"])

    def test_special_files_and_environment_decline_silently(self):
        self.write([assistant()])
        done = self.raw(PYTHONVERBOSE="1", MORU_HOOK_SOFT_FAIL="1")
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        done = self.raw(MORU_HOME=str(self.project))
        self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        fifo = self.base / "fifo"
        os.mkfifo(fifo)
        link = self.base / "link"
        link.symlink_to(self.path)
        for path in (fifo, link, self.base / "missing", "/dev/stdin"):
            done = self.raw({"path": str(path), "roots": self.roots, "window": [None, None]})
            self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
        prefixes = ["/dev/fd"]
        if Path("/DEV/fd").exists():
            prefixes.append("/DEV/fd")
        with self.path.open("rb", buffering=0) as handle:
            handle.read(3)
            for prefix in prefixes:
                done = subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry),
                    "--overhead-probe", "session"], input=json.dumps({"path": f"{prefix}/{handle.fileno()}",
                    "roots": self.roots, "window": [None, None]}).encode(), pass_fds=(handle.fileno(),),
                    env=self.env, capture_output=True, timeout=8)
                self.assertEqual(125, done.returncode)
                self.assertEqual(3, os.lseek(handle.fileno(), 0, os.SEEK_CUR))

    def test_declined_or_malformed_response_does_not_mutate_shared(self):
        shared = reference.new_shared_counters()
        shared["notes"]["kept"] = 4
        before = copy.deepcopy(shared)
        self.write([assistant()])
        with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
            row = reference.measure_session(str(self.path), self.roots, reference.new_shared_counters())
        row = json.loads(json.dumps(row, default=lambda value: value.isoformat()))
        bad_latency = {"row": row, "shared": {"notes": {"bad": 2}, "denials": {},
                                             "hook_latency": {"late": "bad"}}}
        bad_stamp = {"row": {**row, "last_ts": "not-a-time"},
                     "shared": {"notes": {"bad": 2}, "denials": {}, "hook_latency": {}}}
        for response in (None, {}, {"row": {}, "shared": {"notes": {"bad": 2}}}, bad_latency, bad_stamp):
            with patch("support.native_overhead.NativeProbe.request", return_value=response):
                self.assertIsNone(NativeOverhead.measure(str(self.path), self.roots, shared, (None, None)))
            self.assertEqual(before, shared)


if __name__ == "__main__":
    unittest.main()
