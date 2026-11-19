"""On-demand offline comparison of worker completion policies."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_agent_verification_receipts import ReceiptFixture
from workflow_dispatch_completion import evaluate_result
from workflow_dispatch_handoff import build_worker_result_packet


class WorkerCompletionComparison(unittest.TestCase):
    def test_same_packets_under_three_evidence_policies(self):
        temporary = tempfile.TemporaryDirectory(prefix="moru completion comparison ")
        self.addCleanup(temporary.cleanup)
        fixture = ReceiptFixture(temporary.name)
        fixture.write_test("import os\n        self.assertFalse(os.environ.get('MORU_FIXTURE_FAIL'))")
        (fixture.project / "tests" / "test_other.py").write_text(
            "import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
        )
        sample_check = "test_sample.Case.test_ok"
        other_check = "test_other.Case.test_ok"
        required = {"selectors": [sample_check, other_check]}
        prepared = {"rules": str(fixture.project), "worker_preflight_evidence": str(fixture.path),
                    "preflight_evidence": str(fixture.path), "worker_owned_verification": True}
        outcomes = []

        def observe(case, expected, *, requested=True, status="ok"):
            packet = build_worker_result_packet(prepared, returncode=0, raw_output=json.dumps({
                "status": status, "checks": [{"cmd": "unittest", "outcome": "pass"}],
            }))
            policies = {"report_only": False, "opt_in": required if requested else False,
                        "forced": required}
            actual = {
                policy: evaluate_result(packet, prepared=prepared, working_dir=fixture.project,
                                        required_verification=spec)[0]
                for policy, spec in policies.items()
            }
            outcomes.append((case, expected, actual))

        # A traditional test command really passes both methods, but produces no bound receipt.
        manual = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                                cwd=fixture.project, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, manual.returncode, manual.stderr)
        self.assertIn("Ran 3 tests", manual.stderr)
        observe("manual_pass", True, requested=False)

        # Distinct controlled submissions to the same evidence policy.
        observe("honest_incomplete", False, status="blocked")
        observe("success_report_without_receipt", False)
        self.assertEqual(0, fixture.run([sample_check]))
        observe("partial_selection", False)
        self.assertEqual(0, fixture.run([other_check]))
        observe("complete_split_selection", True)
        with patch.dict(os.environ, {"MORU_FIXTURE_FAIL": "1"}):
            self.assertEqual(1, fixture.run([sample_check]))
        observe("later_matching_failure", False)
        self.assertEqual(0, fixture.run([sample_check]))
        observe("matching_recovery", True)
        fixture.write_test("self.assertTrue(True)")
        observe("stale_source", False)

        tally = {
            policy: {
                "missed_incomplete": sum(not expected and actual[policy] for _, expected, actual in outcomes),
                "false_blocks": sum(expected and not actual[policy] for _, expected, actual in outcomes),
            }
            for policy in outcomes[0][2]
        }
        print(json.dumps({"cases": len(outcomes), "policies": tally}, sort_keys=True))
        for case, expected, actual in outcomes:
            with self.subTest(case=case):
                self.assertEqual(expected, actual["opt_in"])
        self.assertEqual({
            "report_only": {"missed_incomplete": 4, "false_blocks": 0},
            "opt_in": {"missed_incomplete": 0, "false_blocks": 0},
            "forced": {"missed_incomplete": 0, "false_blocks": 1},
        }, tally)


if __name__ == "__main__":
    unittest.main()
