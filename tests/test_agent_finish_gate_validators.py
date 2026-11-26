"""Focused regression tests for finish-gate evidence validators."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_finish_gate_doc_test_validators import validate_tests
from agent_finish_gate_validators import validate_platform_selection_evidence


class PlatformSelectionEvidenceValidatorTests(unittest.TestCase):
    def test_rejects_python_prose_without_platform_card_evidence(self) -> None:
        for evidence in (
            "Python code was read before architecture",
            "selected platform: python; python-only code before architecture",
        ):
            with self.subTest(evidence=evidence):
                self.assertTrue(validate_platform_selection_evidence(evidence))

    def test_accepts_explicit_python_platform_card_evidence(self) -> None:
        evidence = (
            "selected platform: python; loaded "
            "platforms/python/skills/python-web-service/SKILL.md "
            "before architecture"
        )

        self.assertEqual([], validate_platform_selection_evidence(evidence))


class TestsEvidenceValidatorTests(unittest.TestCase):
    def test_accepts_real_creative_and_script_check_evidence(self) -> None:
        for evidence in (
            "35 captured stills, 0 console and contract errors, 14/14 exact sampled frames",
            "node tools/choreo-check.mjs -> 0 finding(s)",
            "node _shots/p13/tools/verify13.cjs --scene alley --play -> failed []",
            "check: node tools/shot.cjs --out out; result: 35 captured stills, 0 console and contract errors, 14/14 exact sampled frames",
            "python3 scripts/verify_rig.py --strict -> exit 0",
            "bash tools/smoke_render.sh -> 12 checks passed",
            "verification: failed []",
            "check: zero console failures",
            "audit: 0 findings",
            "1/1 tests passed",
            "14/14 frames",
            "7 animations exported",
            "node tools/check.mjs passed",
            "python3 scripts/verify_rig.py --strict passed",
            "./tools/smoke_render.sh ok",
            "검증 0건 오류",
            "오류 0건",
            "실패 0건",
            "18 / 18 checks passed",
        ):
            with self.subTest(evidence=evidence):
                self.assertEqual([], validate_tests(evidence), evidence)

    def test_rejects_unfalsifiable_zero_run_and_failing_claims(self) -> None:
        for evidence in (
            "tests ran",
            "looks good",
            "verified",
            "tests passed",
            "all tests pass",
            "unit tests green",
            "tests passed on release 26/09",
            "test; passed",
            "tests pass 3 times",
            "tests passed in 5 seconds",
            "tests pass, see PR 12 review",
            "verified 2 things",
            "checked 1 thing",
            "passed 1 time",
            "tests passed on 2 machines",
            "tests passed 0/0",
            "0/5 passed",
            "3/3",
            "14/14 seconds",
            "14/14 times",
            "1/1 pr",
            "frames 3/3",
            "tests passed 1/1",
            "1/2 passed",
            "0 console errors (page never loaded)",
            "0 failures because nothing ran",
            "0 errors (page not loaded)",
            "0 failures (tests did not run)",
            "tests passed 5/5 but 2 skipped",
            "0 failures (skipped)",
            "검증 2건 오류",
            "오류 1건",
            "tests passed, 0 run",
            "ran tests, 0 tests run",
            "verified, 0 problems",
            "ran ./foo.sh",
            "tests pass node a/b.js",
            "ran bash x/y.sh",
            "passed, sh a/b.c",
            "3 failures",
            "tests failed: 3 failures",
            "ran 5 tests, 2 failed",
            "pytest failed with 3 errors",
            "tests passed 2026-11-25",
            "tests passed v1 2",
        ):
            with self.subTest(evidence=evidence):
                self.assertTrue(validate_tests(evidence), evidence)


if __name__ == "__main__":
    unittest.main()
