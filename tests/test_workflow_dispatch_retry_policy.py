"""Terminal transport errors drive recovery; model prose does not."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_dispatch_retry import WorkerOutcome, read_worker_outcome, recovery_message


class RetryPolicyTests(unittest.TestCase):
    def test_success_does_not_read_or_reinterpret_old_errors(self):
        self.assertEqual("complete", read_worker_outcome(0, Path("missing.log")).action)

    def read(self, error, *, before=(), returncode=1):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream"
            path.write_text("\n".join(json.dumps(event) for event in [*before, {"type": "turn.failed", "error": error}]))
            return read_worker_outcome(returncode, path)

    def test_transient_transport_errors_are_retryable_before_any_tool_runs(self):
        for error in ({"code": "ECONNRESET"}, {"code": "UNAVAILABLE"}, {"status_code": 429},
                      {"status_code": 503}, {"code": 502}, {"message": "unexpected status 504"},
                      {"code": "API_ERROR", "status_code": 503}, {"code": "SERVER_ERROR"},
                      {"message": "error sending request for url"}):
            with self.subTest(error=error):
                self.assertEqual("retry_transient", self.read(error).action)

    def test_permanent_errors_direct_a_correction_instead_of_blind_relaunch(self):
        for error, action in (({"code": "INVALID_ARGUMENT"}, "correct_invocation_and_retry"),
                              ({"status": 401}, "check_existing_auth"),
                              ({"status": 403}, "use_approved_permission_path"),
                              ({"code": "INSUFFICIENT_QUOTA", "status": 429}, "check_quota")):
            with self.subTest(error=error):
                self.assertEqual(action, self.read(error).action)

    def test_cancel_signal_wins_over_a_transient_error(self):
        for code in (130, 143, -2, -15):
            self.assertEqual("honor_cancellation", self.read({"code": "UNAVAILABLE"}, returncode=code).action)

    def test_started_or_completed_tools_require_observation_before_replay(self):
        for kind in ("command_execution", "file_change", "mcp_tool_call", "future_tool"):
            for event_type in ("item.started", "item.completed"):
                event = {"type": event_type, "item": {"type": kind}}
                self.assertEqual("observe_before_retry", self.read({"status": 503}, before=[event]).action)

    def test_model_prose_cannot_override_the_terminal_transport_code(self):
        event = {"type": "item.completed", "item": {"type": "agent_message", "text": "HTTP 401 secret text"}}
        self.assertEqual("retry_transient", self.read({"status": 503}, before=[event]).action)
        self.assertEqual("inspect_failure_and_correct_owner", self.read({"message": "assertion failed"}).action)

    def test_in_progress_turn_is_waited_on_instead_of_resubmitted(self):
        self.assertEqual("wait_existing_execution", self.read({"code": "UNAVAILABLE", "turn_in_progress": True}).action)

    def test_provider_retry_refusal_is_preserved(self):
        self.assertNotEqual("retry_transient", self.read({"code": "UNAVAILABLE", "retryable": False}).action)
        self.assertNotEqual("retry_transient", self.read({"status_code": 501}).action)
        self.assertEqual("check_existing_auth", self.read({"code": "UNAVAILABLE", "status_code": 401}).action)

    def test_retry_after_is_respected_but_never_waits_unboundedly(self):
        outcome = self.read({"status": 429, "retry_after_seconds": 4})
        self.assertEqual(4, outcome.delay(1))
        for value in (31, -1, "invalid", float("nan"), float("inf")):
            self.assertEqual("wait_retry_window", self.read({"status": 429, "retry_after_seconds": value}).action)

    def test_malformed_oversized_or_missing_logs_never_prove_replay_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream"
            self.assertFalse(read_worker_outcome(1, path).replay_safe)
            path.write_text("not an event\n" + json.dumps({"type": "error", "code": "UNAVAILABLE"}))
            self.assertEqual("observe_before_retry", read_worker_outcome(1, path).action)
            path.write_text("x" * (1024 * 1024 + 1))
            self.assertFalse(read_worker_outcome(1, path).replay_safe)

    def test_each_attempt_reads_only_its_own_stream_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream"
            previous = json.dumps({"type": "item.started", "item": {"type": "file_change"}}) + "\n"
            path.write_text(previous + json.dumps({"type": "error", "code": "UNAVAILABLE"}))
            self.assertEqual("observe_before_retry", read_worker_outcome(1, path).action)
            self.assertEqual("retry_transient", read_worker_outcome(1, path, len(previous.encode())).action)

    def test_messages_name_local_recovery_not_unrelated_framework_maintenance(self):
        self.assertIn("Correct the reported arguments", recovery_message("correct_invocation_and_retry"))
        self.assertIn("existing host authentication", recovery_message("check_existing_auth"))
        self.assertEqual("correct_invocation_and_retry", WorkerOutcome(2).action)
        self.assertEqual("retry_transient", self.read({"status": 503}, returncode=2).action)


if __name__ == "__main__":
    unittest.main()
