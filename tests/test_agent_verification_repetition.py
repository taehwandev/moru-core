"""Repeated verification must stop executing, while real corrections remain runnable."""

import contextlib
import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_agent_verification_hook as support
import agent_verification_hook as verify
from agent_repair_ledger import (
    claim_verification_attempt, clear_verification_attempt, repair_checkpoint_path_for_preflight,
    capture_failure_checkpoint_binding, rebind_failure_checkpoints_after_required_doc_refresh,
)
from agent_hook_runtime import hook_failure_policy


class VerificationRepetitionTests(unittest.TestCase):
    setUp = support.VerificationHookTests.setUp
    run_hook = support.VerificationHookTests.run_hook
    entries = support.VerificationHookTests.entries
    write_test = support.VerificationHookTests.write_test

    def fail_twice(self):
        self.write_test("self.fail('expected')")
        for _ in range(2):
            self.assertEqual(1, self.run_hook())

    def test_third_unchanged_failure_does_not_start_another_process(self):
        self.fail_twice()
        with patch.object(verify, "execute_unittest", wraps=verify.execute_unittest) as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_not_called()
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("no_progress", self.entries()[-1]["fields"]["result"])

    def test_corrected_source_can_run_and_pass_after_the_limit(self):
        self.fail_twice()
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.assertEqual("SUCCESS", self.entries()[-1]["status"])

    def test_different_selection_is_not_the_same_attempt(self):
        self.fail_twice()
        self.args.test_pattern = "test_other.py"
        with patch.object(verify, "execute_unittest", wraps=verify.execute_unittest) as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_called_once()

    def test_alternating_selections_do_not_reset_the_failed_budget(self):
        self.fail_twice()
        self.args.test_pattern = "test_other.py"
        self.assertEqual(1, self.run_hook())
        self.args.test_pattern = "test_*.py"
        with patch.object(verify, "execute_unittest") as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_not_called()

    def test_changed_external_condition_requires_a_new_reason(self):
        self.fail_twice()
        self.args.retry_reason = "service restored; rechecking the integration"
        self.assertEqual(1, self.run_hook())
        self.assertEqual(1, self.run_hook())
        with patch.object(verify, "execute_unittest") as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_not_called()
        stored = repair_checkpoint_path_for_preflight(self.path).read_text()
        self.assertNotIn(self.args.retry_reason, stored)

    def claim(self, identity="same-input"):
        return claim_verification_attempt(evidence_path=self.path, preflight=self.preflight, identity=identity)

    def test_parallel_claims_cannot_exceed_the_budget(self):
        with ThreadPoolExecutor(max_workers=6) as workers:
            claimed = list(workers.map(lambda _: self.claim(), range(6)))
        self.assertEqual([0, 0, 0, 0, 1, 2], sorted(claimed))

    def test_older_success_does_not_clear_a_newer_attempt(self):
        self.assertEqual(1, self.claim())
        self.assertEqual(2, self.claim())
        clear_verification_attempt(evidence_path=self.path, preflight=self.preflight,
                                   identity="same-input", attempt=1)
        self.assertEqual(0, self.claim())

    def test_attempt_history_is_bounded(self):
        for index in range(40):
            self.assertEqual(1, self.claim(str(index)))
        stored = json.loads(repair_checkpoint_path_for_preflight(self.path).read_text())
        self.assertEqual(32, len(stored["verification_attempts"]))

    def rebind(self):
        binding = capture_failure_checkpoint_binding(self.path)
        self.assertTrue(binding)
        self.session["resume_generation"] = 1
        self.path.write_text(json.dumps(self.preflight))
        self.assertEqual("rebound", rebind_failure_checkpoints_after_required_doc_refresh(
            evidence_path=self.path, preflight=self.preflight, prior_binding=binding, required_doc_drift=True))

    def test_resume_cannot_reset_failed_execution_counts(self):
        self.fail_twice()
        self.rebind()
        with patch.object(verify, "execute_unittest") as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_not_called()

    def test_interrupted_claims_survive_session_rebinding(self):
        self.assertEqual(1, self.claim())
        self.assertEqual(2, self.claim())
        self.rebind()
        self.assertEqual(0, self.claim())

    def test_corrupt_counter_fails_closed_without_running_tests(self):
        self.fail_twice()
        path = repair_checkpoint_path_for_preflight(self.path)
        stored = json.loads(path.read_text())
        stored["verification_attempts"][0]["count"] = "invalid"
        path.write_text(json.dumps(stored))
        with patch.object(verify, "execute_unittest") as execute:
            self.assertEqual(1, self.run_hook())
        execute.assert_not_called()

    def test_success_clears_the_attempt_budget(self):
        self.write_test()
        for _ in range(3):
            self.assertEqual(0, self.run_hook())

    def test_framework_repair_failure_still_stops_after_its_single_cycle(self):
        policy, _ = hook_failure_policy(False, 1, verification_failure="task_failure")
        self.assertEqual("stop_after_repair_verification_failed", policy["next_action"])

    def test_failure_does_not_demand_an_unrelated_framework_repair(self):
        self.write_test("self.fail('expected')")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(1, verify.verification_hook(self.args))
        self.assertNotIn("improve the owning Moru Core", output.getvalue())
        self.assertIn("do not run repair-verify", output.getvalue())


if __name__ == "__main__":
    unittest.main()
