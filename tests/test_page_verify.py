from __future__ import annotations

import json
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
        self.assertEqual(["loads-clean", "action-responds", "ship-on-pad", "x"], ids)
        self.assertEqual(["screenshots"], items[-1]["evidence"])
        self.assertEqual("derived", items[-1]["source"])

    def test_a_derived_item_may_replace_a_generic_one_without_duplicating_it(self):
        answer = json.dumps([{"id": "loads-clean", "claim": "mine", "evidence": ["console"]}])
        items = verify.derive_checklist("request", ask=lambda *a, **k: answer)
        self.assertEqual(1, [i["id"] for i in items].count("loads-clean"))

    def test_the_prompt_asks_for_the_generic_implied_conditions(self):
        self.assertIn("faces its direction of travel", verify.DERIVE_PROMPT)
        self.assertIn("resting state before the action differs", verify.DERIVE_PROMPT)

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

    def test_feedback_names_only_failures_and_lists_what_stayed_unobserved(self):
        results = [{"id": "a", "claim": "A holds.", "verdict": "fail", "reason": "t2s shows otherwise"},
                   {"id": "b", "claim": "B holds.", "verdict": "unobserved", "reason": "n/a"},
                   {"id": "c", "claim": "C holds.", "verdict": "pass", "reason": "ok"}]
        text = verify.feedback_text(results)
        self.assertIn("- a: A holds. Observed: t2s shows otherwise", text)
        self.assertIn("Not observed, so unchecked: b.", text)
        self.assertNotIn("C holds", text)
        self.assertEqual("", verify.feedback_text([{**results[2]}, {**results[1]}]))

    def test_report_table_lists_each_verdict(self):
        table = verify.render([{"id": "a", "verdict": "fail", "reason": "r"}])
        self.assertIn("| a | fail | r |", table)


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

    def test_without_a_service_or_a_key_nothing_can_judge(self):
        env = {"MORU_VERIFY_JUDGE_URL": "", "OPENROUTER_API_KEY": ""}
        with unittest.mock.patch.dict("os.environ", env, clear=False), \
                unittest.mock.patch.object(verify, "api_key", side_effect=RuntimeError("no key")):
            self.assertFalse(verify.can_judge())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ObserverTests(unittest.TestCase):
    def test_the_observer_is_valid_javascript_and_explains_its_usage(self):
        script = str(ROOT / "scripts" / "page_verify" / "observe.mjs")
        self.assertEqual(0, subprocess.run(["node", "--check", script], check=False).returncode)
        usage = subprocess.run(["node", script], capture_output=True, text=True, check=False)
        self.assertEqual(2, usage.returncode)
        self.assertIn("usage", usage.stderr)


if __name__ == "__main__":
    unittest.main()
