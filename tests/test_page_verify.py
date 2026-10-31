from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "page_verify"))
sys.path.insert(0, str(ROOT / "scripts"))

import verify  # noqa: E402

os.environ.setdefault("MORU_VERIFY_EFFECT_LOG", str(Path(tempfile.gettempdir()) / "moru-verify-effect-test.jsonl"))


def write_evidence(directory: Path, **extra) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "00-initial.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (directory / "01-t2s.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    data = {"url": "http://x", "consoleErrors": [], "failedRequests": [], "primaryAction": {"text": "GO"},
            "steps": [{"label": "initial", "seconds": 0, "screenshot": "00-initial.jpg", "text": "READY"},
                      {"label": "t2s", "seconds": 2, "screenshot": "01-t2s.jpg", "text": "RUNNING"}], **extra}
    (directory / "observations.json").write_text(json.dumps(data))


class DeriveTests(unittest.TestCase):
    def test_generic_items_are_kept_and_derived_ids_are_normalised(self):
        answer = json.dumps([
            {"id": "Ship On Pad!", "claim": "A ship rests on a pad.", "phase": "initial", "evidence": ["screenshots"]},
            {"claim": "no id, dropped"},
            {"id": "x", "claim": "bad evidence list", "evidence": ["telepathy"]},
        ])
        items = verify.derive_checklist("request", ask=lambda model, prompt, **kw: f"here:\n{answer}")
        ids = [item["id"] for item in items]
        self.assertEqual(["loads-clean", "action-responds", "input-reaches-controls", "ship-on-pad", "x"], ids)
        self.assertEqual(["screenshots"], items[-1]["evidence"])
        self.assertEqual("derived", items[-1]["source"])

    def test_a_derived_item_may_replace_a_generic_one_without_duplicating_it(self):
        answer = json.dumps([{"id": "loads-clean", "claim": "mine", "evidence": ["console"]}])
        items = verify.derive_checklist("request", ask=lambda *a, **k: answer)
        self.assertEqual(1, [i["id"] for i in items].count("loads-clean"))

    def test_the_prompt_asks_for_the_generic_implied_conditions(self):
        self.assertIn("faces its direction of travel", verify.DERIVE_PROMPT)
        self.assertIn("resting state before the action differs", verify.DERIVE_PROMPT)

    def test_attitude_is_a_derivation_and_code_review_condition(self):
        self.assertIn("rises or descends vertically keeps its body level", verify.DERIVE_PROMPT)
        self.assertIn("stand on its tail, dive nose-first", verify.DERIVE_PROMPT)
        self.assertIn("pitch and roll applied during vertical rises and descents", verify.CODE_JUDGE_PROMPT)

    def test_a_vehicle_request_always_gets_the_attitude_item_even_if_the_model_omits_it(self):
        omitted = json.dumps([{"id": "ship-on-pad", "claim": "A ship rests on a pad.", "evidence": ["screenshots"]}])
        request = "A spaceship takes off, flies a circuit and lands"
        items = verify.derive_checklist(request, ask=lambda *a, **k: omitted)
        menu = [i for i in items if i["source"] == "menu"]
        self.assertEqual(["body-level-in-vertical-phases"], [i["id"] for i in menu])
        self.assertIn("code", menu[0]["evidence"])

    def test_the_attitude_item_is_not_added_twice_or_to_unrelated_requests(self):
        covered = json.dumps([{"id": "level-body", "claim": "The pitch stays near zero.", "evidence": ["code"]}])
        items = verify.derive_checklist("A spaceship takes off", ask=lambda *a, **k: covered)
        self.assertEqual([], [i for i in items if i["source"] == "menu"])
        plain = verify.derive_checklist("A pricing page with three plans", ask=lambda *a, **k: "[]")
        self.assertEqual([], [i for i in plain if i["source"] == "menu"])

    def test_an_answer_without_json_is_an_error(self):
        with self.assertRaises(ValueError):
            verify.derive_checklist("request", ask=lambda *a, **k: "no list here")


