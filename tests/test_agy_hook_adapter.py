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
import agy_hook_state
import agy_hook_verify
from support.agy_setup import _agy_hooks_spec, _merge_agy_hooks


def gate_output(decision: str, reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {"permissionDecision": decision, "permissionDecisionReason": reason}})


class PreToolTranslationTests(unittest.TestCase):
    def call(self, name: str, args: dict) -> dict:
        return {"conversationId": "c1", "workspacePaths": ["/w"], "toolCall": {"name": name, "args": args}}

    def test_tools_the_gate_does_not_govern_are_allowed_without_running_it(self):
        with patch.object(adapter, "run_script", side_effect=AssertionError("gate must not run")):
            self.assertEqual({"decision": "allow"}, adapter.pre_tool(self.call("read_file", {"Path": "x"})))

    def test_a_partial_read_of_a_skill_is_flagged_once_and_a_full_read_is_not(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)):
            skill = Path(tmp) / "demo" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("\n".join(f"line {n}" for n in range(1, 151)), encoding="utf-8")
            partial = self.call("read_file", {"Path": str(skill), "StartLine": 1, "EndLine": 100})
            first = adapter.pre_tool(partial)
            self.assertIn("150 lines", first["reason"])
            self.assertIn("101-150", first["reason"])
            self.assertEqual({"decision": "allow"}, adapter.pre_tool(partial))
            whole = self.call("read_file", {"Path": str(skill), "StartLine": 1, "EndLine": 150})
            self.assertEqual({"decision": "allow"}, adapter.pre_tool(whole))
            other = skill.with_name("notes.md")
            other.write_text("x\n" * 300, encoding="utf-8")
            self.assertEqual({"decision": "allow"}, adapter.pre_tool(self.call("read_file", {"Path": str(other), "EndLine": 5})))

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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake), patch.object(adapter, "verify_in_session", return_value=(False, {})):
            first = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 0})
            second = adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"], "executionNum": 1})
        self.assertEqual({"decision": "continue", "reason": "finish first"}, first)
        self.assertFalse(captured[0]["stop_hook_active"])
        self.assertTrue(captured[1]["stop_hook_active"])
        self.assertEqual({"decision": "continue", "reason": "finish first"}, second)

    def test_no_block_lets_the_agent_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), patch.object(agy_hook_verify, "routed_through_3d", return_value=False):
            self.assertEqual({}, adapter.stop({"conversationId": "c1", "workspacePaths": ["/w"]}))


class UnverifiedReminderTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "c7", "workspacePaths": ["/w"], "executionNum": 0}

    def test_a_3d_routed_session_is_reminded_once_at_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True):
            first = adapter.stop(self.PAYLOAD)
            second = adapter.stop(self.PAYLOAD)
            third = adapter.stop(self.PAYLOAD)
        self.assertEqual("continue", first["decision"])
        self.assertIn("unverified", first["reason"])
        self.assertEqual({}, second)

    def test_other_sessions_and_a_second_execution_are_not_reminded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""):
            with patch.object(agy_hook_verify, "routed_through_3d", return_value=False):
                self.assertEqual({}, adapter.stop(self.PAYLOAD))
            with patch.object(agy_hook_verify, "routed_through_3d", return_value=True):
                self.assertEqual({}, adapter.stop({**self.PAYLOAD, "executionNum": 1}))

    def test_the_gate_block_wins_and_no_run_means_no_reminder(self):
        block = json.dumps({"decision": "block", "reason": "finish first"})
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=block):
            self.assertEqual("finish first", adapter.stop(self.PAYLOAD)["reason"])
        with patch.object(adapter, "run_script", return_value=""), \
                patch("agent_runtime_session.resolve_runtime_evidence", return_value=None):
            self.assertFalse(agy_hook_verify.routed_through_3d(self.PAYLOAD))

    def test_route_and_stop_markers_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)):
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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", side_effect=gate), \
                patch.object(adapter, "verify_in_session", side_effect=[(True, {"decision": "continue", "reason": "fix"}), (True, {})]):
            adapter.stop(self.PAYLOAD)
            adapter.stop(self.PAYLOAD)
        self.assertEqual([False, True], seen)


