"""Exact writable-run authority for loop enrollment and mutations."""

from __future__ import annotations

import json
import os
import contextlib
import io
import unittest
from unittest.mock import patch

from _moru_test_support import ROOT
from agent_loop_binding import LoopBinding, _require_groups_finished, _require_no_check
from agent_loop_state import LoopRun
from agent_run_registry import process_owner, registry_path, transition_run
import test_agent_loop_state as fixture


class LoopBindingTests(unittest.TestCase):
    def setUp(self):
        self.project, self.evidence, self.run_id = fixture.loop_fixture(self)

    def deny_enrollment(self):
        with self.assertRaises(ValueError):
            LoopRun(self.project, self.run_id).start(fixture.loop_config())
        self.assertFalse((self.evidence.parent / "loop.json").exists())

    def test_exact_owner_can_take_a_transaction(self):
        with LoopBinding(self.project).transaction():
            self.assertTrue(self.evidence.exists())

    def test_read_only_flag_denies_even_writable_route(self):
        preflight = json.loads(self.evidence.read_text())
        preflight["execution_mode"]["read_only"] = True
        self.evidence.write_text(json.dumps(preflight))
        self.deny_enrollment()

    def test_intrinsic_read_route_cannot_be_widened(self):
        preflight = json.loads(self.evidence.read_text())
        preflight["route"]["command"] = "analysis"
        self.evidence.write_text(json.dumps(preflight))
        self.deny_enrollment()

    def test_foreign_session_cannot_acquire_enrollment(self):
        with patch.dict(os.environ, CODEX_THREAD_ID="foreign-session"):
            self.deny_enrollment()

    def test_failed_or_completed_run_does_not_admit_loop(self):
        for state in ("failed", "completed"):
            with self.subTest(state=state):
                transition_run(self.project, self.evidence, state)
                self.deny_enrollment()

    def test_changed_resume_generation_cannot_use_stale_binding(self):
        path = registry_path(self.project)
        payload = json.loads(path.read_text())
        payload["runs"][0]["resume_generation"] = 1
        path.write_text(json.dumps(payload))
        self.deny_enrollment()

    def test_state_symlink_is_rejected_before_read_or_write(self):
        target = self.project / "unrelated.json"
        target.write_text('{"user":"data"}')
        (self.evidence.parent / "loop.json").symlink_to(target)
        with self.assertRaises(ValueError):
            LoopBinding(self.project, self.run_id)
        self.assertEqual('{"user":"data"}', target.read_text())

    def test_late_state_symlink_cannot_redirect_a_transaction(self):
        binding = LoopBinding(self.project)
        target = self.project / "unrelated.json"
        target.write_text("untouched")
        binding.path.symlink_to(target)
        with self.assertRaises(ValueError):
            with binding.transaction():
                self.fail("symlink transaction was admitted")
        self.assertEqual("untouched", target.read_text())

    def _stamp_cli_owner(self):
        preflight = json.loads(self.evidence.read_text())
        preflight["runtime_session"] = {"runtime": "cli", "session_id": "cli-owner"}
        self.evidence.write_text(json.dumps(preflight))
        path = registry_path(self.project)
        payload = json.loads(path.read_text())
        payload["runs"][0]["owner"] = process_owner()
        path.write_text(json.dumps(payload))

    def test_cli_process_owner_can_enroll_and_mutate_without_session_environment(self):
        with patch.dict(os.environ, {"MORU_STATE_HOME": str(self.project / "state-home")}, clear=True):
            self._stamp_cli_owner()
            loop = LoopRun(self.project)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual("ready", loop.start(fixture.loop_config())["status"])
            self.assertEqual("attempting", loop.begin("owned CLI attempt")["status"])

    def test_missing_strict_session_does_not_gain_cli_fallback(self):
        with patch.dict(os.environ, {"MORU_STATE_HOME": str(self.project / "state-home")}, clear=True):
            self.deny_enrollment()

    def test_foreign_cli_process_cannot_reuse_an_explicit_run_id(self):
        with patch.dict(os.environ, {"MORU_STATE_HOME": str(self.project / "state-home")}, clear=True):
            self._stamp_cli_owner()
            path = registry_path(self.project)
            payload = json.loads(path.read_text())
            payload["runs"][0]["owner"] = {"pid": 2 ** 30, "started_at": "foreign"}
            path.write_text(json.dumps(payload))
            self.deny_enrollment()

    def test_group_probe_permission_denial_is_uncertain_and_fail_closed(self):
        state = {"inflight": {"owner": 123, "groups": [456]}}
        with patch("agent_loop_binding.os.killpg", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "child group cannot be probed"):
                _require_groups_finished(state)

    def test_owner_probe_permission_denial_is_uncertain_and_fail_closed(self):
        state = {"inflight": {"owner": 123, "groups": []}}
        with patch("agent_loop_binding.os.kill", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "process cannot be probed"):
                _require_no_check(state)

    def test_loop_does_not_automatically_reclaim_an_interrupted_task(self):
        from agent_run_interruption import record_turn_boundary
        record_turn_boundary(self.project, runtime="codex", session_id="loop-fixture", evidence=self.evidence)
        before = registry_path(self.project).read_bytes()
        self.deny_enrollment()
        self.assertEqual(before, registry_path(self.project).read_bytes())
