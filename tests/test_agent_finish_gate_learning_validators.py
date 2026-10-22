"""Causal efficiency assessments reuse the existing retrospective gate."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_gate_evidence import synthesize_gate_evidence


class EfficiencyAssessmentTests(unittest.TestCase):
    def render(self, **extra):
        fields = dict(skills_checked="retrospective_learning",
                      outcome="no_reusable_gap", observation="not_needed")
        fields.update(extra)
        text, missing = synthesize_gate_evidence("retrospective check", "", fields)
        self.assertEqual([], missing)
        return text

    def test_historical_and_unmeasured_records_remain_valid(self):
        for fields in ({}, {"efficiency": "unmeasured", "efficiency_evidence": "No comparable timing available"},
                       {"efficiency": "no_waste", "efficiency_evidence": "No unchanged-result requery observed"}):
            with self.subTest(fields=fields):
                self.assertEqual([], validate_retrospective_check(self.render(**fields)))

    def test_improvement_survives_rendering_and_requires_causal_chain(self):
        fields = dict(efficiency="improvement_needed", outcome="reusable_gap", observation="recorded",
                      efficiency_evidence="One unchanged ledger query followed its snapshot",
                      efficiency_cause="Snapshot reuse decision was absent",
                      efficiency_reduction="Reuse unchanged batch snapshot",
                      efficiency_verification="Regression checks snapshot and failed-ledger counterexample")
        self.assertEqual([], validate_retrospective_check(self.render(**fields)))
        for name in ("efficiency_evidence", "efficiency_cause", "efficiency_reduction", "efficiency_verification"):
            with self.subTest(name=name):
                incomplete = dict(fields)
                del incomplete[name]
                self.assertTrue(validate_retrospective_check(self.render(**incomplete)))

    def test_improvement_cannot_bypass_existing_maintenance(self):
        text = self.render(efficiency="improvement_needed", efficiency_evidence="Observed redundant read",
                           efficiency_cause="Optional link treated as mandatory", efficiency_reduction="Narrow selection",
                           efficiency_verification="Selection regression with required dependency preserved")
        self.assertTrue(any("same-closeout" in error for error in validate_retrospective_check(text)))

    def test_unknown_or_orphan_fields_are_rejected(self):
        for fields in ({"efficiency": "fast"}, {"efficiency_cause": "Missing assessment"},
                       {"efficiency": "no_waste"}):
            with self.subTest(fields=fields):
                self.assertTrue(validate_retrospective_check(self.render(**fields)))


class CausalRetrospectiveTests(unittest.TestCase):
    render = EfficiencyAssessmentTests.render

    def assess(self, **extra):
        fields = dict(
            alignment_evidence="Agreed ticket AC1 includes null input after Q&A; artifact and test T1 cover AC1",
            causal_assessment="Agreement, ticket, execution and observed result match; no corrective intervention",
            learning_decision="Keep existing null-input check; no reusable guidance gap evidenced",
        )
        fields.update(extra)
        return validate_retrospective_check(self.render(**fields), contract="causal_v1")

    def test_success_still_requires_actual_assessment(self):
        self.assertEqual([], self.assess())
        self.assertTrue(validate_retrospective_check(self.render(), contract="causal_v1"))
        for name in ("alignment_evidence", "causal_assessment", "learning_decision"):
            with self.subTest(name=name):
                self.assertTrue(any(name.replace("_", " ") in error for error in self.assess(**{name: ""})))

    def test_runtime_judgment_is_not_reclassified_from_words_or_turn_counts(self):
        scenarios = (
            ("User adds JSON after accepting CSV; ticket v2 supersedes v1", "Legitimate requirement evolution"),
            ("Null input was required in AC1 but omitted until user pointed to Q&A", "Execution drift and missed verification"),
            ("Agent assumed an unresolved format; clarification led to correct final artifact", "Ambiguity mishandled before recovery"),
            ("Original check passed but did not exercise AC2; user intervention supplied missing case", "Verification gap despite eventual success"),
            ("Several questions resolved format before execution; ticket and output agree", "Successful clarification without failure"),
            ("아까 논의한 빈 입력 조건이 결과에서 빠졌어; 티켓 AC2와 검증 T2를 비교함", "누락은 구현에서 시작했고 검증이 놓침"),
        )
        for alignment, cause in scenarios:
            with self.subTest(alignment=alignment):
                self.assertEqual([], self.assess(alignment_evidence=alignment, causal_assessment=cause))

    def test_causal_fields_survive_rendering_and_unknown_contract_fails(self):
        text = self.render(alignment_evidence="Ticket AC1 -> artifact -> T1",
                           causal_assessment="No divergence observed", learning_decision="Keep existing check")
        self.assertIn("alignment evidence: Ticket AC1 -> artifact -> T1", text)
        for contract in ("unknown_future_contract", "", None, {}):
            with self.subTest(contract=contract):
                self.assertTrue(validate_retrospective_check(text, contract=contract))

    def test_new_route_binds_the_assessment_to_real_gate_validation(self):
        from agent_finish_gate_policy import validate_gate_evidence
        from workflow_route import resolve_docs

        for command in ("build", "bugfix", "docs", "test", "retrospective"):
            with self.subTest(command=command):
                route = resolve_docs(command, None, [], request_classified=True)
                self.assertEqual("causal_v1", route["retrospective_contract"])
                self.assertIn("retrospective check", route["gates"])
                failures = validate_gate_evidence(
                    {"retrospective check": self.render()}, ["retrospective check"], route=route,
                )
                self.assertTrue(any("causal assessment" in error for error in failures))

    def test_ungrounded_no_change_dismissals_are_rejected_while_grounded_decisions_pass(self):
        for ungrounded in (
            "No canonical skill change needed; existing workflow rules matched",
            "No additional canonical skill update required",
            "No canonical skill or rule change needed",
            "No changes needed",
            "No updates needed",
            "Not applicable",
            "No action needed",
            "No-op",
            "skip",
            "`none`",
            "- none",
            "No skill-doc change needed",
            "No SKILL.md change needed",
            "none",
            "n/a",
            "not needed",
        ):
            with self.subTest(ungrounded=ungrounded):
                failures = self.assess(learning_decision=ungrounded)
                self.assertTrue(
                    any("learning decision" in error for error in failures),
                    f"Expected rejection for {ungrounded!r}, got {failures}",
                )
        for grounded in (
            "Keep existing null-input check; no reusable guidance gap evidenced",
            "Keep existing check",
            "Updated retrospective validator and unit tests",
            "No change needed because finish gate X already blocks this",
            "No change to verification_policy because test_null_input already covers AC1",
            "No guidance update required because rule X covers it",
            "No rule change; keep existing finish check",
            "None of the 3 skills lacked a rule; finish validator X covers it",
        ):
            with self.subTest(grounded=grounded):
                self.assertEqual([], self.assess(learning_decision=grounded))


if __name__ == "__main__":
    unittest.main()