class JudgeTests(unittest.TestCase):
    ITEMS = [{"id": "a", "claim": "A", "phase": "any", "evidence": ["screenshots"], "source": "derived"},
             {"id": "b", "claim": "B", "phase": "any", "evidence": ["text"], "source": "derived"},
             {"id": "c", "claim": "C", "phase": "any", "evidence": ["console"], "source": "derived"}]

    def judge(self, answer: list, **extra) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(Path(tmp), **extra)
            return verify.judge(self.ITEMS, Path(tmp), ask=lambda *a, **k: json.dumps(answer))

    def test_a_fail_must_cite_a_step_that_exists(self):
        results = self.judge([
            {"id": "a", "verdict": "fail", "reason": "bad", "contradicting_step": "t2s"},
            {"id": "b", "verdict": "fail", "reason": "no evidence at all", "contradicting_step": ""},
            {"id": "c", "verdict": "pass", "reason": "ok"},
        ])
        verdicts = {r["id"]: r["verdict"] for r in results}
        self.assertEqual({"a": "fail", "b": "unobserved", "c": "pass"}, verdicts)
        self.assertIn("downgraded", results[1]["reason"])

    def test_a_missing_or_unknown_verdict_is_unobserved_never_a_pass(self):
        results = self.judge([{"id": "a", "verdict": "great", "reason": "x"}])
        self.assertEqual(["unobserved"] * 3, [r["verdict"] for r in results])

    def test_an_observer_failure_makes_everything_unobserved(self):
        results = self.judge([{"id": i["id"], "verdict": "pass", "reason": "ok"} for i in self.ITEMS],
                             observerError="chrome missing")
        self.assertEqual({"unobserved"}, {r["verdict"] for r in results})
        self.assertIn("chrome missing", results[0]["reason"])

    def test_the_judge_sees_every_screenshot_and_the_console(self):
        captured = {}

        def ask(model, content, **kw):
            captured["content"] = content
            return json.dumps([])

        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(Path(tmp), consoleErrors=["ReferenceError: THREE is not defined"])
            verify.judge(self.ITEMS, Path(tmp), ask=ask)
        images = [part for part in captured["content"] if part["type"] == "image_url"]
        self.assertEqual(2, len(images))
        self.assertIn("THREE is not defined", captured["content"][0]["text"])

    def test_a_check_that_could_not_be_confirmed_is_a_failure_with_its_reason_and_there_is_no_third_outcome(self):
        raw = [{"id": "a", "claim": "A holds.", "verdict": "fail", "reason": "t2s shows otherwise"},
               {"id": "b", "claim": "B holds.", "verdict": "unobserved", "reason": "no step shows the action used"},
               {"id": "c", "claim": "C holds.", "verdict": "pass", "reason": "ok"}]
        results = verify.finalize(raw, {"inputProbes": {}})
        self.assertEqual({"pass", "fail"}, {r["verdict"] for r in results})
        self.assertEqual(["contradicted", "unverified"], [r["basis"] for r in results if r["verdict"] == "fail"])
        text = verify.feedback_text(results)
        self.assertIn("- a: A holds. Observed: t2s shows otherwise", text)
        self.assertIn("- b: B holds. Could not be confirmed (unverified: no step shows the action used)", text)
        self.assertNotIn("C holds", text)
        self.assertEqual("", verify.feedback_text([results[2]]))

    def test_items_skipped_because_a_basic_check_failed_fail_but_are_not_asked_to_be_fixed(self):
        results = [{"id": "x", "claim": "X.", "verdict": "fail", "basis": "contradicted", "reason": "console error"},
                   {"id": "y", "claim": "Y.", "verdict": "fail", "basis": "unchecked", "reason": "not checked yet"}]
        text = verify.feedback_text(results)
        self.assertIn("- x: X. Observed: console error", text)
        self.assertNotIn("- y:", text)
        self.assertIn("Not checked yet because a basic check failed: y.", text)

    def test_remaining_text_asks_for_an_honest_report_not_another_fix(self):
        results = [{"id": "a", "claim": "A holds.", "verdict": "fail", "reason": "t6s shows otherwise"},
                   {"id": "b", "claim": "B holds.", "verdict": "pass", "reason": "ok"}]
        text = verify.remaining_text(results)
        self.assertIn("still reports these items failing", text)
        self.assertIn("- a: A holds. Observed: t6s shows otherwise", text)
        self.assertIn("Do not call the page complete", text)
        self.assertNotIn("B holds", text)
        self.assertEqual("", verify.remaining_text([results[1]]))

    def test_report_table_lists_each_verdict(self):
        table = verify.render([{"id": "a", "verdict": "fail", "reason": "r"}])
        self.assertIn("| a | fail | r |", table)


class TimelineCitationTests(unittest.TestCase):
    ITEM = {"id": "smooth", "claim": "Speed changes smoothly.", "phase": "during_action", "evidence": ["text"], "source": "derived"}

    def judged(self, evidence, cited):
        answer = json.dumps([{"id": "smooth", "verdict": "fail", "reason": "speed fell from 130 to 0 in half a second",
                              "contradicting_step": cited}])
        return verify.judge_loaded([self.ITEM], evidence, {}, ask=lambda *a, **k: answer)[0]

    def test_a_timeline_time_counts_as_a_contradicting_citation_when_a_timeline_exists(self):
        evidence = {"steps": [{"label": "initial", "seconds": 0, "screenshot": "x"}], "timeline": [{"t": 26.6, "text": "SPEED 0"}]}
        self.assertEqual("fail", self.judged(evidence, "timeline@26.6s")["verdict"])

    def test_without_a_timeline_or_a_real_step_the_fail_is_not_accepted(self):
        evidence = {"steps": [{"label": "initial", "seconds": 0, "screenshot": "x"}]}
        self.assertEqual("unobserved", self.judged(evidence, "timeline@26.6s")["verdict"])
        self.assertEqual("unobserved", self.judged(evidence, "made-up-step")["verdict"])


