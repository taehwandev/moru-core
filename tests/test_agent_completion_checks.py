"""Real native policy connected to existing checkpoint, gate, finish and Stop."""
import json
import os
import fcntl
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import agent_hook_gate_records as hooks
from agent_completion_checks import progress_note, quality_notes
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_packet import validate_continuation_packet
from agent_gate_evidence import record_gate_evidence
from agent_work_completion import work_completion_failures
from native_pretool_support import PROJECT, environment, prepare
from test_agent_run_interruption import Run
from test_native_completion import contract


class CompletionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="completion-wiring-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        prepare(self.base)
        scope = patch.dict(os.environ, environment(self.base), clear=True)
        scope.start()
        self.addCleanup(scope.stop)
        (self.base / "run").mkdir()
        self.run = Run(str(self.base / "run"), packet=True, writable=True)
        self.checkpoint(work={"objective": "Deliver requirements", "remaining_work": []}, kind="initial")

    def checkpoint(self, work, kind="decision"):
        return write_continuation_checkpoint(project=self.run.project, rules=self.run.project,
            run_id=self.run.run["run_id"], binding_path=self.run.evidence, kind=kind, phase="acting", work=work)

    def test_opt_in_requirements_block_finish_until_gate_and_file_are_observed(self):
        required = contract(gate="verify")
        self.checkpoint({"requirements": required})
        self.assertTrue(work_completion_failures(self.run.project, self.run.evidence))
        record_gate_evidence(evidence_path=self.run.evidence, preflight=self.run.binding,
            gate="verify", status="SUCCESS", evidence="Observed fixture verification")
        self.assertTrue(work_completion_failures(self.run.project, self.run.evidence))
        (self.run.project / "plan.md").write_text("Delivered\n")
        self.assertEqual([], work_completion_failures(self.run.project, self.run.evidence))
        (self.run.project / "plan.md").unlink()
        self.assertTrue(work_completion_failures(self.run.project, self.run.evidence))

    def test_revision_changes_preserve_ids_and_atomic_prior_checkpoint(self):
        self.checkpoint({"requirements": contract(gate="verify")})
        path = self.run.evidence.parent / "continuation.json"
        original = path.read_bytes()
        for changed in (contract(gate="verify", owner="changed"), contract(2, id="r2", gate="verify")):
            with self.assertRaises(ValueError): self.checkpoint({"requirements": changed})
            self.assertEqual(original, path.read_bytes())
        self.checkpoint({"requirements": contract(2, owner="changed", gate="verify")})
        self.assertEqual(2, json.loads(path.read_text())["work"]["requirements"]["revision"])

    def test_real_finish_cli_cannot_close_a_missing_requirement_artifact(self):
        self.checkpoint({"requirements": contract(gate="verify")})
        result = subprocess.run([sys.executable, "-B", str(PROJECT / "scripts/agent-hook.py"), "finish",
            "--project", str(self.run.project), "--rules", str(self.run.project), "--evidence", str(self.run.evidence)],
            env={**os.environ, "CODEX_THREAD_ID": "bound-session"}, capture_output=True, text=True, timeout=10)
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("delivery is still pending", result.stdout)
        self.assertIn("requirement r1", result.stdout)
        self.assertNotEqual("completed", self.run.state())
        self.assertFalse(list(self.run.evidence.parent.glob("finish.json")))

    def test_legacy_contract_and_native_unavailable_remain_honest(self):
        self.assertEqual([], work_completion_failures(self.run.project, self.run.evidence))
        self.checkpoint({"requirements": contract(gate="verify")})
        with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
            self.assertIn("unavailable", work_completion_failures(self.run.project, self.run.evidence)[0])
            with self.assertRaises(ValueError): self.checkpoint({"requirements": contract(2, gate="verify")})

    def test_closed_contract_depth_does_not_relax_other_packet_fields(self):
        path = self.run.evidence.parent / "continuation.json"
        packet = json.loads(path.read_text())
        packet["work"]["requirements"] = contract(gate="verify")
        self.assertEqual([], validate_continuation_packet(packet))
        packet["work"]["objective"] = [[[[["too deep"]]]]]
        self.assertIn("depth_exceeded", [v["rule"] for v in validate_continuation_packet(packet)])

    def test_gate_and_batch_surface_native_warnings_without_an_extra_gate(self):
        entry = {"gate": "tests", "status": "SUCCESS", "fields": {"check": "echo passed", "result": "1 test passed"}}
        self.assertIn("fixed-output", quality_notes([entry])[0])
        args = SimpleNamespace(field=[], gate_name="tests", gate_evidence="", source="runtime", status="SUCCESS",
                               output=None, repair_cycle=0, project=self.run.project)
        with patch.object(hooks, "record_hook_gate", return_value=entry), \
             patch.object(hooks, "_auto_bridge_retrospective_if_needed", return_value=[]), \
             patch.object(hooks, "finish_with_result", return_value=0) as finish:
            self.assertEqual(0, hooks.gate_hook(args))
            self.assertTrue(any("quality warning" in line for line in finish.call_args.args[2]))
        with patch.object(hooks, "_gate_records_from_args", return_value=[entry]), \
             patch.object(hooks, "record_hook_gate_batch", return_value=[entry]), \
             patch.object(hooks, "_auto_bridge_retrospective_if_needed", return_value=[]), \
             patch.object(hooks, "_gate_progress", return_value={"remaining_gates": []}), \
             patch.object(hooks, "finish_with_result", return_value=0) as finish:
            self.assertEqual(0, hooks.gate_batch_hook(args))
            self.assertTrue(any("quality warning" in line for line in finish.call_args.args[2]))

    def test_progress_is_session_bound_and_does_not_grant_more_continuations(self):
        from agent_stop_continuation import continuation_reason
        self.checkpoint({"remaining_work": [{"checkpoint": "verify", "action": "Check the result"}]})
        payload = {"session_id": "bound-session"}
        for _ in range(2):
            self.assertNotIn("three Stop", continuation_reason(payload, "codex", self.run.project, self.run.evidence))
        reason = continuation_reason(payload, "codex", self.run.project, self.run.evidence)
        self.assertIn("three Stop", reason)
        self.assertIn("one per turn", reason)
        self.assertIsNone(continuation_reason({**payload, "stop_hook_active": True}, "codex", self.run.project, self.run.evidence))
        work = json.loads((self.run.evidence.parent / "continuation.json").read_text())["work"]
        self.assertEqual("", progress_note(self.run.project, self.run.evidence, work, {"runtime": "codex", "session_id": "other"}))
        self.assertNotEqual("completed", self.run.state())

    def test_progress_lock_contention_and_symlinks_never_hold_stop_or_change_data(self):
        work = {"remaining_work": [{"checkpoint": "verify", "action": "Check"}], "blockers": []}
        identity = {"runtime": "codex", "session_id": "bound-session"}
        self.assertEqual("", progress_note(self.run.project, self.run.evidence, work, identity))
        path = next(self.run.evidence.parent.glob("completion-progress-*.json"))
        original = path.read_bytes()
        lock = path.with_name("." + path.name + ".lock")
        code = ("import json,sys; from pathlib import Path; from agent_completion_checks import progress_note; "
                "v=json.load(sys.stdin); print(progress_note(Path(v['project']),Path(v['evidence']),v['work'],v['identity']))")
        payload = {"project": str(self.run.project), "evidence": str(self.run.evidence), "work": work, "identity": identity}
        with lock.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([sys.executable, "-B", "-c", code], input=json.dumps(payload).encode(),
                cwd=PROJECT, env={**os.environ, "PYTHONPATH": "scripts"}, capture_output=True, timeout=3)
        self.assertEqual((0, b"\n", b""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(original, path.read_bytes())
        lock.unlink()
        target = self.base / "outside-lock"
        target.write_text("unchanged")
        lock.symlink_to(target)
        self.assertEqual("", progress_note(self.run.project, self.run.evidence, work, identity))
        self.assertEqual("unchanged", target.read_text())
        self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
