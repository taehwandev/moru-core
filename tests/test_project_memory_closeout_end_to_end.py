"""A completed retrospective must leave a durable lesson or explain no capture."""

import json
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_finish_gate_policy import validate_gate_evidence
from agent_gate_evidence import synthesize_gate_evidence
from agent_project_memory import _capture, _digest, _retire, recall_lines, store_dir


class RetrospectiveMemoryCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        env = patch.dict(os.environ, {"MORU_STATE_HOME": str(Path(self.temp.name) / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.route = {"command": "bugfix", "retrospective_contract": "causal_v1",
                      "project_memory_contract": "decision_v1"}

    def render(self, **extra):
        fields = dict(skills_checked="retrospective_learning", outcome="no_reusable_gap",
                      observation="not_needed", alignment_evidence="Agreed retry repair and observed regression",
                      causal_assessment="The old closeout omitted durable capture",
                      learning_decision="Repair the closeout owner and replay next-task recall")
        fields.update(extra)
        rendered, errors = synthesize_gate_evidence("retrospective check", "", fields)
        self.assertEqual([], errors)
        return rendered

    def validate(self, text, **kwargs):
        return validate_gate_evidence({"retrospective check": text}, ["retrospective check"],
                                      route=self.route, project=self.project, **kwargs)

    def capture(self, **extra):
        return _capture(self.project, body="Retry delivery must preserve event identity",
                        source="verified retry regression", scope="all",
                        review_on=(date.today() + timedelta(days=30)).isoformat(),
                        applies_when="retry delivery after a transport timeout", **extra)

    def stored(self, record):
        return self.render(memory_decision="stored", memory_reason="Verified retry cause retained for later work",
                           memory_record=record["id"] + ":" + record["digest"])

    def test_old_success_without_memory_decision_is_no_longer_completion(self):
        self.assertTrue(any("memory decision" in error for error in self.validate(self.render())))

    def test_no_lesson_is_an_explicit_reasoned_decision_not_a_forced_capture(self):
        self.assertEqual([], self.validate(self.render(memory_decision="not_needed",
                         memory_reason="The canonical retry rule was repaired and regression-tested directly")))
        self.assertTrue(self.validate(self.render(memory_decision="not_needed")))
        self.assertTrue(self.validate(self.render(memory_decision="guessed", memory_reason="Unknown action")))
        self.assertFalse(store_dir(self.project).exists())

    def test_memory_fields_do_not_ground_a_dismissive_learning_decision(self):
        record = self.capture()
        for memory_decision in ("not_needed", "stored"):
            memory = dict(memory_decision=memory_decision, memory_reason="Canonical retry rule already covers it")
            if memory_decision == "stored":
                memory["memory_record"] = record["id"] + ":" + record["digest"]
            for outcome in ("no_reusable_gap", "reusable_gap"):
                for decision in ("none", "n/a", "No skill change needed"):
                    with self.subTest(memory=memory_decision, outcome=outcome, decision=decision):
                        text = self.render(outcome=outcome, observation="recorded" if outcome == "reusable_gap" else "not_needed",
                                           learning_decision=decision, **memory)
                        self.assertTrue(any("learning decision" in error for error in self.validate(text)))

    def test_memory_fields_preserve_a_grounded_semicolon_rationale(self):
        text = self.render(learning_decision="No skill change needed; keep the canonical retry rule because the regression covers it",
                           memory_decision="not_needed", memory_reason="Canonical retry rule already covers it")
        self.assertEqual([], self.validate(text))

    def test_late_recheck_preserves_the_initial_missing_gate_diagnosis(self):
        from agent_finish_check_steps import revalidate_project_memory_closeout

        route = dict(self.route, gates=["retrospective check"])
        signals = [dict(gate="retrospective check", signal="FAIL", status="missed", evidence="missing evidence")]
        failures = ["missing required gate evidence: retrospective check"]
        policy = ["retrospective check evidence is required"]
        before = json.dumps([signals, failures, policy], sort_keys=True)
        revalidate_project_memory_closeout(route, self.project, {}, signals, failures, policy)
        self.assertEqual(before, json.dumps([signals, failures, policy], sort_keys=True))

    def test_late_recheck_only_owns_memory_and_does_not_reassess_causal_fields(self):
        from agent_finish_check_steps import project_memory_closeout_failures

        route = dict(self.route, gates=["retrospective check"])
        text = self.render(causal_assessment="", memory_decision="not_needed",
                           memory_reason="Canonical rule already repaired and tested")
        self.assertTrue(self.validate(text))  # The initial causal check still rejects it.
        self.assertEqual([], project_memory_closeout_failures(route, {"retrospective check": text}, self.project))

    def test_promised_or_foreign_lesson_cannot_pass_as_stored(self):
        fields = dict(memory_decision="stored", memory_reason="Confirmed root cause")
        self.assertTrue(self.validate(self.render(**fields)))
        self.assertTrue(self.validate(self.render(**fields, memory_record="0" * 16 + ":" + "0" * 64)))
        record = self.capture()
        other = Path(self.temp.name) / "other"
        other.mkdir()
        with patch.object(self, "project", other):
            self.assertTrue(self.validate(self.stored(record)))

    def test_a_lesson_that_can_never_fit_recall_cannot_pass_as_reusable(self):
        review_on = (date.today() + timedelta(days=30)).isoformat()
        old = _capture(self.project, body="y" * 200, source="verified old fixture", scope="all", review_on=review_on)
        record = _capture(self.project, body="x" * 500, source="s" * 200, scope="all",
                          review_on=review_on, replaces=old["id"],
                          applies_when="a" * 160, not_when="b" * 160)
        self.assertEqual([], recall_lines(self.project, "bugfix"))
        self.assertTrue(any("budget" in error for error in self.validate(self.stored(record))))

    def test_saved_lesson_passes_and_is_delivered_to_the_next_task(self):
        record = self.capture(not_when="new event with a distinct valid id")
        self.assertEqual([], self.validate(self.stored(record)))
        delivered = "\n".join(recall_lines(self.project, "bugfix", request="retry delivery"))
        self.assertIn(record["id"], delivered)
        self.assertIn("applies_when", delivered)
        self.assertIn("not_when", delivered)

    def test_finish_rechecks_retirement_replacement_and_digest(self):
        record = self.capture()
        text = self.stored(record)
        self.assertEqual([], self.validate(text))
        _retire(self.project, record["id"])
        self.assertTrue(self.validate(text))
        live = self.capture()
        path = store_dir(self.project) / (live["id"] + ".json")
        text = self.stored(live)
        live["body"] = "An independently updated lesson"
        live["digest"] = _digest(live)
        path.write_text(json.dumps(live), encoding="utf-8")
        self.assertTrue(self.validate(text))

    def test_superseded_lesson_cannot_complete_after_interrupted_replacement_is_retired(self):
        old = self.capture()
        text = self.stored(old)
        self.assertEqual([], self.validate(text))
        with patch("agent_project_memory._retire"):
            corrected = self.capture(replaces=old["id"])
        _retire(self.project, corrected["id"])
        self.assertTrue(any("replaced" in error for error in self.validate(text)))
        self.assertEqual([], recall_lines(self.project, "bugfix", request="retry delivery"))

    def test_legacy_contract_stays_frozen_and_unknown_contract_fails(self):
        del self.route["project_memory_contract"]
        self.assertEqual([], self.validate(self.render()))
        self.route["project_memory_contract"] = "unknown_future"
        self.assertTrue(self.validate(self.render()))

    def test_source_drift_expiry_and_replacement_invalidate_the_closeout_reference(self):
        source = self.project / "retry.py"
        source.write_text("# verified retry contract\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "retry.py"], check=True)
        record = self.capture(source_paths=("retry.py",))
        text = self.stored(record)
        self.assertEqual([], self.validate(text))
        source.write_text("# changed retry contract\n", encoding="utf-8")
        self.assertTrue(self.validate(text))
        source.unlink()
        self.assertTrue(self.validate(text))
        old = self.capture()
        self.capture(replaces=old["id"])
        self.assertTrue(self.validate(self.stored(old)))
        expired = self.capture()
        expired["review_on"] = date.today().isoformat()
        expired["digest"] = _digest(expired)
        (store_dir(self.project) / (expired["id"] + ".json")).write_text(json.dumps(expired), encoding="utf-8")
        self.assertTrue(self.validate(self.stored(expired)))

    def test_new_routes_require_the_existing_gate_decision(self):
        from workflow_route import resolve_docs
        for command in ("bugfix", "docs", "test", "small-change", "retrospective"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertEqual("decision_v1", route["project_memory_contract"])

    def test_memory_contract_is_bound_to_route_provenance_without_changing_legacy_routes(self):
        from agent_route_state import route_fingerprint

        legacy = {"command": "bugfix", "gates": ["retrospective check"]}
        old_hash = route_fingerprint(legacy)
        current = dict(legacy, project_memory_contract="decision_v1")
        self.assertNotEqual(old_hash, route_fingerprint(current))
        self.assertNotEqual(route_fingerprint(current), route_fingerprint(dict(current, project_memory_contract="unknown")))
        self.assertEqual(old_hash, route_fingerprint(dict(legacy)))

    def test_actual_cli_closeout_capture_next_start_and_late_retirement(self):
        from support.stable_launcher import _launcher_script_text

        root = Path(__file__).resolve().parents[1]
        launcher = Path(self.temp.name) / "moru-hook"
        launcher.write_text(_launcher_script_text(), encoding="utf-8")
        env = dict(os.environ, MORU_HOME=str(root), PYTHONDONTWRITEBYTECODE="1")
        (self.project / ".gitignore").write_text(".env\n.env.*\n!.env.example\n.moru/\n", encoding="utf-8")
        (self.project / "README.md").write_text("Synthetic retry delivery fixture.\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", ".gitignore", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "Synthetic fixture"], check=True)

        def cli(*args, body=None, success=True):
            result = subprocess.run([sys.executable, "-B", str(launcher), *args],
                                    cwd=self.project, env=env, input=body, text=True, capture_output=True, timeout=45)
            self.assertEqual(success, result.returncode == 0, result.stdout + result.stderr)
            return result.stdout + result.stderr

        def start():
            result = cli("start", "--project", str(self.project), "--rules", str(root),
                         "--command", "test", "--request", "Verify retry delivery",
                         "--intent", "fixture_verification", "--target-summary", "Verify retry delivery")
            evidence = re.search(r"^- evidence: (.+)$", result, re.M).group(1)
            return result, ["--project", str(self.project), "--rules", str(root), "--evidence", evidence]

        _, context = start()
        fields = dict(skills_checked="retrospective_learning", outcome="no_reusable_gap", observation="not_needed",
                      alignment_evidence="Synthetic retry fixture request and observed outcome agree",
                      causal_assessment="Closeout must preserve a verified retry lesson",
                      learning_decision="Use the existing project memory store and test its actual CLI delivery")
        rejected = cli("gate-batch", *context, "--gate-record", json.dumps([
            dict(gate="retrospective check", status="SUCCESS", fields=fields)]), success=False)
        self.assertIn("memory decision", rejected)
        record = json.loads(cli("project-memory", "--project", str(self.project), "capture",
                                "--source", "synthetic verified retry fixture", "--review-on",
                                (date.today() + timedelta(days=30)).isoformat(),
                                "--applies-when", "retry delivery after timeout", "--not-when", "distinct valid event ids",
                                body="Retry delivery must preserve event identity"))
        fields.update(memory_decision="stored", memory_reason="Verified retry cause is useful in later delivery work",
                      memory_record=record["id"] + ":" + record["digest"])
        gates = [dict(gate="tests", status="SUCCESS", fields=dict(check="synthetic retry CLI flow",
                  result="1 integration test passed, exit status 0")),
                 dict(gate="retrospective check", status="SUCCESS", fields=fields)]
        cli("gate-batch", *context, "--gate-record", json.dumps(gates))
        self.assertIn("SUCCESS finish", cli("finish", *context))
        next_start, next_context = start()
        self.assertIn(record["id"], next_start)
        self.assertIn("distinct valid event ids", next_start)
        cli("gate-batch", *next_context, "--gate-record", json.dumps(gates))
        spec = importlib.util.spec_from_file_location("memory_finish_race", root / "scripts/agent-finish-check.py")
        finish = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(finish)
        original_checks = finish.run_final_checks

        def retire_during_final_checks(*args, **kwargs):
            result = original_checks(*args, **kwargs)
            _retire(self.project, record["id"])
            return result

        output = io.StringIO()
        with patch.object(finish, "run_final_checks", side_effect=retire_during_final_checks), \
             patch.object(sys, "argv", ["agent-finish-check.py", *next_context]), \
             redirect_stdout(output), redirect_stderr(output):
            self.assertNotEqual(0, finish.main())
        self.assertIn("memory_record", output.getvalue())


if __name__ == "__main__":
    unittest.main()
