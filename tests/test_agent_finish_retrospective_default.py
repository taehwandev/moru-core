"""Finish records the default retrospective only when the agent recorded none."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_finish_gate_learning_validators import validate_retrospective_check
from agent_finish_retrospective_default import derive_retrospective_default
from agent_gate_evidence import (
    merge_gate_evidence_from_ledger,
    record_gate_evidence,
    reset_gate_evidence_ledger,
)

ROUTE = {
    "command": "bugfix",
    "gates": ["tests", "review hook", "retrospective check"],
    "required_docs": ["common/skills/agent-operating-skill/SKILL.md"],
}


class RetrospectiveDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.evidence = Path(self._tmp.name) / "runs" / "run-1" / "preflight.json"
        self.evidence.parent.mkdir(parents=True)
        self.preflight = {"route": ROUTE, "agent_run_id": "run-1"}
        self.evidence.write_text(json.dumps(self.preflight), encoding="utf-8")
        reset_gate_evidence_ledger(self.evidence, self.preflight)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _recorded(self) -> dict:
        return merge_gate_evidence_from_ledger(route=ROUTE, evidence_path=self.evidence)[0]

    def test_missing_retrospective_is_derived_and_passes_finish_validation(self) -> None:
        self.assertIn("derived at finish", derive_retrospective_default(self.evidence))
        recorded = self._recorded()
        self.assertIn("retrospective check", recorded)
        self.assertEqual([], validate_retrospective_check(
            recorded["retrospective check"], loaded_skill_ids={"agent_operating_skill"},
        ))

    def test_agent_record_wins(self) -> None:
        record_gate_evidence(
            evidence_path=self.evidence, preflight=self.preflight, gate="retrospective check",
            fields={"skills_checked": "agent_operating_skill", "outcome": "reusable_gap",
                    "observation": "recorded"},
        )
        self.assertEqual("", derive_retrospective_default(self.evidence))
        self.assertIn("reusable_gap", self._recorded()["retrospective check"])

    def test_failed_agent_record_is_not_replaced(self) -> None:
        record_gate_evidence(
            evidence_path=self.evidence, preflight=self.preflight, gate="retrospective check",
            fields={"skills_checked": "agent_operating_skill", "outcome": "reusable_gap",
                    "observation": "recorded"}, status="FAIL",
        )
        self.assertEqual("", derive_retrospective_default(self.evidence))
        self.assertNotIn("retrospective check", self._recorded())

    def test_route_without_the_gate_is_untouched(self) -> None:
        route = {**ROUTE, "gates": ["request intake", "review hook", "commit readiness"]}
        self.evidence.write_text(json.dumps({**self.preflight, "route": route}), encoding="utf-8")
        self.assertEqual("", derive_retrospective_default(self.evidence))


if __name__ == "__main__":
    unittest.main()
