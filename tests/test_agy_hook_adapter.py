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

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake), patch.object(adapter, "verify_in_session", return_value=(False, {})):
            first = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 0})
            second = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 1})
        self.assertEqual({"decision": "continue", "reason": "finish first"}, first)
        self.assertFalse(captured[0]["stop_hook_active"])
        self.assertTrue(captured[1]["stop_hook_active"])
        self.assertEqual({"decision": "continue", "reason": "finish first"}, second)

    def test_no_block_lets_the_agent_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), patch.object(adapter, "routed_through_3d", return_value=False):
            self.assertEqual({}, adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"]}))


class UnverifiedReminderTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "c7", "workspacePaths": ["/w"], "executionNum": 0}

    def test_a_3d_routed_session_is_reminded_once_at_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True):
            first = adapter.stop(self.PAYLOAD)
            second = adapter.stop(self.PAYLOAD)
            third = adapter.stop(self.PAYLOAD)
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
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=block):
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


class StopGateContinuationCapTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "cg", "workspacePaths": ["/w"], "lastUserInput": "Build a thing", "executionNum": 0}

    def test_the_finish_gate_blocks_once_per_user_input_then_stop_hook_active_is_set(self):
        seen = []

        def gate(name, args, stdin, cwd, env=None):
            seen.append(stdin["stop_hook_active"])
            return "" if stdin["stop_hook_active"] else json.dumps({"decision": "block", "reason": "finish first"})

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", side_effect=gate), \
                patch.object(adapter, "verify_in_session", return_value=(True, {})):
            first = adapter.stop(self.PAYLOAD)
            second = adapter.stop(self.PAYLOAD)
            third = adapter.stop(self.PAYLOAD)
        self.assertEqual("continue", first["decision"])
        self.assertEqual([{}, {}], [second, third])
        self.assertEqual([False, True, True], seen)

    def test_a_new_user_input_rearms_the_gate(self):
        def gate(name, args, stdin, cwd, env=None):
            return "" if stdin["stop_hook_active"] else json.dumps({"decision": "block", "reason": "finish first"})

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", side_effect=gate), \
                patch.object(adapter, "verify_in_session", return_value=(True, {})):
            adapter.stop(self.PAYLOAD)
            again = adapter.stop({**self.PAYLOAD, "lastUserInput": "A different request"})
        self.assertEqual("continue", again["decision"])

    def test_a_verification_continue_counts_so_the_gate_does_not_pile_on(self):
        seen = []

        def gate(name, args, stdin, cwd, env=None):
            seen.append(stdin["stop_hook_active"])
            return ""

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", side_effect=gate), \
                patch.object(adapter, "verify_in_session", side_effect=[(True, {"decision": "continue", "reason": "fix"}), (True, {})]):
            adapter.stop(self.PAYLOAD)
            adapter.stop(self.PAYLOAD)
        self.assertEqual([False, True], seen)


class InSessionVerificationTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "cv", "workspacePaths": ["/w"], "lastUserInput": "Build a thing", "executionNum": 0}

    def run_stop(self, results, rounds_before=0, can_judge=True, dist=True, fingerprint=None):
        import types

        import itertools

        sequence = itertools.chain(fingerprint or ["same"], itertools.repeat((fingerprint or ["same"])[-1]))

        calls = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist") if dist else None
        fake.can_judge = lambda: can_judge
        fake.project_fingerprint = lambda project: next(sequence)

        def verify_project(project, request, out, checklist=None, **kw):
            calls.append((request, checklist))
            return [{"id": "a"}], results

        fake.verify_project = verify_project
        fake.feedback_text = lambda r: ("FIX: " + ",".join(x["id"] for x in r if x["verdict"] == "fail")
                                        if any(x["verdict"] == "fail" for x in r) else "")
        fake.remaining_text = lambda r: ("STILL: " + ",".join(x["id"] for x in r if x["verdict"] == "fail")
                                         if any(x["verdict"] == "fail" for x in r) else "")
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            for _ in range(rounds_before):
                adapter.stop(self.PAYLOAD)
            return adapter.stop(self.PAYLOAD), calls, Path(tmp)

    def test_with_a_judge_service_the_local_evidence_is_removed_after_the_round(self):
        import types

        made = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_judge = lambda: True
        fake.project_fingerprint = lambda project: "x"
        fake.feedback_text = lambda r: ""
        fake.remaining_text = lambda r: ""

        def verify_project(project, request, out, checklist=None, **kw):
            out.mkdir(parents=True)
            (out / "checklist.json").write_text("[]")
            made.append(out)
            return [{"id": "a"}], [{"id": "a", "verdict": "pass"}]

        fake.verify_project = verify_project
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True), \
                patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": "http://127.0.0.1:9"}, clear=False), \
                patch.dict(sys.modules, {"verify": fake}):
            adapter.stop(self.PAYLOAD)
            leftovers = [p.exists() for p in made]
        self.assertEqual([False], leftovers, "the checked session must not find its checklist or pictures at home")

    def test_a_check_that_crashes_is_reported_once_and_never_ends_the_run_unseen(self):
        import types

        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_judge = lambda: True
        fake.project_fingerprint = lambda project: "x"

        def boom(*args, **kwargs):
            raise RuntimeError("judge url refused")

        fake.verify_project = boom
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            first = adapter.stop(self.PAYLOAD)
            second = adapter.stop(self.PAYLOAD)
            third = adapter.stop(self.PAYLOAD)
        self.assertEqual("continue", first["decision"])
        self.assertIn("could not run (RuntimeError: judge url refused)", first["reason"])
        self.assertIn("Nothing was independently verified", first["reason"])
        self.assertNotIn("could not run", second.get("reason", ""), "the crash notice is given once")
        self.assertEqual({}, third, "and the stop is never trapped")

    def test_a_failure_is_sent_back_as_continue_and_the_checklist_is_kept(self):
        fail = [{"id": "a", "verdict": "fail"}]
        verdict, calls, tmp = self.run_stop(fail)
        self.assertEqual({"decision": "continue", "reason": "FIX: a"}, verdict)
        self.assertEqual([("Build a thing", None)], calls)

    def test_one_fix_round_then_a_final_check_that_reports_what_remains_then_nothing(self):
        fail = [{"id": "a", "verdict": "fail"}]
        verdict, calls, _ = self.run_stop(fail, rounds_before=1, fingerprint=["a", "b"])
        self.assertEqual({"decision": "continue", "reason": "STILL: a"}, verdict,
                         "the last allowed check asks for a report of what remains, not another fix")
        self.assertEqual([("Build a thing", None), ("Build a thing", [{"id": "a"}])], calls,
                         "the re-check reuses the derived checklist")
        verdict, calls, _ = self.run_stop(fail, rounds_before=2, fingerprint=["a", "b", "c"])
        self.assertEqual({}, verdict, "the remaining failures were reported once; nothing more is asked")
        self.assertEqual(2, len(calls), "no verification beyond the cap")

    def test_a_passing_final_check_says_nothing(self):
        verdict, calls, _ = self.run_stop([{"id": "a", "verdict": "pass"}], rounds_before=1, fingerprint=["a", "b"])
        self.assertEqual({}, verdict)

    def test_an_unchanged_project_is_not_verified_again_but_its_failures_are_reported_once(self):
        fail = [{"id": "a", "verdict": "fail"}]
        verdict, calls, _ = self.run_stop(fail, rounds_before=1, fingerprint=["same", "same"])
        self.assertEqual({"decision": "continue", "reason": "STILL: a"}, verdict,
                         "nothing was fixed, so the failures held from the last check are reported")
        self.assertEqual(1, len(calls), "the second stop found the same fingerprint and skipped the check")
        verdict, calls, _ = self.run_stop(fail, rounds_before=2, fingerprint=["same", "same", "same"])
        self.assertEqual({}, verdict, "reported once, then the agent may stop")

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


class IndependentCheckNoticeTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "cn", "workspacePaths": ["/w"], "lastUserInput": "Create a 3D page"}

    def inject(self, entry, available):
        def fake(name, args, stdin, cwd, env=None):
            return "# Moru Core Workflow Route\n" if name == "workflow.py" else entry

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake), \
                patch.object(adapter, "independent_check_available", return_value=available):
            return adapter.pre_invocation(self.PAYLOAD)["injectSteps"][0]["systemMessage"]["systemMessage"]

    def test_the_notice_is_added_only_for_3d_work_when_the_check_can_run(self):
        entry = "guidance:\n- platforms/web/skills/web-3d-interaction/SKILL.md\n"
        self.assertIn("independent check opens the finished page", self.inject(entry, True))
        self.assertNotIn("independent check", self.inject(entry, False))
        self.assertNotIn("independent check", self.inject("guidance:\n- common/skills/other/SKILL.md\n", True))

    def test_the_notice_keeps_room_for_checks_the_verifier_misses_and_for_honest_reporting(self):
        self.assertIn("look at the running page yourself once", adapter.INDEPENDENT_CHECK_NOTICE)
        self.assertNotIn("Do not build", adapter.INDEPENDENT_CHECK_NOTICE,
                         "a prohibition collides with the UI skill that asks the agent to see its own page")
        self.assertIn("what you could not verify", adapter.INDEPENDENT_CHECK_NOTICE)

    def test_the_check_is_promised_only_when_judge_and_observer_are_both_present(self):
        import types

        for judge, observe, expected in ((True, True, True), (True, False, False), (False, True, False)):
            fake = types.ModuleType("verify")
            fake.can_judge = lambda j=judge: j
            fake.can_observe = lambda o=observe: o
            with self.subTest(judge=judge, observe=observe), patch.dict(sys.modules, {"verify": fake}):
                self.assertEqual(expected, adapter.independent_check_available())


class VerificationStateResetTests(unittest.TestCase):
    def test_a_new_user_input_does_not_inherit_the_last_checklist_or_rounds(self):
        import types

        calls = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_judge = lambda: True
        prints = iter(["one", "two", "three"])
        fake.project_fingerprint = lambda project: next(prints)

        def verify_project(project, request, out, checklist=None, **kw):
            calls.append((request, checklist))
            return [{"id": "a"}], [{"id": "a", "verdict": "fail"}]

        fake.verify_project = verify_project
        fake.feedback_text = lambda r: "FIX"
        base = {"conversationId": "cr", "workspacePaths": ["/w"], "executionNum": 0}
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(adapter, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            adapter.stop({**base, "lastUserInput": "first request"})
            adapter.stop({**base, "lastUserInput": "first request"})
            adapter.stop({**base, "lastUserInput": "second request"})
        self.assertEqual([("first request", None), ("first request", [{"id": "a"}]), ("second request", None)], calls)


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

    def test_state_lives_on_the_judge_service_when_one_is_configured(self):
        store: dict = {}

        class FakeVerify:
            @staticmethod
            def remote_call(path, body):
                self.assertEqual("/state", path)
                if body["op"] == "put":
                    store[body["key"]] = body["value"]
                    return {"ok": True}
                return {"value": store.get(body["key"])}

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "_verifier", return_value=FakeVerify), \
                patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": "http://127.0.0.1:1"}, clear=False):
            path = Path(tmp) / "conv1.stop.json"
            adapter.save_state(path, "stop", {"input": "x", "continuations": 1})
            loaded = adapter.load_state(path, "stop")
            on_disk = list(Path(tmp).iterdir())
        self.assertEqual(1, loaded["continuations"])
        self.assertEqual([], on_disk, "nothing is written where the checked session could rewrite it")
        self.assertIn("conv1.stop", store)

    def test_state_untouched_for_an_hour_is_forgotten(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)):
            path = Path(tmp) / "conv2.stop.json"
            adapter.save_state(path, "stop", {"input": "x", "continuations": 1})
            self.assertEqual(1, adapter.load_state(path, "stop")["continuations"])
            with patch.object(adapter.time, "time", return_value=__import__("time").time() + 3601):
                self.assertEqual({}, adapter.load_state(path, "stop"))

    def test_a_new_request_after_an_unchanged_route_still_gets_project_entry_once(self):
        def fake(name, args, stdin, cwd, env=None):
            return "unchanged since this session already received it" if name == "workflow.py" else "status: guided\n"

        with tempfile.TemporaryDirectory() as tmp, patch.object(adapter, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake):
            base = {"conversationId": "c10", "workspacePaths": [tmp]}
            first = adapter.pre_invocation({**base, "lastUserInput": "Now build a 3D scene"})
            again = adapter.pre_invocation({**base, "lastUserInput": "Now build a 3D scene"})
        text = first["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("status: guided", text)
        self.assertNotIn("unchanged since", text)
        self.assertEqual({}, again)

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
