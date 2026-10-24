"""Analysis reuse must miss on changed inputs, not just changed target files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_project_memory as memory


class AnalysisReuseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.environment = patch.dict(os.environ, {"MORU_STATE_HOME": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-q")
        for name, text in {"target.py": "from dependency import check\n", "dependency.py": "LIMIT = 1\n",
                           "config.json": '{"strict": true}\n', ".gitignore": ".moru/\n.env\n"}.items():
            (self.project / name).write_text(text)
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline")
        self.review_on = (date.today() + timedelta(days=7)).isoformat()
        self.question = "Can check raise?"
        self.context = "Python 3; local inputs only; no external facts"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def capture(self, **overrides):
        values = dict(body="check can raise; inspect dependency before removing its handler.",
                      source="Reviewed target and dependency contract", scope="analysis", review_on=self.review_on,
                      source_paths=("target.py", "dependency.py"), analysis_question=self.question,
                      analysis_context=self.context)
        return memory._capture(self.project, **(values | overrides))

    def recall(self, **overrides):
        return memory._analysis_recall(self.project, overrides.get("scope", "analysis"),
                                       overrides.get("question", self.question), overrides.get("context", self.context))

    def test_repeated_lookup_returns_original_conclusion_without_capture_or_model(self):
        record = self.capture()
        with patch.object(memory, "_capture", side_effect=AssertionError("unexpected write")):
            for _ in range(3):
                result = self.recall()
                self.assertEqual([record["id"]], [item["id"] for item in result])
                self.assertEqual(record["body"], result[0]["body"])
                self.assertEqual("candidate_only", result[0]["analysis_status"])

    def test_target_dependency_and_undeclared_config_drift_all_miss(self):
        self.capture()
        for name in ("target.py", "dependency.py", "config.json"):
            with self.subTest(name=name):
                path = self.project / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.assertEqual([], self.recall())
                path.write_bytes(original)
                self.assertTrue(self.recall())

    def test_added_deleted_and_renamed_inputs_miss(self):
        self.capture()
        extra = self.project / "new_config.json"
        extra.write_text("{}")
        self.assertEqual([], self.recall())
        extra.unlink()
        target = self.project / "target.py"
        contents = target.read_bytes()
        target.rename(self.project / "renamed.py")
        self.assertEqual([], self.recall())
        (self.project / "renamed.py").unlink()
        self.assertEqual([], self.recall())
        target.write_bytes(contents)
        self.assertTrue(self.recall())

    def test_scope_assumptions_case_negation_and_paraphrase_are_not_identity(self):
        self.capture()
        for values in ({"scope": "review"}, {"context": "production platform"},
                       {"question": "Can check not raise?"}, {"question": "Can CHECK raise?"},
                       {"question": "Does validation throw?"}, {"question": "Can  check raise?"}):
            with self.subTest(values=values):
                self.assertEqual([], self.recall(**values))
        self.assertTrue(self.recall(question=" Can check raise? "))

    def test_missing_declaration_partial_keys_and_invalid_values_rejected(self):
        for values in ({"source_paths": ()}, {"analysis_question": ""}, {"analysis_context": ""},
                       {"analysis_question": "x" * 301}, {"analysis_context": "line\nbreak"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.capture(**values)
        self.assertEqual([], memory.scan_records(self.project)[0])

    def test_retired_expired_and_interrupted_replacement_never_resurrect(self):
        old = self.capture()
        with patch.object(memory, "_retire"):
            corrected = self.capture(body="Corrected conclusion", replaces=old["id"])
        self.assertEqual([corrected["id"]], [item["id"] for item in self.recall()])
        memory._retire(self.project, corrected["id"])
        self.assertEqual([], self.recall())
        record = self.capture()
        path = memory._record_path(self.project, record["id"])
        record["review_on"] = date.today().isoformat()
        record["digest"] = memory._digest(record)
        path.write_text(json.dumps(record))
        self.assertEqual([], self.recall())

    def test_tampered_or_malformed_analysis_metadata_fails_closed(self):
        record = self.capture()
        path = memory._record_path(self.project, record["id"])
        record["analysis"]["question"] = "Altered question"
        path.write_text(json.dumps(record))
        self.assertIsNone(memory.read_record(path))
        record["analysis"]["inputs"] = []
        record["digest"] = memory._digest(record)
        path.write_text(json.dumps(record))
        self.assertIsNone(memory.read_record(path))

    def test_unavailable_or_oversized_workspace_snapshot_misses(self):
        self.capture()
        for error in (OSError, ValueError, RuntimeError):
            with self.subTest(error=error), patch.object(memory.EvidenceInputs, "capture", side_effect=error):
                self.assertEqual([], self.recall())

    def test_legacy_capture_and_nonmatching_lookup_do_not_hash_workspace(self):
        with patch.object(memory.EvidenceInputs, "capture", side_effect=AssertionError("unexpected scan")):
            record = self.capture(analysis_question="", analysis_context="")
            self.assertTrue(memory.read_record(memory._record_path(self.project, record["id"])))
            self.assertEqual([], self.recall())
        self.capture()
        with patch.object(memory.EvidenceInputs, "capture", side_effect=AssertionError("unexpected scan")):
            self.assertEqual([], self.recall(question="Unrelated question"))

    def test_result_item_and_character_budgets(self):
        for _ in range(8):
            self.capture(body="x" * 500)
        result = self.recall()
        self.assertLessEqual(len(result), memory.MAX_RECALL_ITEMS)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), memory.MAX_RECALL_CHARS)

    def test_ignored_external_inputs_need_a_fresh_caller_context(self):
        self.capture()
        (self.project / ".env").write_text("MODE=changed\n")
        self.assertTrue(self.recall())  # Explicit limitation: ignored inputs are not auto-observed.
        self.assertEqual([], self.recall(context=self.context + "; MODE=changed"))

    def test_actual_capture_recall_cli_then_config_change(self):
        script = Path(memory.__file__)
        common = [sys.executable, "-B", str(script), "--project", str(self.project)]
        capture = subprocess.run([*common, "capture", "--scope", "analysis", "--source", "CLI evidence",
                                  "--review-on", self.review_on, "--source-path", "target.py",
                                  "--analysis-question", self.question, "--analysis-context", self.context],
                                 input="Stored CLI conclusion", text=True, capture_output=True, check=True)
        record = json.loads(capture.stdout)
        command = [*common, "recall", "--scope", "analysis", "--analysis-question", self.question,
                   "--analysis-context", self.context]
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual(record["id"], json.loads(result.stdout)[0]["id"])
        (self.project / "config.json").write_text('{"strict": false}\n')
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual([], json.loads(result.stdout))
        rejected = subprocess.run([*command, "--request", "lexical query"], text=True, capture_output=True)
        self.assertEqual(2, rejected.returncode)


if __name__ == "__main__":
    unittest.main()