class InSessionVerificationTests(unittest.TestCase):
    PAYLOAD = {"conversationId": "cv", "workspacePaths": ["/w"], "lastUserInput": "Build a thing", "executionNum": 0}

    def run_stop(self, results, rounds_before=0, can_judge=True, dist=True, fingerprint=None, judge_configured=True):
        import types

        import itertools

        sequence = itertools.chain(fingerprint or ["same"], itertools.repeat((fingerprint or ["same"])[-1]))

        calls = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist") if dist else None
        fake.can_observe = lambda: can_judge
        fake.judge_configured = lambda: judge_configured
        fake.project_fingerprint = lambda project: next(sequence)

        def verify_project(project, request, out, checklist=None, **kw):
            calls.append((request, checklist))
            return [{"id": "a"}], results

        fake.verify_project = verify_project
        fake.feedback_text = lambda r: ("FIX: " + ",".join(x["id"] for x in r if x["verdict"] == "fail")
                                        if any(x["verdict"] == "fail" for x in r) else "")
        fake.remaining_text = lambda r: ("STILL: " + ",".join(x["id"] for x in r if x["verdict"] == "fail")
                                         if any(x["verdict"] == "fail" for x in r) else "")
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            for _ in range(rounds_before):
                adapter.stop(self.PAYLOAD)
            return adapter.stop(self.PAYLOAD), calls, Path(tmp)

    def test_with_a_judge_service_the_local_evidence_is_removed_after_the_round(self):
        import types

        made = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: True
        fake.project_fingerprint = lambda project: "x"
        fake.feedback_text = lambda r: ""
        fake.remaining_text = lambda r: ""

        def verify_project(project, request, out, checklist=None, **kw):
            out.mkdir(parents=True)
            (out / "checklist.json").write_text("[]")
            made.append(out)
            return [{"id": "a"}], [{"id": "a", "verdict": "pass"}]

        fake.verify_project = verify_project
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(agy_hook_verify, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": "http://127.0.0.1:9"}, clear=False), \
                patch.dict(sys.modules, {"verify": fake}):
            adapter.stop(self.PAYLOAD)
            leftovers = [p.exists() for p in made]
        self.assertEqual([False], leftovers, "the checked session must not find its checklist or pictures at home")

    def test_without_a_judge_a_passing_basic_check_still_says_the_rest_is_unverified_once(self):
        ok = [{"id": "loads-clean", "verdict": "pass"}]
        first, calls, tmp = self.run_stop(ok, judge_configured=False)
        self.assertEqual("continue", first["decision"])
        self.assertIn("No model judgement", first["reason"])
        self.assertIn("unverified by this check", first["reason"])

    def test_without_a_judge_basic_failures_are_sent_back_with_the_same_note(self):
        verdict, calls, tmp = self.run_stop([{"id": "input-reaches-controls", "verdict": "fail"}], judge_configured=False)
        self.assertEqual("continue", verdict["decision"])
        self.assertIn("FIX: input-reaches-controls", verdict["reason"])
        self.assertIn("No model judgement", verdict["reason"])

    def test_a_check_that_crashes_is_reported_once_and_never_ends_the_run_unseen(self):
        import types

        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: True
        fake.project_fingerprint = lambda project: "x"

        def boom(*args, **kwargs):
            raise RuntimeError("judge url refused")

        fake.verify_project = boom
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
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

    def test_the_check_is_promised_whenever_a_browser_can_run_it_judge_or_not(self):
        import types

        for judge, observe, expected in ((True, True, True), (True, False, False), (False, True, True)):
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
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: True
        prints = iter(["one", "two", "three"])
        fake.project_fingerprint = lambda project: next(prints)

        def verify_project(project, request, out, checklist=None, **kw):
            calls.append((request, checklist))
            return [{"id": "a"}], [{"id": "a", "verdict": "fail"}]

        fake.verify_project = verify_project
        fake.feedback_text = lambda r: "FIX"
        base = {"conversationId": "cr", "workspacePaths": ["/w"], "executionNum": 0}
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            adapter.stop({**base, "lastUserInput": "first request"})
            adapter.stop({**base, "lastUserInput": "first request"})
            adapter.stop({**base, "lastUserInput": "second request"})
        self.assertEqual([("first request", None), ("first request", [{"id": "a"}]), ("second request", None)], calls)


class PreInvocationTests(unittest.TestCase):
    def test_guidance_is_injected_once_per_conversation(self):
        def fake(name, args, stdin, cwd, env=None):
            return "# Moru Core Workflow Route\n" if name == "workflow.py" else "status: not_found\n"

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
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

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(agy_hook_state, "_verifier", return_value=FakeVerify), \
                patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": "http://127.0.0.1:1"}, clear=False):
            path = Path(tmp) / "conv1.stop.json"
            agy_hook_state.save_state(path, "stop", {"input": "x", "continuations": 1})
            loaded = agy_hook_state.load_state(path, "stop")
            on_disk = list(Path(tmp).iterdir())
        self.assertEqual(1, loaded["continuations"])
        self.assertEqual([], on_disk, "nothing is written where the checked session could rewrite it")
        self.assertIn("conv1.stop", store)

    def test_state_untouched_for_an_hour_is_forgotten(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)):
            path = Path(tmp) / "conv2.stop.json"
            agy_hook_state.save_state(path, "stop", {"input": "x", "continuations": 1})
            self.assertEqual(1, agy_hook_state.load_state(path, "stop")["continuations"])
            with patch.object(agy_hook_state.time, "time", return_value=__import__("time").time() + 3601):
                self.assertEqual({}, agy_hook_state.load_state(path, "stop"))

    def test_a_new_request_after_an_unchanged_route_still_gets_project_entry_once(self):
        def fake(name, args, stdin, cwd, env=None):
            return "unchanged since this session already received it" if name == "workflow.py" else "status: guided\n"

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
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

    def test_step_two_after_full_route_does_not_reinject_entry_or_respawn(self):
        calls = []

        def fake(name, args, stdin, cwd, env=None):
            calls.append((name, args))
            if name == "workflow.py":
                return (
                    "# Moru Core Workflow Route\n"
                    if sum(1 for n, _ in calls if n == "workflow.py") == 1
                    else "unchanged since this session already received it"
                )
            req = args[args.index("--request") + 1]
            if "3D" in req:
                return "guidance:\n- platforms/web/skills/web-3d-interaction/SKILL.md\n"
            return "status: selected\n"

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake), \
                patch.object(adapter, "independent_check_available", return_value=True):
            same = {"conversationId": "c11", "workspacePaths": [tmp], "lastUserInput": "Refactor hooks"}
            step1 = adapter.pre_invocation(same)
            step2 = adapter.pre_invocation(same)
            step3 = adapter.pre_invocation(same)
            self.assertEqual(2, len(calls), "steps 2+ within the same user input must spawn no subprocesses")
            self.assertEqual([{}, {}], [step2, step3])
            self.assertIn("Workflow Route", step1["injectSteps"][0]["systemMessage"]["systemMessage"])
            self.assertIn("status: selected", step1["injectSteps"][0]["systemMessage"]["systemMessage"])

            turn2 = {**same, "lastUserInput": "Now build a 3D scene"}
            next_first = adapter.pre_invocation(turn2)
            next_second = adapter.pre_invocation(turn2)
            self.assertEqual(4, len(calls), "a new user input recomputes route and entry once")
            next_text = next_first["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("web-3d-interaction", next_text)
            self.assertIn("independent check opens the finished page", next_text)
            self.assertEqual({}, next_second)

    def test_autoloaded_workspace_instructions_are_trimmed_while_external_projects_stay_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            external = Path(tmp) / "other"
            workspace.mkdir()
            external.mkdir()
            (workspace / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
            (external / "AGENTS.md").write_text("# agents\n", encoding="utf-8")

            ws_entry = (
                "status: selected\n"
                f"project: {workspace}\n"
                "instruction_files:\n"
                "- AGENTS.md\n"
                "- CLAUDE.md\n"
                "next_steps:\n"
                "- Open the selected project's runtime instruction files before project work.\n"
                "- Run preflight before edits.\n"
            )
            trimmed = adapter._trim_autoloaded_workspace_entry(ws_entry, {"workspacePaths": [str(workspace)]})
            self.assertNotIn("instruction_files:", trimmed)
            self.assertNotIn("CLAUDE.md", trimmed)
            self.assertNotIn("Open the selected project's runtime instruction files", trimmed)
            self.assertIn("- Run preflight before edits.", trimmed)

            ext_entry = ws_entry.replace(str(workspace), str(external))
            untouched = adapter._trim_autoloaded_workspace_entry(ext_entry, {"workspacePaths": [str(workspace)]})
            self.assertIn("instruction_files:", untouched)
            self.assertIn("- AGENTS.md", untouched)
            self.assertIn("Open the selected project's runtime instruction files", untouched)

    def test_required_docs_deliver_in_process_even_when_prompt_guidance_short_circuits(self):
        calls = []

        def fake(name, args, stdin, cwd, env=None):
            calls.append(name)
            return "# Moru Core Workflow Route\n" if name == "workflow.py" else "status: selected\n"

        doc_step = {"injectSteps": [{"systemMessage": {"systemMessage": "REQUIRED DOC BODY"}}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", fake), \
                patch.object(adapter.agy_required_docs_hook, "respond", side_effect=[{}, doc_step, {}]):
            payload = {"conversationId": "c12", "workspacePaths": [tmp], "lastUserInput": "Implement fix"}
            before_start = adapter.pre_invocation(payload)
            after_start = adapter.pre_invocation(payload)
            after_delivery = adapter.pre_invocation(payload)
        self.assertEqual(["workflow.py", "agent-entry.py"], calls)
        self.assertEqual(1, len(before_start["injectSteps"]))
        self.assertEqual([{"systemMessage": {"systemMessage": "REQUIRED DOC BODY"}}], after_start["injectSteps"])
        self.assertEqual({}, after_delivery)


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
        self.assertEqual("run_command|read_file|write_file|edit_file", spec["PreToolUse"][0]["matcher"])


class BackgroundTaskStopSuppressionTests(unittest.TestCase):
    def _write_transcript(self, path: Path, steps: list[dict]) -> None:
        path.write_text("\n".join(json.dumps(step) for step in steps) + "\n", encoding="utf-8")

    def test_non_daemon_running_background_task_defers_stop_without_burning_continuations(self):
        seen = []

        def gate(name, args, stdin, cwd, env=None):
            seen.append(stdin["stop_hook_active"])
            return "" if stdin["stop_hook_active"] else json.dumps({"decision": "block", "reason": "finish first"})

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", side_effect=gate), \
                patch.object(adapter, "verify_in_session", return_value=(True, {})):
            transcript = Path(tmp) / "transcript.jsonl"
            steps = [
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest", "IsDaemon": False}}],
                },
                {
                    "step_index": 2,
                    "source": "TOOL_RESULT",
                    "type": "GENERIC",
                    "status": "RUNNING",
                    "content": "Created At: now\nTool is running as a background task with task id: conv/task-42",
                },
            ]
            self._write_transcript(transcript, steps)
            payload = {
                "conversationId": "cbg",
                "workspacePaths": ["/w"],
                "lastUserInput": "Fix tests",
                "executionNum": 0,
                "transcriptPath": str(transcript),
            }
            while_running = adapter.stop(payload)
            self.assertEqual({}, while_running)
            self.assertEqual([], seen, "stop gate must not run while waiting on background command wakeup")

            steps.append(
                {
                    "step_index": 3,
                    "source": "SYSTEM",
                    "type": "SYSTEM_MESSAGE",
                    "status": "DONE",
                    "content": '[Message] timestamp=now sender=conv/task-42\nTask id "conv/task-42" finished with result:\nok',
                }
            )
            self._write_transcript(transcript, steps)
            after_done = adapter.stop(payload)
            after_cap = adapter.stop(payload)
        self.assertEqual({"decision": "continue", "reason": "finish first"}, after_done)
        self.assertEqual({}, after_cap)
        self.assertEqual([False, True], seen)

    def test_daemon_tasks_quoted_source_text_and_restart_notices_do_not_suppress_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "transcript.jsonl"
            # 1) Daemon background process stays running intentionally and must not suppress final stop.
            self._write_transcript(
                transcript,
                [
                    {
                        "step_index": 1,
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "tool_calls": [{"name": "run_command", "args": {"CommandLine": "npm run dev", "IsDaemon": True}}],
                    },
                    {
                        "step_index": 2,
                        "source": "TOOL_RESULT",
                        "type": "GENERIC",
                        "status": "RUNNING",
                        "content": "Tool is running as a background task with task id: conv/task-dev",
                    },
                    {
                        "step_index": 3,
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "tool_calls": [{"name": "read_file", "args": {"Path": "foo.py"}}],
                    },
                    {
                        "step_index": 4,
                        "source": "TOOL_RESULT",
                        "type": "GENERIC",
                        "status": "DONE",
                        "content": '1: marker = "Tool is running as a background task with task id: conv/task-fake"',
                    },
                ],
            )
            self.assertFalse(agy_hook_state.has_inflight_background_task({"transcriptPath": str(transcript)}))

            # 2) Non-daemon task settled by server restart notice or manage_task cancellation clears in-flight state.
            self._write_transcript(
                transcript,
                [
                    {
                        "step_index": 1,
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "tool_calls": [{"name": "run_command", "args": {"CommandLine": "sleep 30"}}],
                    },
                    {
                        "step_index": 2,
                        "source": "TOOL_RESULT",
                        "type": "GENERIC",
                        "status": "RUNNING",
                        "content": "Tool is running as a background task with task id: conv/task-99",
                    },
                    {
                        "step_index": 3,
                        "source": "SYSTEM",
                        "type": "SYSTEM_MESSAGE",
                        "status": "DONE",
                        "content": "[Notice] All your subagents and background tasks have been stopped due to a server restart.",
                    },
                ],
            )
            self.assertFalse(agy_hook_state.has_inflight_background_task({"transcriptPath": str(transcript)}))


class CliHelpAndWorkflowRulesTests(unittest.TestCase):
    def test_agent_hook_action_help_scopes_flags_to_the_requested_hook(self):
        import subprocess

        review_proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "review", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, review_proc.returncode, review_proc.stderr)
        self.assertIn("--review-outcome", review_proc.stdout)
        self.assertIn("--structure-review-evidence", review_proc.stdout)
        self.assertNotIn("--commit-ready", review_proc.stdout)
        self.assertNotIn("--continue-from", review_proc.stdout)

        start_proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "start", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, start_proc.returncode, start_proc.stderr)
        self.assertIn("--commit-ready", start_proc.stdout)
        self.assertNotIn("--review-outcome", start_proc.stdout)

        top_proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent-hook.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, top_proc.returncode, top_proc.stderr)
        self.assertIn("--commit-ready", top_proc.stdout)
        self.assertIn("--review-outcome", top_proc.stdout)

    def test_workflow_query_accepts_rules_before_or_after_subcommand(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            rules_dir = Path(tmp) / "custom-rules"
            (rules_dir / "docs").mkdir(parents=True)
            (rules_dir / "docs" / "custom-guide.md").write_text(
                "# Custom Rules Guide\n\nxyzzymoruquerytoken unique guidance entry.\n",
                encoding="utf-8",
            )
            for argv in (
                ["--rules", str(rules_dir), "query", "xyzzymoruquerytoken", "--format", "json"],
                ["query", "xyzzymoruquerytoken", "--rules", str(rules_dir), "--format", "json"],
            ):
                with self.subTest(argv=argv):
                    proc = subprocess.run(
                        [sys.executable, str(ROOT / "scripts" / "workflow.py"), *argv],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(0, proc.returncode, proc.stderr)
                    payload = json.loads(proc.stdout)
                    paths = [item["path"] for item in payload.get("results", [])]
                    self.assertEqual(["docs/custom-guide.md"], paths)


class ActionRespondsScopeSkipTests(unittest.TestCase):
    def _init_repo(self, root: Path) -> None:
        import subprocess

        (root / "dist").mkdir(parents=True, exist_ok=True)
        (root / "dist" / "index.html").write_text("<html><body><canvas></canvas></body></html>", encoding="utf-8")
        (root / "index.html").write_text("<html><body><canvas></canvas></body></html>", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)

    def test_skips_headless_film_and_blender_asset_work_outside_page_shell(self):
        import types

        called = []
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: project / "dist"
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: False
        fake.project_fingerprint = lambda project: "fp"
        fake.verify_project = lambda *a, **k: (called.append(a), ([], []))[1]
        fake.feedback_text = lambda r: ""
        fake.remaining_text = lambda r: ""

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            (repo / "tools" / "blender").mkdir(parents=True)
            (repo / "tools" / "blender" / "vault.py").write_text("import bpy\n", encoding="utf-8")
            (repo / "assets").mkdir()
            (repo / "assets" / "vault.glb").write_bytes(b"glTF")

            with patch.object(agy_hook_state, "MARKER_DIR", Path(tmp) / "markers"), \
                    patch.object(adapter, "run_script", return_value=""), \
                    patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                    patch.dict(sys.modules, {"verify": fake}):
                # 1. Headless film request
                v1 = adapter.stop({
                    "conversationId": "cfilm",
                    "workspacePaths": [str(repo)],
                    "lastUserInput": "Render 14 stills on the headless film page and check choreography",
                    "executionNum": 0,
                })
                # 2. Blender asset work where index.html is untouched/outside owned paths
                v2 = adapter.stop({
                    "conversationId": "cblend",
                    "workspacePaths": [str(repo)],
                    "lastUserInput": "Update the vault prop geometry",
                    "executionNum": 0,
                })
                # 3. Request explicitly excluding index.html / page shell
                (repo / "src").mkdir()
                (repo / "src" / "lighting.js").write_text("export const sun = 1;\n", encoding="utf-8")
                v3 = adapter.stop({
                    "conversationId": "cowned",
                    "workspacePaths": [str(repo)],
                    "lastUserInput": "You own: src/lighting.js. Do NOT touch index.html or page shell.",
                    "executionNum": 0,
                })
        self.assertEqual({}, v1)
        self.assertEqual({}, v2)
        self.assertEqual({}, v3)
        self.assertEqual([], called)

    def test_unverified_only_action_responds_reports_once_without_blocking(self):
        import types

        unverified_results = [
            {"id": "loads-clean", "claim": "loads", "verdict": "pass", "reason": "ok"},
            {
                "id": "action-responds",
                "claim": "main action responds",
                "verdict": "fail",
                "basis": "unverified",
                "reason": "unverified: no main action was found to use",
            },
        ]
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: Path("/w/dist")
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: False
        fake.project_fingerprint = lambda project: "fp1"
        fake.verify_project = lambda *a, **k: ([{"id": "action-responds"}], unverified_results)
        fake.feedback_text = lambda r: ""
        fake.remaining_text = lambda r: ""

        with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                patch.object(adapter, "run_script", return_value=""), \
                patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                patch.dict(sys.modules, {"verify": fake}):
            first = adapter.stop({
                "conversationId": "cunv",
                "workspacePaths": ["/w"],
                "lastUserInput": "Add launch button to the interactive UI",
                "executionNum": 0,
            })
            second = adapter.stop({
                "conversationId": "cunv",
                "workspacePaths": ["/w"],
                "lastUserInput": "Add launch button to the interactive UI",
                "executionNum": 1,
            })
        self.assertEqual("continue", first["decision"])
        self.assertIn("Reported unverified items (not blocking)", first["reason"])
        self.assertIn("action-responds", first["reason"])
        self.assertEqual({}, second)

    def test_i3_observer_error_and_malformed_judge_are_reported_not_swallowed(self):
        import types

        observer_failed = [
            {
                "id": "loads-clean",
                "claim": "page loads",
                "verdict": "fail",
                "basis": "unverified",
                "reason": "unverified: observer failed: Chrome exited 1",
            },
        ]
        malformed_judge = [
            {
                "id": "loads-clean",
                "claim": "page loads",
                "verdict": "fail",
                "basis": "unverified",
                "reason": "unverified: the judge gave no answer for this item",
            },
        ]
        for cid, results, needle in (
            ("cobs", observer_failed, "Nothing was independently verified"),
            ("cmal", malformed_judge, "Reported unverified items (not blocking)"),
        ):
            with self.subTest(cid=cid):
                fake = types.ModuleType("verify")
                fake.find_dist = lambda project: Path("/w/dist")
                fake.can_observe = lambda: True
                fake.judge_configured = lambda: True
                fake.project_fingerprint = lambda project: "fp1"
                fake.verify_project = lambda *a, **k: ([{"id": "loads-clean"}], results)
                fake.feedback_text = lambda r: ""
                fake.remaining_text = lambda r: ""
                with tempfile.TemporaryDirectory() as tmp, patch.object(agy_hook_state, "MARKER_DIR", Path(tmp)), \
                        patch.object(adapter, "run_script", return_value=""), \
                        patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                        patch.dict(sys.modules, {"verify": fake}):
                    verdict = adapter.stop({
                        "conversationId": cid,
                        "workspacePaths": ["/w"],
                        "lastUserInput": "Build interactive page",
                        "executionNum": 0,
                    })
                self.assertEqual("continue", verdict.get("decision"), verdict)
                self.assertIn(needle, verdict.get("reason", ""))

    def test_i4_changed_page_shell_verifies_regardless_of_request_wording_or_language(self):
        for rel_path, request in (
            ("src/App.tsx", "Fix props and material render frames"),
            ("assets/app.js", "Update video shot assets"),
            ("scripts/main.ts", "Fix render frame timing"),
            ("index.html", "렌더 머티리얼과 프롭 레이아웃 수정"),
        ):
            with self.subTest(rel_path=rel_path, request=request):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp) / "repo"
                    repo.mkdir()
                    self._init_repo(repo)
                    changed = repo / rel_path
                    changed.parent.mkdir(parents=True, exist_ok=True)
                    changed.write_text("// changed\n", encoding="utf-8")
                    self.assertTrue(
                        agy_hook_verify._should_verify_interactive_page(repo, request),
                        (rel_path, request),
                    )

    def test_n3_out_of_scope_page_shell_changes_are_verified_and_reported(self):
        import types

        self.assertEqual(
            ["src/scene/"],
            agy_hook_verify._explicit_owned_paths("You own: src/scene/. do not touch index.html"),
        )
        for request, changed in (
            ("You own: src/scene/. do not touch index.html", ["src/scene/a.js", "index.html"]),
            ("You own: src/scene/", ["src/scene/a.js", "index.html"]),
            ("You own: src/scene/", ["index.html"]),
        ):
            with self.subTest(request=request, changed=changed):
                with patch.object(agy_hook_verify, "_changed_repo_paths", return_value=changed):
                    self.assertTrue(
                        agy_hook_verify._should_verify_interactive_page(Path("/x"), request)
                    )
        # Even when no built dist/observer is present, out-of-scope shell changes are reported.
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: None
        fake.can_observe = lambda: False
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            (repo / "index.html").write_text("<html><body>modified</body></html>", encoding="utf-8")
            with patch.object(agy_hook_state, "MARKER_DIR", Path(tmp) / "markers"), \
                    patch.object(adapter, "run_script", return_value=""), \
                    patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                    patch.dict(sys.modules, {"verify": fake}):
                verdict = adapter.stop({
                    "conversationId": "cn3-oos",
                    "workspacePaths": [str(repo)],
                    "lastUserInput": "You own: src/scene/",
                    "executionNum": 0,
                })
        self.assertEqual("continue", verdict.get("decision"))
        self.assertIn("Out-of-scope page-shell file(s) changed outside owned paths", verdict.get("reason", ""))
        self.assertIn("index.html", verdict.get("reason", ""))

    def test_n3_clean_working_tree_uses_latest_commit_diff_not_request_wording(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            # Commit 1: modified index.html, clean working tree -> MUST verify even with headless wording.
            (repo / "index.html").write_text("<html><body><h1>v2</h1></body></html>", encoding="utf-8")
            subprocess.run(["git", "add", "index.html"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "touch shell"], cwd=repo, check=True)
            self.assertTrue(
                agy_hook_verify._should_verify_interactive_page(
                    repo, "render a short film with blender"
                )
            )
            # Commit 2: only blender tool file changed, clean working tree -> skip even with UI wording.
            (repo / "tools" / "blender").mkdir(parents=True)
            (repo / "tools" / "blender" / "shot.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "tools/blender/shot.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "blender only"], cwd=repo, check=True)
            self.assertFalse(
                agy_hook_verify._should_verify_interactive_page(repo, "버튼 색 바꿔줘")
            )

    def test_negative_control_interactive_ui_change_with_contradicted_failure_still_blocks(self):
        import types

        contradicted = [
            {
                "id": "action-responds",
                "claim": "main action responds",
                "verdict": "fail",
                "basis": "contradicted",
                "reason": "text and picture unchanged after clicking Launch",
            },
        ]
        fake = types.ModuleType("verify")
        fake.find_dist = lambda project: project / "dist"
        fake.can_observe = lambda: True
        fake.judge_configured = lambda: True
        fake.project_fingerprint = lambda project: "fp2"
        fake.verify_project = lambda *a, **k: ([{"id": "action-responds"}], contradicted)
        fake.feedback_text = lambda r: "FIX: action-responds"
        fake.remaining_text = lambda r: "STILL: action-responds"

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            (repo / "index.html").write_text("<html><body><button>Launch</button></body></html>", encoding="utf-8")
            with patch.object(agy_hook_state, "MARKER_DIR", Path(tmp) / "markers"), \
                    patch.object(adapter, "run_script", return_value=""), \
                    patch.object(agy_hook_verify, "routed_through_3d", return_value=True), \
                    patch.dict(sys.modules, {"verify": fake}):
                verdict = adapter.stop({
                    "conversationId": "cneg",
                    "workspacePaths": [str(repo)],
                    "lastUserInput": "Add Launch button and HUD controls to index.html",
                    "executionNum": 0,
                })
        self.assertEqual({"decision": "continue", "reason": "FIX: action-responds"}, verdict)


if __name__ == "__main__":
    unittest.main()
