from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agy_hook_adapter as adapter
from support.agy_setup import _agy_hooks_spec, _merge_agy_hooks


def gate_output(decision: str, reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"permissionDecision": decision, "permissionDecisionReason": reason}})


class PreToolTranslationTests(unittest.TestCase):
    def call(self, name: str, args: dict) -> dict:
        return {"conversationId": "c1", "workspacePaths": ["/w"], "toolCall": {"name": name, "args": args}}

    def test_tools_the_gate_does_not_govern_are_allowed_without_running_it(self):
        with patch.object(adapter, "run_script", side_effect=AssertionError("gate must not run")):
            self.assertEqual({"decision": "allow"}, adapter.pre_tool(self.call("read_file", {"Path": "x"})))

    def test_commands_and_edits_reach_the_gate_in_claude_shape(self):
        seen = []

        def fake(name, args, stdin, cwd, env=None):
            seen.append((name, stdin, env))
            return ""

        with patch.object(adapter, "run_script", fake):
            adapter.pre_tool(self.call("run_command", {"CommandLine": "ls"}))
            adapter.pre_tool(self.call("write_file", {"Path": "/w/a.txt"}))
        self.assertEqual(("Bash", {"command": "ls"}), (seen[0][1]["tool_name"], seen[0][1]["tool_input"]))
        self.assertEqual(("Write", {"file_path": "/w/a.txt"}), (seen[1][1]["tool_name"], seen[1][1]["tool_input"]))
        self.assertEqual("c1", seen[0][1]["session_id"])
        self.assertEqual("antigravity", seen[0][2]["MORU_PRETOOL_RUNTIME"])

    def test_a_deny_is_advisory_by_default_and_enforced_in_strict_mode(self):
        with patch.object(adapter, "run_script", return_value=gate_output("deny", "start first")):
            with patch.dict(os.environ, {"MORU_AGY_GATE": ""}):
                verdict = adapter.pre_tool(self.call("write_file", {"Path": "/w/a.txt"}))
            self.assertEqual("allow", verdict["decision"])
            self.assertIn("start first", verdict["reason"])
            with patch.dict(os.environ, {"MORU_AGY_GATE": "strict"}):
                strict = adapter.pre_tool(self.call("write_file", {"Path": "/w/a.txt"}))
            self.assertEqual({"decision": "deny", "reason": "start first"}, strict)


class StopTranslationTests(unittest.TestCase):
    def test_a_block_becomes_continue_once(self):
        captured = []

        def fake(name, args, stdin, cwd, env=None):
            captured.append(stdin)
            return json.dumps({"decision": "block", "reason": "finish first"})

        with patch.object(adapter, "run_script", fake):
            first = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 0})
            second = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 1})
        self.assertEqual({"decision": "continue", "reason": "finish first"}, first)
        self.assertFalse(captured[0]["stop_hook_active"])
        self.assertTrue(captured[1]["stop_hook_active"])
        self.assertEqual({"decision": "continue", "reason": "finish first"}, second)

    def test_no_block_lets_the_agent_stop(self):
        with patch.object(adapter, "run_script", return_value=""):
            self.assertEqual({}, adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"]}))


class UnverifiedReminderTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "c7", "workspacePaths": ["/w"], "executionNum": 0}

    def test_a_3d_routed_session_is_reminded_once_at_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True):
            first = adapter.stop(self.PAYLOAD)
            second = adapter.stop(self.PAYLOAD)
        self.assertEqual("continue", first["decision"])
        self.assertIn("unverified", first["reason"])
        self.assertEqual({}, second)

    def test_other_sessions_and_a_second_execution_are_not_reminded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""):
            with patch.object(adapter, "routed_through_3d", return_value=False):
                self.assertEqual({}, adapter.stop(self.PAYLOAD))
            with patch.object(adapter, "routed_through_3d", return_value=True):
                self.assertEqual({}, adapter.stop({**self.PAYLOAD, "executionNum": 1}))

    def test_the_gate_block_wins_and_no_run_means_no_reminder(self):
        block = json.dumps({"decision": "block", "reason": "finish first"})
        with patch.object(adapter, "run_script", return_value=block):
            self.assertEqual("finish first", adapter.stop(self.PAYLOAD)["reason"])
        with patch.object(adapter, "run_script", return_value=""), \
                patch("agent_runtime_session.resolve_runtime_evidence", return_value=None):
            self.assertFalse(adapter.routed_through_3d(self.PAYLOAD))

    def test_route_and_stop_markers_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)):
            self.assertFalse(adapter.already_delivered("c1", "route text"))
            self.assertFalse(adapter.already_delivered("c1", "reminder", "stop"))
            self.assertTrue(adapter.already_delivered("c1", "route text"))
            self.assertTrue(adapter.already_delivered("c1", "reminder", "stop"))


class InSessionVerificationTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "cv", "workspacePaths": ["/w"], "lastUserInput": "Build a thing", "executionNum": 0}

    def run_stop(self, results, rounds_before=0, can_judge=True, dist=True):
        import types

        calls = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist") if dist else None
        fake.can_judge = lambda: can_judge

        def verify_project(project, request, out, checklist=None, **kw):
            calls.append((request, checklist))
            return [{"id": "a"}], results

        fake.verify_project = verify_project
        fake.feedback_text = lambda r: ("FIX: " + ",".join(x["id"] for x in r if x["verdict"] == "fail")
                                        if any(x["verdict"] == "fail" for x in r) else "")
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            for _ in range(rounds_before):
                adapter.stop(self.PAYLOAD)
            return adapter.stop(self.PAYLOAD), calls, Path(tmp)

    def test_a_failure_is_sent_back_as_continue_and_the_checklist_is_kept(self):
        fail = [{"id": "a", "verdict": "fail"}]
        verdict, calls, tmp = self.run_stop(fail)
        self.assertEqual({"decision": "continue", "reason": "FIX: a"}, verdict)
        self.assertEqual([("Build a thing", None)], calls)

    def test_the_second_round_reuses_the_first_checklist_and_the_rounds_are_capped(self):
        fail = [{"id": "a", "verdict": "fail"}]
        verdict, calls, _ = self.run_stop(fail, rounds_before=1)
        self.assertEqual("continue", verdict["decision"])
        self.assertEqual([("Build a thing", None), ("Build a thing", [{"id": "a"}])], calls)
        verdict, calls, _ = self.run_stop(fail, rounds_before=2)
        self.assertEqual({}, verdict, "the last allowed round ends with no further request")
        verdict, calls, _ = self.run_stop(fail, rounds_before=3)
        self.assertEqual({}, verdict)
        self.assertEqual(3, len(calls), "no verification beyond the cap")

    def test_all_pass_lets_the_agent_stop_without_the_reminder(self):
        verdict, calls, _ = self.run_stop([{"id": "a", "verdict": "pass"}])
        self.assertEqual({}, verdict)

    def test_when_verification_cannot_run_the_reminder_is_the_fallback(self):
        for kwargs in ({"can_judge": False}, {"dist": False}):
            with self.subTest(kwargs=kwargs):
                verdict, calls, _ = self.run_stop([], **kwargs)
                self.assertEqual("continue", verdict["decision"])
                self.assertIn("unverified", verdict["reason"])
                self.assertEqual([], calls)


class PreInvocationTests(unittest.TestCase):
    def test_guidance_is_injected_once_per_conversation(self):
        def fake(name, args, stdin, cwd, env=None):
            return "# Moru Core Workflow Route\n" if name == "workflow.py" else "status: not_found\n"

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake):
            payload = {"conversationId": "c9", "workspacePaths": [tmp], "lastUserInput": "Create a page"}
            first = adapter.pre_invocation(payload)
            second = adapter.pre_invocation(payload)
        text = first["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("Workflow Route", text)
        self.assertIn("status: not_found", text)
        self.assertEqual({}, second)

    def test_the_shared_unchanged_note_injects_nothing(self):
        with patch.object(adapter, "run_script", return_value="unchanged since this session already received it"):
            self.assertEqual({}, adapter.pre_invocation({"conversationId": "c1", "workspacePaths": ["/w"]}))


class FailOpenTests(unittest.TestCase):
    def test_a_broken_payload_never_blocks(self):
        import io

        for event, expected in (("pre-tool", {"decision": "allow"}), ("stop", {}), ("pre-invocation", {})):
            with self.subTest(event=event), patch("sys.stdin", io.StringIO("not json")), \
                    patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(0, adapter.main(["agy_hook_adapter.py", event]))
                self.assertEqual(expected, json.loads(out.getvalue()))


class HooksFileMergeTests(unittest.TestCase):
    def test_installs_by_name_and_keeps_other_hooks(self):
        spec = _agy_hooks_spec(Path("/home/u/.moru/bin/moru-hook"))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "hooks.json"
            target.write_text(json.dumps({"mine": {"Stop": []}}))
            self.assertEqual("missing", _merge_agy_hooks(target, spec, True))
            self.assertEqual("installed", _merge_agy_hooks(target, spec, False))
            self.assertEqual("ok", _merge_agy_hooks(target, spec, False))
            written = json.loads(target.read_text())
        self.assertEqual({"mine": {"Stop": []}, "moru": spec}, written)
        commands = json.dumps(spec)
        for event in ("pre-invocation", "pre-tool", "stop"):
            self.assertIn(f"agy-hook {event}", commands)
        self.assertEqual("run_command|write_file|edit_file", spec["PreToolUse"][0]["matcher"])


if __name__ == "__main__":
    unittest.main()
