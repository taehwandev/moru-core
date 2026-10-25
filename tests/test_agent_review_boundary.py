"""Structure evidence rejections answer with a per-file fill-in template."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_review_boundary import structure_evidence_template
from agent_review_hook import (
    record_review_input_evidence,
    review_input_invocation_failure_details,
    structure_evidence_failures,
)


def _structure(boundary: bool = False) -> dict:
    return {
        "scope": "working tree",
        "checked_paths": ["scripts/big.py", "scripts/other.py", "scripts/quiet.py"],
        "warnings": [
            "scripts/big.py is already over 1000 lines and adds 4 line(s); evidence required",
            "scripts/other.py is a changed development source/style file with 700 lines",
        ],
        "boundary_note_requirements": (
            [{"package": "scripts", "reason": "package now contains multiple roles", "added": "scripts/new.py"}]
            if boundary
            else []
        ),
    }


class StructureEvidenceTemplateTests(unittest.TestCase):
    def test_missing_decision_and_prose_boundary_need_both_execution_repairs(self) -> None:
        structure = {"warnings": [], "boundary_note_requirements": [
            {"package": "scripts/native", "reason": "new runtime package/folder"},
        ]}
        arguments = SimpleNamespace(
            project=ROOT, evidence=None, review_outcome="",
            code_review_evidence="Exact scoped source reviewed",
            docs_freshness_evidence="Owning docs match current source",
            structure_review_evidence="The CLI owns configuration; focused tests passed",
            boundary_plan_evidence="Owned CLI boundary; focused verification",
            side_effect_audit_evidence="Only the scoped local files changed",
        )
        with patch("agent_review_hook.review_route_gates", return_value=[]):
            missing: list[str] = []
            record_review_input_evidence(arguments, {}, missing)
            missing += structure_evidence_failures(
                structure, arguments.structure_review_evidence,
            )
            self.assertTrue(any("review outcome" in failure for failure in missing))
            for field in ("allowed imports", "forbidden imports", "callers"):
                self.assertTrue(any(field in failure for failure in missing), field)

            decision_only: list[str] = []
            arguments.review_outcome = "pass"
            record_review_input_evidence(arguments, {}, decision_only)
            decision_only += structure_evidence_failures(structure, arguments.structure_review_evidence)
            self.assertTrue(any("allowed imports" in failure for failure in decision_only))
            self.assertFalse(any("review outcome" in failure for failure in decision_only))

            arguments.review_outcome = ""
            arguments.structure_review_evidence = (
                "owner: native packaging; allowed imports: standard library; "
                "forbidden imports: UI and credential services; "
                "callers/tests: CLI and packaging tests; verification: focused unittest"
            )
            boundary_only: list[str] = []
            record_review_input_evidence(arguments, {}, boundary_only)
            boundary_failures = structure_evidence_failures(structure, arguments.structure_review_evidence)
            self.assertEqual([], boundary_failures)
            boundary_only += boundary_failures
            self.assertEqual(1, len(boundary_only))
            self.assertTrue(any("review outcome" in failure for failure in boundary_only))

            # Repair the actual invocation as one unit: a verdict alone cannot
            # supply the missing package contract, nor can prose supply a verdict.
            arguments.review_outcome = "pass"
            repaired: list[str] = []
            record_review_input_evidence(arguments, {}, repaired)
            repaired += structure_evidence_failures(structure, arguments.structure_review_evidence)
            self.assertEqual([], repaired)

    def test_template_names_each_warned_file_with_its_questions(self) -> None:
        template = structure_evidence_template(_structure())

        for path in ("scripts/big.py", "scripts/other.py"):
            self.assertIn(
                f"{path}: expands public owner surface? <yes/no>; "
                "why the code stays here: <reason>",
                template,
            )
        self.assertNotIn("scripts/quiet.py", template)
        self.assertNotIn("allowed imports", template)

    def test_boundary_labels_appear_only_for_a_multi_role_package(self) -> None:
        template = structure_evidence_template(_structure(boundary=True))

        self.assertIn(
            "owner: <owning module>; allowed imports: <modules>; forbidden imports: <modules>; "
            "callers/tests: <callers and tests>; verification: <check run>",
            template,
        )

    def test_rejected_review_prints_the_template_without_changing_the_verdict(self) -> None:
        structure = _structure()
        failures = structure_evidence_failures(structure, "")

        details = review_input_invocation_failure_details(failures, structure, "working-tree")

        self.assertEqual(1, len(failures))
        self.assertTrue(any(line.startswith("fill-in template: --structure-review-evidence") for line in details))
        self.assertEqual([], structure_evidence_failures(structure, "scripts/big.py: no; reason"))


if __name__ == "__main__":
    unittest.main()