class LocalCodexJudgeTests(unittest.TestCase):
    def run_chat(self, content, returncode=0, answer="[]"):
        calls = {}

        def fake_run(command, **kwargs):
            calls["command"], calls["input"] = command, kwargs["input"]
            out = Path(command[command.index("-o") + 1])
            if answer is not None:
                out.write_text(answer)
            calls["images"] = [Path(command[i + 1]).read_bytes() for i, a in enumerate(command) if a == "-i"]
            return subprocess.CompletedProcess(command, returncode, "", "boom" if returncode else "")

        with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_BACKEND": "codex", "MORU_VERIFY_MODEL": "",
                                                     "MORU_VERIFY_CONFIG": "/nonexistent"}, clear=False), \
                unittest.mock.patch.object(verify.subprocess, "run", fake_run):
            result = verify.chat("ignored/model", content)
        return result, calls

    def test_the_codex_judge_runs_with_no_tools_config_or_session(self):
        result, calls = self.run_chat("judge this")
        command = calls["command"]
        self.assertEqual("[]", result)
        for flag in ("--sandbox", "read-only", "--ignore-user-config", "--ignore-rules", "--ephemeral", "-m", "gpt-6.1-terra"):
            self.assertIn(flag, command)
        self.assertEqual("-", command[-1], "the prompt goes through stdin, never the command line")
        self.assertIn("judge this", calls["input"])
        self.assertIn("Do not run commands", calls["input"])

    def test_images_are_attached_in_order_and_marked_in_the_prompt(self):
        import base64

        jpeg = lambda raw: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode()}}
        content = [{"type": "text", "text": "Screenshot: initial"}, jpeg(b"one"), {"type": "text", "text": "Screenshot: t3s"}, jpeg(b"two")]
        _, calls = self.run_chat(content)
        self.assertEqual([b"one", b"two"], calls["images"])
        self.assertLess(calls["input"].index("[image 1]"), calls["input"].index("[image 2]"))
        self.assertLess(calls["input"].index("Screenshot: initial"), calls["input"].index("[image 1]"))

    def test_a_failed_or_empty_judgement_raises_instead_of_passing_anything(self):
        with self.assertRaises(RuntimeError):
            self.run_chat("x", returncode=1)
        with self.assertRaises(RuntimeError):
            self.run_chat("x", answer="  ")

    def test_codex_needs_no_key_and_no_paid_permission_but_must_be_installed(self):
        env = {"MORU_VERIFY_JUDGE_URL": "", "MORU_VERIFY_BACKEND": "codex", "MORU_VERIFY_ALLOW_PAID": "",
               "OPENROUTER_API_KEY": "", "MORU_VERIFY_CONFIG": "/nonexistent"}
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            with unittest.mock.patch.object(verify, "codex_available", return_value=True):
                self.assertTrue(verify.can_judge())
            with unittest.mock.patch.object(verify, "codex_available", return_value=False):
                self.assertFalse(verify.can_judge())
                with self.assertRaises(RuntimeError):
                    verify.require_backend()


