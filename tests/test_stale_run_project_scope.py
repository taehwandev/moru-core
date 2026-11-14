"""An untouched checkout's run must not govern opaque work elsewhere."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_claude_pretool_gate as base
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_runtime_session import resolve_runtime_evidence
from test_claude_pretool_gate import _decide, _reason, _write_preflight
from test_claude_pretool_merge_and_loops import SESSION, _run


def setUpModule():
    base.setUpModule()


def tearDownModule():
    base.tearDownModule()


class NoMutationProjectScopeTests(unittest.TestCase):
    def setUp(self):
        runtime = patch.dict(os.environ, {"MORU_PRETOOL_RUNTIME": "claude"})
        runtime.start()
        self.addCleanup(runtime.stop)

    def project(self, directory):
        project = base.CodexRepairableApprovalTests()._project(directory, linked=False).resolve()
        # Exercise the default protected-main path that reaches the lifecycle
        # hold for unreadable commands; an explicit isolation policy refuses
        # them earlier for its own independent reason.
        (project / base.gate.WORKTREE_POLICY_PATH).unlink()
        _write_preflight(project, SESSION)
        self.assertTrue(base.gate.workflow_entry_allows(project, SESSION))
        return project

    def outside_command(self, project, outside, command='"${runner%/}"'):
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
            return _decide({"tool_name": "Bash", "cwd": str(outside), "session_id": SESSION,
                            "tool_input": {"command": command}})

    def test_opaque_command_in_another_directory_is_not_held_by_untouched_run(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(Path(directory) / "main")
            outside = Path(directory) / "other"
            outside.mkdir()
            with patch.object(base.gate, "_open_run_holds", return_value=True):
                _, before = self.outside_command(project, outside)
            self.assertIn("still open", before)
            _, output = self.outside_command(project, outside)
            self.assertNotIn("still open", output)
            self.assertNotIn('"permissionDecision": "deny"', output)

    def test_opaque_command_in_same_checkout_still_waits_for_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(Path(directory))
            _, output = _run(project, '"${runner%/}"')
            self.assertIn("still open", output)

    def test_mutation_record_keeps_the_hold_on_a_command_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(Path(directory) / "main")
            outside = Path(directory) / "other"
            outside.mkdir()
            evidence = resolve_runtime_evidence(project, {"runtime": "claude", "session_id": SESSION})
            write_continuation_checkpoint(project=project, rules=project, run_id=evidence.parent.name,
                kind="pre_mutation", binding_path=evidence,
                mutation={"kind": "update", "paths": ["file.py"]})
            _, output = self.outside_command(project, outside)
            self.assertIn("still open", output)

    def test_known_publication_is_still_held_with_no_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(Path(directory) / "main")
            outside = Path(directory) / "other"
            outside.mkdir()
            _, output = self.outside_command(project, outside, f"git -C {project} push origin work")
            self.assertIn("still open", _reason(output))

    def test_other_projects_own_workflow_entry_is_still_required(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(Path(directory) / "main")
            other = base.CodexRepairableApprovalTests()._project(Path(directory) / "other").resolve()
            _, output = self.outside_command(project, other, "touch file.py")
            self.assertIn(str(other), _reason(output))
            self.assertIn("workflow start", _reason(output))
