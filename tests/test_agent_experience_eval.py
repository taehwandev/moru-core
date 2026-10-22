from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_experience_eval", ROOT / "scripts/agent_experience_eval.py")
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class ExperienceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.json"
        self.fixture = {
            "schema_version": 1, "description": "Synthetic arithmetic fixture.",
            "records": [
                {"id": "0000000000000001", "body": "First.", "source": "synthetic fixture"},
                {"id": "0000000000000002", "body": "Second.", "source": "synthetic fixture"},
                {"id": "0000000000000003", "body": "Third.", "source": "synthetic fixture"},
            ],
            "cases": [{"id": "mixed", "category": "arithmetic", "request": "first",
                       "expected_relevant": ["0000000000000001", "0000000000000002"]}],
        }

    def load(self, fixture=None):
        self.path.write_text(json.dumps(fixture or self.fixture), encoding="utf-8")
        return evaluator.load_fixture(self.path)

    def engine(self, rendered):
        def lines(project, scope, **context):
            self.assertEqual(len(context["records"]), 3)
            return ["reference header", *["- " + json.dumps({"id": item}) for item in rendered]]
        return SimpleNamespace(_digest=lambda record: "fixture-digest",
                               _recall=lambda project, scope, **context: context["records"],
                               recall_lines=lines)

    def test_metrics_count_rendered_context_instead_of_all_ranked_candidates(self):
        rendered = ["0000000000000001", "0000000000000003"]
        report = evaluator.evaluate(self.engine(rendered), self.load(), ROOT)
        metrics = report["metrics"]
        self.assertEqual((metrics["precision"], metrics["recall"]), (0.5, 0.5))
        self.assertEqual((metrics["irrelevant_selections"], metrics["misses"]), (1, 1))
        self.assertEqual(metrics["payload_characters"], sum(len(json.dumps({"id": item})) for item in rendered))
        self.assertEqual(report["cases"][0]["missed_ids"], ["0000000000000002"])
        self.assertEqual(len(report["cases"][0]["ranked_ids"]), 3)

    def test_empty_denominators_are_unknown_instead_of_perfect_scores(self):
        fixture = self.load()
        fixture["cases"][0]["expected_relevant"] = []
        report = evaluator.evaluate(self.engine([]), fixture, ROOT)
        self.assertIsNone(report["metrics"]["precision"])
        self.assertIsNone(report["metrics"]["recall"])

    def test_context_free_listing_does_not_inflate_retrieval_metrics(self):
        fixture = self.load()
        fixture["cases"].append({"id": "listing", "category": "listing",
                                  "expected_relevant": ["0000000000000001"]})
        report = evaluator.evaluate(self.engine(["0000000000000001"]), fixture, ROOT)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["retrieval_case_count"], 1)
        self.assertEqual(report["metrics"]["expected"], 2)
        self.assertEqual(report["metrics"]["recall"], 0.5)
        self.assertEqual(report["total_payload_characters"], 2 * report["metrics"]["payload_characters"])

    def test_conditions_and_expiry_are_materialized_without_mutating_fixture(self):
        fixture = self.load()
        fixture["records"][0].update(applies_when="A qualifying symptom.", review_in_days=0)
        original = copy.deepcopy(fixture)
        observed = []
        engine = self.engine([])
        engine._digest = lambda record: observed.append(dict(record)) or "digest"
        evaluator.evaluate(engine, fixture, ROOT)
        self.assertEqual(fixture, original)
        self.assertEqual(observed[0]["applies_when"], "A qualifying symptom.")
        self.assertEqual(observed[0]["review_on"], evaluator.date.today().isoformat())
        self.assertNotIn("review_in_days", observed[0])

    def test_invalid_fixture_fields_are_rejected(self):
        mutations = [
            lambda value: value.update(schema_version=2),
            lambda value: value.update(schema_version=True),
            lambda value: value["records"][1].update(id="0000000000000001"),
            lambda value: value["records"][0].update(source_files=[]),
            lambda value: value["records"][0].update(applies_when="x" * 161),
            lambda value: value["records"][0].update(not_when="two\nlines"),
            lambda value: value["records"][0].update(review_in_days=True),
            lambda value: value["records"][0].update(status=[]),
            lambda value: value["records"][0].update(replaces="ffffffffffffffff"),
            lambda value: value["records"][0].update(replaces=[]),
            lambda value: value["cases"][0].update(expected_relevant=["ffffffffffffffff"]),
            lambda value: value["cases"][0].update(target_paths="not-a-list"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                invalid = copy.deepcopy(self.fixture)
                mutate(invalid)
                with self.assertRaises(ValueError):
                    self.load(invalid)

    def test_unknown_or_duplicate_rendered_ids_are_rejected(self):
        for rendered in [["ffffffffffffffff"], ["0000000000000001"] * 2]:
            with self.subTest(rendered=rendered), self.assertRaises(ValueError):
                evaluator.evaluate(self.engine(rendered), self.load(), ROOT)

    def test_checked_in_fixture_has_explicit_limitations(self):
        fixture = evaluator.load_fixture(evaluator.DEFAULT_FIXTURE)
        self.assertEqual(len(fixture["cases"]), 14)
        limits = [case for case in fixture["cases"] if case["category"] == "known_lexical_limit"]
        self.assertEqual({case["id"] for case in limits}, {"generic_overlap", "zero_overlap_paraphrase"})
        self.assertTrue(all(case.get("applicability_expectation") for case in limits))

    def test_engine_root_loads_the_requested_module(self):
        engine_dir = Path(self.directory.name)
        (engine_dir / "agent_project_memory.py").write_text("MARKER = 'historical fixture'\n", encoding="utf-8")
        self.assertEqual(evaluator.load_engine(engine_dir).MARKER, "historical fixture")


if __name__ == "__main__":
    unittest.main()