class JudgeSelectionTests(unittest.TestCase):
    def settings(self, env=None, saved=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verify.json"
            if saved is not None:
                path.write_text(json.dumps(saved))
            base = {"MORU_VERIFY_BACKEND": "", "MORU_VERIFY_MODEL": "", "MORU_VERIFY_EFFORT": "", "MORU_VERIFY_JUDGE_URL": "",
                    "MORU_VERIFY_CONFIG": str(path)}
            with unittest.mock.patch.dict("os.environ", {**base, **(env or {})}, clear=False):
                return verify.judge_settings(), verify.judge_configured(), verify.can_judge()

    def test_nothing_is_chosen_by_default_even_if_codex_and_a_key_exist(self):
        with unittest.mock.patch.object(verify, "codex_available", return_value=True):
            settings, configured, can = self.settings({"OPENROUTER_API_KEY": "present"})
        self.assertEqual("none", settings["backend"])
        self.assertFalse(configured)
        self.assertFalse(can)

    def test_a_saved_choice_applies_and_the_environment_overrides_it_for_one_run(self):
        saved = {"backend": "codex", "model": "cheap-model", "effort": "low"}
        with unittest.mock.patch.object(verify, "codex_available", return_value=True):
            settings, configured, _ = self.settings(saved=saved)
            self.assertEqual({"backend": "codex", "model": "cheap-model", "effort": "low"}, settings)
            self.assertTrue(configured)
            settings, configured, _ = self.settings({"MORU_VERIFY_BACKEND": "none", "MORU_VERIFY_MODEL": "other"}, saved=saved)
            self.assertEqual("none", settings["backend"])
            self.assertEqual("other", settings["model"])
            self.assertFalse(configured)

    def test_an_unknown_backend_or_a_broken_file_means_no_judge(self):
        self.assertEqual("none", self.settings({"MORU_VERIFY_BACKEND": "something"})[0]["backend"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "verify.json"
            bad.write_text("{not json")
            with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_CONFIG": str(bad), "MORU_VERIFY_BACKEND": ""}, clear=False):
                self.assertEqual("none", verify.judge_settings()["backend"])

    def test_the_chosen_model_reaches_the_codex_command(self):
        seen = {}

        def fake_run(command, **kwargs):
            seen["model"] = command[command.index("-m") + 1]
            Path(command[command.index("-o") + 1]).write_text("[]")
            return subprocess.CompletedProcess(command, 0, "", "")

        env = {"MORU_VERIFY_BACKEND": "codex", "MORU_VERIFY_MODEL": "cheap-model", "MORU_VERIFY_CONFIG": "/nonexistent"}
        with unittest.mock.patch.dict("os.environ", env, clear=False), unittest.mock.patch.object(verify.subprocess, "run", fake_run):
            verify.chat("ignored", "hi")
        self.assertEqual("cheap-model", seen["model"])


class NoJudgeModeTests(unittest.TestCase):
    def test_basic_checks_run_without_any_model_and_pass_or_fail_on_their_own_evidence(self):
        items = [dict(i) for i in verify.GENERIC_ITEMS]
        clean = {"primaryAction": {"text": "GO"}, "consoleErrors": [], "steps": [{"label": "a"}, {"label": "b"}],
                 "inputProbes": {"primary": {"x": 1, "y": 2, "reaches": True, "by": None, "text": "", "invisible": False}}}
        results = verify.finalize(verify.basic_results(items, clean, []), clean)
        self.assertEqual({"pass"}, {r["verdict"] for r in results})
        broken = {**clean, "consoleErrors": ["boom"], "steps": [{"label": "a"}, {"label": "b"}]}
        failing = verify.floor_results(items, broken)
        results = verify.finalize(verify.basic_results(items, broken, failing), broken)
        self.assertEqual("fail", next(r for r in results if r["id"] == "loads-clean")["verdict"])
        none = {**clean, "primaryAction": None}
        results = verify.finalize(verify.basic_results(items, none, []), none)
        self.assertEqual("unverified", next(r for r in results if r["id"] == "action-responds")["basis"])

    def test_each_check_leaves_one_local_line_with_backend_counts_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "effect.jsonl"
            results = [{"id": "a", "verdict": "pass"}, {"id": "b", "verdict": "fail", "basis": "unverified"}]
            with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_EFFECT_LOG": str(log), "MORU_VERIFY_BACKEND": "codex",
                                                         "MORU_VERIFY_CONFIG": "/nonexistent"}, clear=False):
                verify.log_round([], results, True, 12.4)
            line = json.loads(log.read_text().strip())
        self.assertEqual({"backend": "codex", "judged": True, "seconds": 12, "failing": ["b"],
                          "counts": {"pass": 1, "contradicted": 0, "unverified": 1, "unchecked": 0}},
                         {k: line[k] for k in ("backend", "judged", "seconds", "failing", "counts")})


class PaidCallsAreOffByDefaultTests(unittest.TestCase):
    def test_a_key_alone_never_turns_paid_calls_on(self):
        env = {"MORU_VERIFY_JUDGE_URL": "", "MORU_VERIFY_BACKEND": "openrouter", "MORU_VERIFY_ALLOW_PAID": "",
               "OPENROUTER_API_KEY": "present"}
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            self.assertFalse(verify.can_judge())
            with unittest.mock.patch.object(verify, "open_provider_request", side_effect=AssertionError("network used")):
                with self.assertRaises(RuntimeError) as caught:
                    verify.chat("any/model", "hi")
        self.assertIn("MORU_VERIFY_ALLOW_PAID=1", str(caught.exception))

    def test_explicit_permission_and_a_key_allow_it(self):
        env = {"MORU_VERIFY_JUDGE_URL": "", "MORU_VERIFY_BACKEND": "openrouter", "MORU_VERIFY_ALLOW_PAID": "1",
               "OPENROUTER_API_KEY": "present"}
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            self.assertTrue(verify.can_judge())

    def test_the_judge_service_refuses_to_start_without_permission(self):
        import judge_service

        env = {"MORU_VERIFY_BACKEND": "openrouter", "MORU_VERIFY_ALLOW_PAID": "", "OPENROUTER_API_KEY": "present"}
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            with self.assertRaises(RuntimeError):
                judge_service.main(["--token-file", "/nonexistent", "--port", "0"])


class MobileAndTimelineTests(unittest.TestCase):
    def test_the_touch_viewport_look_is_merged_as_mobile_steps_with_its_probes(self):
        def fake_observe(url, out, viewport, seconds):
            out.mkdir(parents=True, exist_ok=True)
            (out / "00-initial.jpg").write_bytes(b"\xff\xd8\xff\xd9")
            (out / "observations.json").write_text(json.dumps({
                "steps": [{"label": "initial", "seconds": 0, "screenshot": "00-initial.jpg", "text": "READY", "overflowX": 0}],
                "inputProbes": {"primary": {"x": 1, "y": 2, "reaches": False, "by": "div.sheet", "text": "", "invisible": True}},
                "consoleErrors": ["boom"]}))

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(verify, "observe", fake_observe):
            out = Path(tmp)
            evidence = {"steps": [{"label": "initial"}], "consoleErrors": []}
            verify.observe_mobile("http://x", out, evidence)
            self.assertTrue((out / "m-00-initial.jpg").is_file())
        self.assertEqual(["initial", "mobile-initial"], [s["label"] for s in evidence["steps"]])
        self.assertEqual(["boom"], evidence["consoleErrors"])
        self.assertIn("mobile primary", verify.invisible_blockers(evidence)[0])

    def test_a_failed_touch_look_is_recorded_not_raised(self):
        def broken(*args, **kwargs):
            raise RuntimeError("no chrome")

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(verify, "observe", broken):
            evidence = {"steps": [], "consoleErrors": []}
            verify.observe_mobile("http://x", Path(tmp), evidence)
        self.assertIn("no chrome", evidence["mobileError"])

    def test_the_timeline_keeps_only_changes_and_the_observer_samples_it(self):
        evidence = {"timeline": [{"t": 1, "text": "ALT 1"}, {"t": 1.5, "text": "ALT 1"}, {"t": 2, "text": "ALT 5"}]}
        self.assertEqual("- 1s: ALT 1\n- 2s: ALT 5", verify.timeline_text(evidence))
        self.assertEqual("(none)", verify.timeline_text({}))
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        for needle in ("evidence.timeline", "setInterval", "const brief", "after-action"):
            self.assertIn(needle, source)


class InputReachTests(unittest.TestCase):
    ITEMS = [{"id": "input-reaches-controls", "claim": "c", "phase": "any", "evidence": ["input"], "source": "generic"}]
    BLOCKED = {"inputProbes": {"canvasRunning": [{"x": 420, "y": 520, "reaches": False, "by": "div.shortcut-row",
                                                  "text": "Pause / Resume", "invisible": True}]}}
    CLEAR = {"inputProbes": {"primary": {"x": 1, "y": 2, "reaches": True, "by": None, "text": "", "invisible": False},
                             "canvasInitial": [{"x": 5, "y": 5, "reaches": True, "by": None, "text": "", "invisible": False}]}}

    def test_an_invisible_element_over_the_scene_or_the_main_action_fails_without_a_model(self):
        failing = verify.floor_results(self.ITEMS, {"steps": [], **self.BLOCKED})
        self.assertEqual(["fail"], [r["verdict"] for r in failing])
        self.assertIn("invisible <div.shortcut-row>", failing[0]["reason"])

    def test_a_visible_overlay_is_left_to_the_judge_and_clear_probes_pass(self):
        visible = {"inputProbes": {"primary": {"x": 1, "y": 2, "reaches": False, "by": "div.splash", "text": "Start", "invisible": False}}}
        self.assertEqual([], verify.floor_results(self.ITEMS, {"steps": [], **visible}))
        pending = [{**self.ITEMS[0], "verdict": "unobserved", "reason": "judge"}]
        self.assertEqual("pass", verify.settle_input_items(pending, self.CLEAR)[0]["verdict"])
        self.assertEqual("fail", verify.settle_input_items(pending, self.BLOCKED)[0]["verdict"])
        self.assertEqual("unobserved", verify.settle_input_items(pending, {})[0]["verdict"])

    def test_the_observer_probes_hits_and_does_a_real_drag_and_wheel_and_the_menu_asks_for_it(self):
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        for needle in ("elementFromPoint", "pointer-drag-before", "pointer-drag-after", "mouseWheel", "inputProbes.primary"):
            self.assertIn(needle, source)
        items = verify.ensure_menu_items("A page with orbit and zoom camera controls", [])
        self.assertIn("scene-follows-drag-and-wheel", [i["id"] for i in items])
        kept = verify.select_steps([{"label": f"late-t{i}s"} for i in range(8)] + [{"label": "pointer-drag-after"}] * 4)
        self.assertTrue(any(s["label"].startswith("pointer-") for s in kept))
        many = [{"label": "initial"}] + [{"label": f"late-t{i}s"} for i in range(9)] + [{"label": "mobile-initial"}, {"label": "mobile-after-action"}]
        self.assertEqual(["mobile-initial", "mobile-after-action"],
                         [s["label"] for s in verify.select_steps(many) if s["label"].startswith("mobile-")],
                         "the touch-viewport pictures must reach the judge, or a mobile claim can never be judged")


class CodeEvidenceTests(unittest.TestCase):
    ITEM = {"id": "faces", "claim": "front faces travel", "phase": "any", "evidence": ["code"], "source": "derived"}

    def test_collect_source_skips_dependencies_builds_and_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("src/a.js", "node_modules/x/i.js", "dist/b.js", "tests/c.test.js", "src/d.test.js", "src/notes.txt"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("line one\nline two\n")
            source = verify.collect_source(root)
        self.assertIn("=== src/a.js\n1: line one\n2: line two", source)
        for skipped in ("node_modules", "dist/", "c.test", "d.test", "notes.txt"):
            self.assertNotIn(skipped, source)

    def test_collect_source_leaves_out_ignored_files_secrets_and_links_out_of_the_project(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("local.js\n")
            for rel in ("src/a.js", "local.js", "src/api-secret.js", ".env.js"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("keep me\n")
            (Path(outside) / "out.js").write_text("outside\n")
            (root / "src" / "link.js").symlink_to(Path(outside) / "out.js")
            source = verify.collect_source(root)
        self.assertIn("=== src/a.js", source)
        for leaked in ("local.js", "api-secret", ".env", "link.js", "outside"):
            self.assertNotIn(leaked, source)

    def test_a_code_fail_must_cite_file_and_line(self):
        cited = json.dumps([{"id": "faces", "verdict": "fail", "reason": "reversed", "evidence": "flight.js:244 matrix.lookAt(o, t)"}])
        bare = json.dumps([{"id": "faces", "verdict": "fail", "reason": "looks wrong", "evidence": ""}])
        self.assertEqual("fail", verify.judge_code([self.ITEM], "x", ask=lambda *a, **k: cited)["faces"]["verdict"])
        self.assertEqual("unobserved", verify.judge_code([self.ITEM], "x", ask=lambda *a, **k: bare)["faces"]["verdict"])

    def test_only_items_that_name_code_are_sent_and_empty_source_judges_nothing(self):
        screens = {**self.ITEM, "id": "pic", "evidence": ["screenshots"]}
        self.assertEqual({}, verify.judge_code([screens], "src", ask=lambda *a, **k: "[]"))
        self.assertEqual({}, verify.judge_code([self.ITEM], "   ", ask=lambda *a, **k: "[]"))

    def test_combine_lets_a_cited_fail_win_and_either_pass_beat_unobserved(self):
        base = [{"id": "faces", "verdict": "unobserved", "reason": "sparse screens"},
                {"id": "rest", "verdict": "pass", "reason": "initial looks idle"},
                {"id": "plain", "verdict": "pass", "reason": "ok"}]
        code = {"faces": {"verdict": "fail", "reason": "reversed", "evidence": "f.js:1"},
                "rest": {"verdict": "unobserved", "reason": "n/a", "evidence": ""}}
        merged = {r["id"]: r for r in verify.combine(base, code)}
        self.assertEqual("fail", merged["faces"]["verdict"])
        self.assertIn("code: reversed [f.js:1]", merged["faces"]["reason"])
        self.assertEqual("pass", merged["rest"]["verdict"])
        self.assertEqual(base[2], merged["plain"])

    def test_derivation_may_name_code_evidence(self):
        answer = json.dumps([{"id": "faces", "claim": "c", "evidence": ["code", "screenshots"]}])
        items = verify.derive_checklist("r", ask=lambda *a, **k: answer)
        self.assertEqual(["code", "screenshots"], items[-1]["evidence"])
        self.assertIn("code", verify.DERIVE_PROMPT)


class FloorTests(unittest.TestCase):
    ITEMS = [{"id": "loads-clean", "claim": "c", "phase": "any", "evidence": ["console"], "source": "generic"},
             {"id": "action-responds", "claim": "a", "phase": "any", "evidence": ["text"], "source": "generic"},
             {"id": "other", "claim": "o", "phase": "any", "evidence": ["screenshots"], "source": "derived"}]

    def evidence(self, **extra):
        steps = [{"label": "initial", "seconds": 0, "text": "READY"}, {"label": "late-t75s", "seconds": 75, "text": "READY"}]
        return {"consoleErrors": [], "primaryAction": {"text": "GO"}, "secondaryControls": [], "steps": steps, **extra}

    def test_a_console_error_fails_the_load_check_without_a_model(self):
        failing = verify.floor_results(self.ITEMS, self.evidence(consoleErrors=["ReferenceError: THREE is not defined"],
                                                                  steps=[{"label": "initial", "seconds": 0, "text": "READY"},
                                                                         {"label": "t6s", "seconds": 6, "text": "RUNNING"}]))
        self.assertEqual(["loads-clean"], [f["id"] for f in failing])
        self.assertIn("THREE is not defined", failing[0]["reason"])

    def test_text_that_never_changes_after_the_main_action_fails_the_action_check(self):
        failing = verify.floor_results(self.ITEMS, self.evidence())
        self.assertEqual(["action-responds"], [f["id"] for f in failing])
        self.assertIn("late-t75s", failing[0]["reason"])

    def test_a_canvas_only_change_is_not_called_unresponsive(self):
        steps = [{"label": "initial", "seconds": 0, "text": "READY", "shotHash": "a"},
                 {"label": "t6s", "seconds": 6, "text": "READY", "shotHash": "b"}]
        self.assertEqual([], verify.floor_results(self.ITEMS, self.evidence(steps=steps)))

    def test_text_and_picture_both_unchanged_is_unresponsive(self):
        steps = [{"label": "initial", "seconds": 0, "text": "READY", "shotHash": "a"},
                 {"label": "t6s", "seconds": 6, "text": "READY", "shotHash": "a"}]
        failing = verify.floor_results(self.ITEMS, self.evidence(steps=steps))
        self.assertEqual(["action-responds"], [f["id"] for f in failing])
        self.assertIn("picture", failing[0]["reason"])

    def test_the_observer_hashes_each_screenshot_and_can_observe_checks_node_and_a_browser(self):
        self.assertIn("shotHash", (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text())
        with unittest.mock.patch("shutil.which", return_value=None):
            self.assertFalse(verify.can_observe())

    def test_a_responsive_clean_page_has_no_floor_failure(self):
        steps = [{"label": "initial", "seconds": 0, "text": "READY"}, {"label": "t6s", "seconds": 6, "text": "TAKEOFF"}]
        self.assertEqual([], verify.floor_results(self.ITEMS, self.evidence(steps=steps)))

    def test_without_a_primary_action_nothing_is_called_unresponsive(self):
        self.assertEqual([], verify.floor_results(self.ITEMS, self.evidence(primaryAction=None)))

    def test_the_fingerprint_changes_only_when_the_built_page_or_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            (root / "src").mkdir()
            (root / "dist" / "index.html").write_text("<html>1</html>")
            (root / "src" / "a.js").write_text("one")
            first = verify.project_fingerprint(root)
            self.assertEqual(first, verify.project_fingerprint(root))
            (root / "src" / "a.js").write_text("two")
            self.assertNotEqual(first, verify.project_fingerprint(root))


class CheaperEvidenceTests(unittest.TestCase):
    def steps(self, controls=8, late=7):
        out = [{"label": "initial", "seconds": 0}]
        out += [{"label": f"default-view-t{n}s", "seconds": n} for n in (3, 6, 10)]
        out += [{"label": f"control-c{n}", "seconds": 11 + n} for n in range(controls)]
        out += [{"label": f"late-t{n}s", "seconds": n} for n in range(14, 14 + late)]
        return out

    def test_the_image_selection_is_capped_and_keeps_the_start_default_view_and_end(self):
        steps = self.steps()
        chosen = verify.select_steps(steps)
        self.assertLessEqual(len(chosen), verify.MAX_IMAGES)
        labels = [s["label"] for s in chosen]
        for must in ("initial", "default-view-t3s", "default-view-t10s", steps[-1]["label"]):
            self.assertIn(must, labels)

    def test_a_short_timeline_is_sent_whole(self):
        steps = self.steps(controls=2, late=2)
        self.assertEqual(steps, verify.select_steps(steps))

    def test_items_that_need_no_screenshot_send_no_image(self):
        sent = {}

        def ask(model, content, **kw):
            sent["images"] = [p for p in content if p["type"] == "image_url"]
            return "[]"

        text_only = [{"id": "t", "claim": "c", "phase": "any", "evidence": ["text", "console"], "source": "derived"}]
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(Path(tmp))
            verify.judge(text_only, Path(tmp), ask=ask)
        self.assertEqual([], sent["images"])

    def test_items_that_need_screenshots_send_a_bounded_set(self):
        sent = {}

        def ask(model, content, **kw):
            sent["images"] = [p for p in content if p["type"] == "image_url"]
            return "[]"

        shots = [{"id": "s", "claim": "c", "phase": "any", "evidence": ["screenshots"], "source": "derived"}]
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(Path(tmp))
            verify.judge(shots, Path(tmp), ask=ask)
        self.assertEqual(2, len(sent["images"]))

    def test_the_observer_ends_at_rest_and_keeps_few_small_screenshots(self):
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        for needle in ("endedAtRest = true", "restKey", "quality: 45", "width: 1024, height: 640", ".slice(0, 5)"):
            self.assertIn(needle, source)


class RemoteJudgeTests(unittest.TestCase):
    def serve(self, derive, judge):
        import threading
        from http.server import ThreadingHTTPServer

        import judge_service

        server = ThreadingHTTPServer(("127.0.0.1", 0), judge_service.make_handler("tok", derive=derive, judge=judge))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_derive_and_judge_round_trip_without_a_local_key(self):
        url = self.serve(lambda request: [{"id": "x", "claim": request, "phase": "any", "evidence": ["text"], "source": "derived"}],
                         lambda items, evidence, images: [{**items[0], "verdict": "pass", "reason": "ok"}])
        with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": url, "MORU_VERIFY_JUDGE_TOKEN": "tok"}, clear=False):
            items = verify.derive_any("make a page")
            with tempfile.TemporaryDirectory() as tmp:
                write_evidence(Path(tmp))
                results = verify.judge_any(items, Path(tmp))
            self.assertTrue(verify.can_judge())
        self.assertEqual("make a page", items[0]["claim"])
        self.assertEqual("pass", results[0]["verdict"])

    def test_a_wrong_token_is_refused(self):
        import urllib.error

        url = self.serve(lambda request: [], lambda *a: [])
        with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": url, "MORU_VERIFY_JUDGE_TOKEN": "nope"}, clear=False):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                verify.derive_any("x")
        self.assertEqual(401, caught.exception.code)

    def test_the_service_can_keep_what_it_judged_outside_the_agent_session(self):
        import base64
        import judge_service

        with tempfile.TemporaryDirectory() as tmp:
            body = {"items": [{"id": "x"}], "evidence": {"steps": []}, "images": {"00-initial.jpg": base64.b64encode(b"jpg").decode()}}
            judge_service.keep_round(Path(tmp), body, [{"id": "x", "verdict": "pass"}])
            kept = sorted(p.name for p in next(Path(tmp).iterdir()).iterdir())
        self.assertEqual(["00-initial.jpg", "evidence.json", "items.json", "results.json"], kept)

    def test_the_url_a_container_uses_to_reach_its_host_is_allowed(self):
        with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": "http://host.docker.internal:1"}, clear=False):
            with self.assertRaises(OSError):  # refused by the network, not by the guard
                verify.remote_call("/derive", {"request": "x"})

    def test_plain_http_to_a_remote_host_is_refused_before_anything_is_sent(self):
        for url in ("http://judge.example.com:8765", "ftp://127.0.0.1/x"):
            with unittest.mock.patch.dict("os.environ", {"MORU_VERIFY_JUDGE_URL": url}, clear=False):
                with self.assertRaises(RuntimeError):
                    verify.remote_call("/derive", {"request": "x"})

    def test_the_service_keeps_hook_state_and_the_token_is_never_an_argument(self):
        url = self.serve(lambda request: [], lambda *a: [])
        env = {"MORU_VERIFY_JUDGE_URL": url, "MORU_VERIFY_JUDGE_TOKEN": "tok"}
        with unittest.mock.patch.dict("os.environ", env, clear=False):
            self.assertIsNone(verify.remote_call("/state", {"op": "get", "key": "c.verify"})["value"])
            verify.remote_call("/state", {"op": "put", "key": "c.verify", "value": {"rounds": 1}})
            self.assertEqual({"rounds": 1}, verify.remote_call("/state", {"op": "get", "key": "c.verify"})["value"])
            verify.remote_call("/state", {"op": "put", "key": "c.verify", "value": None})
            self.assertIsNone(verify.remote_call("/state", {"op": "get", "key": "c.verify"})["value"])
        import judge_service

        source = Path(judge_service.__file__).read_text()
        self.assertNotIn('"--token"', source)
        self.assertIn("--token-file", source)

    def test_without_a_service_or_a_key_nothing_can_judge(self):
        env = {"MORU_VERIFY_JUDGE_URL": "", "MORU_VERIFY_BACKEND": "openrouter", "OPENROUTER_API_KEY": ""}
        with unittest.mock.patch.dict("os.environ", env, clear=False), \
                unittest.mock.patch.object(verify, "api_key", side_effect=RuntimeError("no key")):
            self.assertFalse(verify.can_judge())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ObserverTests(unittest.TestCase):
    def test_the_observer_shows_the_default_view_first_retries_a_swallowed_click_and_runs_long(self):
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        self.assertLess(source.index("default-view-t"), source.index("FIND_SECONDARY)) || []"))
        self.assertLess(source.index("FIND_SECONDARY)) || []"), source.index("late-t"))
        for needle in ("primaryAttempts = 2", "option('--seconds', '75')"):
            self.assertIn(needle, source)
        self.assertIn("default=75", (ROOT / "scripts" / "page_verify" / "verify.py").read_text())

    def test_secondary_controls_do_not_match_ordinary_words_like_in_progress(self):
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        self.assertNotIn("|in\\\\b|out\\\\b", source)
        self.assertIn("drone", source)

    def test_the_observer_cannot_leave_browser_processes_behind(self):
        source = (ROOT / "scripts" / "page_verify" / "observe.mjs").read_text()
        for needle in ("detached: true", "process.kill(-chrome.pid", "watchdog expired", "--in-process-gpu"):
            self.assertIn(needle, source)
        self.assertIn("start_new_session=True", (ROOT / "scripts" / "page_verify" / "verify.py").read_text())
        self.assertIn("os.killpg", (ROOT / "scripts" / "page_verify" / "verify.py").read_text())

    def test_the_observer_is_valid_javascript_and_explains_its_usage(self):
        script = str(ROOT / "scripts" / "page_verify" / "observe.mjs")
        self.assertEqual(0, subprocess.run(["node", "--check", script], check=False).returncode)
        usage = subprocess.run(["node", script], capture_output=True, text=True, check=False)
        self.assertEqual(2, usage.returncode)
        self.assertIn("usage", usage.stderr)


if __name__ == "__main__":
    unittest.main()
