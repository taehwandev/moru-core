from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_pretool_auto_start as auto  # noqa: E402
from support.global_state import STATE_HOME_ENV  # noqa: E402
from test_claude_pretool_gate import _decision_of, _opt_in_project, _reason, gate  # noqa: E402


def _prompt_payload(session: str, prompt: str) -> str:
    return json.dumps({"session_id": session, "prompt": prompt})


class _Result:
    def __init__(self, code: int, out: str):
        self.returncode, self.stdout, self.stderr = code, out, ""


class RequestRecordTests(unittest.TestCase):
    def test_latest_prompt_is_kept_per_session_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            auto.record_request(_prompt_payload("s1", "첫 요청"))
            auto.record_request(_prompt_payload("s1", "서버 재시작해줘"))
            auto.record_request(_prompt_payload("s2", "다른 세션"))
            self.assertEqual("서버 재시작해줘", auto.current_request("s1"))
            self.assertEqual("다른 세션", auto.current_request("s2"))
            later = auto.time.time() + auto.MAX_REQUEST_AGE_SECONDS + 1
            self.assertEqual("", auto.current_request("s1", now=later))
            self.assertEqual("", auto.current_request("unknown"))

    def test_unreadable_payload_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            for text in ("", "not json", "[]", json.dumps({"session_id": "s"}), json.dumps({"prompt": "x"})):
                auto.record_request(text)
            self.assertFalse((Path(tmp) / "session-requests").exists())

    def test_question_is_not_work(self):
        self.assertFalse(auto.is_work_request("어떻게하면 좋을까?"))
        self.assertTrue(auto.is_work_request("서버 재시작해줘"))


class StartRunTests(unittest.TestCase):
    def test_starts_small_change_local_write_with_recorded_prompt_and_session(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs["env"]))
            return _Result(0, "SUCCESS start\n- run id: abc123\n")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            auto.record_request(_prompt_payload("s1", "서버 재시작해줘"))
            run = auto.start_run(Path(tmp), "s1", "claude", "Edit", "a.py", runner=runner)
        self.assertEqual("abc123", run)
        command, env = calls[0]
        self.assertEqual("start", command[2])
        for flag, value in (("--command", "small-change"), ("--request", "서버 재시작해줘"),
                            ("--intent", "auto_work"), ("--requested-effect", "local_write")):
            self.assertEqual(value, command[command.index(flag) + 1])
        self.assertNotIn("--approved-effect", command)
        self.assertEqual("s1", env["CLAUDE_CODE_SESSION_ID"])

    def test_nothing_starts_without_a_work_request(self):
        def runner(*_args, **_kwargs):
            raise AssertionError("must not start")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            self.assertEqual("", auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner))
            auto.record_request(_prompt_payload("s1", "어떻게하면 좋을까?"))
            self.assertEqual("", auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner))

    def test_failed_start_is_not_retried_for_the_same_request(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            return _Result(2, "FAIL start")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            auto.record_request(_prompt_payload("s1", "서버 재시작해줘"))
            self.assertEqual("", auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner))
            self.assertEqual("", auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner))
            self.assertEqual(1, len(calls))
            auto.record_request(_prompt_payload("s1", "다른 파일도 고쳐줘"))
            auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner)
            self.assertEqual(2, len(calls))

    def test_timeout_falls_back_to_no_run(self):
        def runner(*_args, **_kwargs):
            raise subprocess.TimeoutExpired("start", 7)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp}):
            auto.record_request(_prompt_payload("s1", "서버 재시작해줘"))
            self.assertEqual("", auto.start_run(Path(tmp), "s1", "claude", "Edit", "", runner=runner))


class GateAutoStartTests(unittest.TestCase):
    def _edit(self, project: Path, session: str) -> dict:
        return {"tool_name": "Edit", "cwd": str(project), "session_id": session,
                "tool_input": {"file_path": str(project / "a.py"), "old_string": "a", "new_string": "b"}}

    def _run(self, payload: dict) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            gate.decide_with_auto_start(payload)
        return buffer.getvalue()

    def test_missing_entry_is_repaired_by_an_automatic_start_and_rejudged(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp + "/state"}):
            project = _opt_in_project(Path(tmp))
            payload = self._edit(project, "auto-1")
            started = []

            def start_run(root, session_id, runtime, tool, target):
                started.append((root, session_id, tool, target))
                return "run-1"

            decisions = iter(["deny", "allow"])
            notes = []

            def fake_decide(_payload):
                verdict = next(decisions)
                if verdict == "deny":
                    gate._AUTO_START["root"] = project
                    return gate.deny("Moru Core: run the workflow start hook", "workflow_entry_missing")
                notes.append(gate._AUTO_START["note"])
                return gate.allow()

            with patch.object(auto, "start_run", start_run), patch.object(gate, "decide", fake_decide):
                out = self._run(payload)
            self.assertEqual([(project, "auto-1", "Edit", "a.py")], started)
            self.assertNotEqual("deny", _decision_of(out))
            self.assertIn("started `small-change` run run-1", notes[0])

    def test_first_verdict_is_kept_when_the_start_does_not_happen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp + "/state"}):
            project = _opt_in_project(Path(tmp))
            payload = self._edit(project, "auto-2")
            with patch.object(auto, "start_run", lambda *a, **k: ""):
                out = self._run(payload)
            self.assertEqual("deny", _decision_of(out))
            self.assertIn("run the workflow start hook", _reason(out))

    def test_other_denials_never_start_a_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp + "/state"}):
            project = _opt_in_project(Path(tmp))

            def fake_decide(_payload):
                gate._AUTO_START["root"] = project
                return gate.deny("worktree", "worktree_isolation")

            def start_run(*_args, **_kwargs):
                raise AssertionError("must not start")

            with patch.object(auto, "start_run", start_run), patch.object(gate, "decide", fake_decide):
                out = self._run(self._edit(project, "auto-3"))
            self.assertEqual("deny", _decision_of(out))

    def test_disabled_by_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {STATE_HOME_ENV: tmp + "/state", auto.DISABLE_ENV: "0"}
        ):
            project = _opt_in_project(Path(tmp))

            def start_run(*_args, **_kwargs):
                raise AssertionError("must not start")

            with patch.object(auto, "start_run", start_run):
                out = self._run(self._edit(project, "auto-4"))
            self.assertEqual("deny", _decision_of(out))


class RealStartTests(unittest.TestCase):
    """The real compact start, in a throwaway project, opens a writable run."""

    def test_recorded_request_opens_a_run_that_admits_the_edit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {STATE_HOME_ENV: tmp + "/state"}):
            project = _opt_in_project(Path(tmp))
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            (project / "a.py").write_text("a\n")
            session = "auto-real"
            auto.record_request(_prompt_payload(session, "a.py 문구를 b로 고쳐줘"))
            payload = {"tool_name": "Edit", "cwd": str(project), "session_id": session,
                       "tool_input": {"file_path": str(project / "a.py"), "old_string": "a", "new_string": "b"}}
            with patch.object(auto, "START_TIMEOUT_SECONDS", 60):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    gate.decide_with_auto_start(payload)
            out = buffer.getvalue()
            self.assertNotEqual("deny", _decision_of(out), out)
            self.assertIn("started `small-change` run", out)


if __name__ == "__main__":
    unittest.main()
