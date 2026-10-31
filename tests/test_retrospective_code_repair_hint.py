from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_finish_gate_learning_validators as validators  # noqa: E402


class CodeRepairIsNotASkillGapTests(unittest.TestCase):
    def test_a_decision_naming_the_repaired_owner_and_test_is_grounded(self):
        decision = "Repaired agent_hook_runtime.git_status with test_hook_gate_alias_and_dependency_status; no reusable skill gap."
        self.assertFalse(validators._is_ungrounded_learning_decision(decision))

    def test_a_bare_dismissal_is_still_ungrounded(self):
        self.assertTrue(validators._is_ungrounded_learning_decision("No skill change needed."))

    def test_the_rejection_message_offers_the_code_repair_wording(self):
        text = "\n".join([
            "alignment evidence: a", "causal assessment: b", "learning decision: No skill change needed.",
            "memory decision: not_needed", "memory reason: r"])
        failures = validators._causal_assessment_failures(text, validators.CAUSAL_RETROSPECTIVE_CONTRACT, "no_reusable_gap")
        joined = " ".join(failures)
        self.assertIn("Repaired <owner> with <test>; no reusable skill gap", joined)
        self.assertIn("reusable_gap when a skill document must change", joined)

    def test_the_gate_record_hint_separates_code_repairs_from_skill_changes(self):
        import agent_gate_record_template as template

        source = Path(template.__file__).read_text()
        self.assertIn("A gap repaired in a hook, validator, ", source)
        self.assertIn('only when a skill document must change', source)


if __name__ == "__main__":
    unittest.main()
