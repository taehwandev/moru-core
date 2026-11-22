"""Headless child processes own their lifecycle even inside another runtime."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_run_owner
import workflow_spill
from agent_preflight_runtime import active_runtime_label
from agent_runtime_session import cli_runtime_session_scope, runtime_session

REAL_RUNTIME_ANCESTOR = agent_run_owner.runtime_ancestor

spec = importlib.util.spec_from_file_location("nested_hook", ROOT / "scripts/agent-hook.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class NestedRuntimeStartTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, timeout=10)
        self.contexts = contextlib.ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.dict(os.environ, {
            "PATH": os.environ["PATH"], "MORU_STATE_HOME": str(self.project / ".moru/state"),
            "CLAUDE_CODE_SESSION_ID": "parent-session",
        }, clear=True))
        self.contexts.enter_context(patch("agent_preflight_runtime.agy_runtime_bridge_issue", return_value=""))
        # The real process tree of whoever runs the suite (Claude, Codex, AGY or a
        # terminal) must not decide identity; tests that need ancestry patch it.
        self.contexts.enter_context(patch.object(agent_run_owner, "runtime_ancestor", return_value=("", "")))

    def call(self, action, *options, route="bugfix"):
        argv = ["moru-hook", action, "--project", str(self.project), "--rules", str(ROOT), *options]
        if action == "start":
            argv += ["--command", route, "--read-only", "--request", "Diagnose the local fixture",
                     "--intent", "debugging", "--target-summary", "Local fixture"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            code = hook.main()
        return code, output.getvalue()

    def test_parent_id_does_not_mask_native_child_id(self):
        for runtime, key in (("antigravity", "ANTIGRAVITY_CONVERSATION_ID"),
                             ("codex", "CODEX_THREAD_ID")):
            with (self.subTest(runtime=runtime), patch.dict(os.environ, {key: "child-session"}),
                  patch.object(agent_run_owner, "runtime_ancestor", return_value=("", ""), create=True)):
                self.assertEqual({"runtime": runtime, "session_id": "child-session"}, runtime_session())
                self.assertEqual(runtime, active_runtime_label())
                with cli_runtime_session_scope("parent-session", "claude"):
                    self.assertEqual(runtime, runtime_session()["runtime"])

    def test_agy_without_native_variables_uses_the_same_child_across_hooks(self):
        code, details = self.call("start")
        self.assertEqual(0, code, details)
        parent, = (self.project / ".moru/runs").glob("*/preflight.json")
        with patch.object(agent_run_owner, "runtime_ancestor", return_value=("antigravity", "pid-11-100"), create=True):
            self.assertEqual("antigravity", active_runtime_label())
            self.assertEqual({"runtime": "antigravity", "session_id": "pid-11-100"}, runtime_session())
            code, details = self.call("start", route="writing")
            self.assertEqual(0, code, details)
            evidence, = set((self.project / ".moru/runs").glob("*/preflight.json")) - {parent}
            self.assertEqual(runtime_session(), json.loads(evidence.read_text())["runtime_session"])
            args = Namespace(hook="finish", evidence=None, project=self.project)
            self.assertEqual(evidence, hook.preflight_evidence_path(args))
            fields = {
                "skills_checked": "agent_operating_skill", "outcome": "no_reusable_gap",
                "observation": "not_needed", "memory_decision": "not_needed",
                "memory_reason": "The fixture is temporary and has no reusable project guidance.",
                "alignment_evidence": "The child preflight binds the requested checkout and scope.",
                "causal_assessment": "The child selected its own evidence with the parent still active.",
                "learning_decision": "The runtime binding assertions cover the observed behavior.",
                "efficiency": "no_waste", "efficiency_evidence": "The child used one start attempt.",
            }
            record = {"gate": "retrospective check", "status": "SUCCESS", "fields": fields}
            code, details = self.call("gate-batch", "--gate-record", json.dumps([record]))
            self.assertEqual(0, code, details)
            code, details = self.call("finish")
            self.assertEqual(0, code, details)
        self.assertEqual(["running", "completed"], self.states())
        self.assertEqual(parent, hook.preflight_evidence_path(Namespace(hook="finish", evidence=None, project=self.project)))

    def test_markerless_sibling_processes_and_pid_reuse_do_not_collide(self):
        # Two tool shells in the same runtime, a sibling AGY, then a reused
        # PID. The hook can see process names and birth times but no child IDs.
        processes = {
            11: (20, "sh", "1"), 12: (20, "sh", "2"), 13: (21, "sh", "3"),
            20: (30, "agy-real", "100"), 21: (30, "agy-real", "101"),
            30: (1, "claude", "99"),
        }
        with (patch.object(sys, "platform", "darwin"),
              patch.object(agent_run_owner, "runtime_ancestor", REAL_RUNTIME_ANCESTOR),
              patch.object(agent_run_owner, "_darwin_process_info", side_effect=processes.get, create=True),
              patch.object(os, "getppid", side_effect=[11, 12, 13, 11])):
            def from_separate_hook():
                ancestor = getattr(agent_run_owner, "runtime_ancestor", None)
                if ancestor:
                    ancestor.cache_clear()
                    self.addCleanup(ancestor.cache_clear)
                return runtime_session()

            first = from_separate_hook()
            self.assertEqual("antigravity", first["runtime"])
            self.assertEqual(first, from_separate_hook())
            self.assertNotEqual(first, from_separate_hook())
            processes[20] = (30, "agy-real", "200")
            self.assertNotEqual(first, from_separate_hook())

    def test_denied_optional_helper_does_not_require_a_second_start(self):
        helper = self.contexts.enter_context(patch.object(workflow_spill, "spill_setup_helper_path")).return_value
        helper.is_file.side_effect = PermissionError("sandbox denied optional helper")
        os.environ["ANTIGRAVITY_CONVERSATION_ID"] = "child-session"
        # Exercise both optional-helper probes in the admitted preflight.
        code, details = self.call("start")
        self.assertEqual(0, code, details)
        self.assertEqual(["running"], self.states())
        self.assertEqual(1, len(list((self.project / ".moru/runs").iterdir())))

    def states(self):
        return [r["state"] for r in json.loads((self.project / ".moru/run-registry.json").read_text())["runs"]]

    def test_required_failure_reports_reason_and_leaves_only_the_retry(self):
        os.environ.update(MORU_AI_TOOL="agy", ANTIGRAVITY_CONVERSATION_ID="child-session")
        with patch("agent_preflight_runtime.agy_runtime_bridge_issue", return_value="required AGY bridge unavailable"):
            code, details = self.call("start")
        self.assertNotEqual(0, code)
        self.assertIn("required AGY bridge unavailable", details)
        self.assertEqual(["cancelled"], self.states())
        self.assertEqual([], list((self.project / ".moru/runs").glob("*")))
        code, details = self.call("start")
        self.assertEqual(0, code, details)
        self.assertEqual(["cancelled", "running"], self.states())
        self.assertEqual(1, len(list((self.project / ".moru/runs").iterdir())))

    def test_failed_explicit_start_preserves_caller_files(self):
        os.environ.update(MORU_AI_TOOL="agy", ANTIGRAVITY_CONVERSATION_ID="child-session")
        path = self.project / ".moru" / "custom.json"
        path.parent.mkdir()
        original = b'{"staged":"caller-owned"}\n'
        path.write_bytes(original)
        with patch("agent_preflight_runtime.agy_runtime_bridge_issue", return_value="required AGY bridge unavailable"):
            code, details = self.call("start", "--evidence", str(path))
        self.assertNotEqual(0, code)
        self.assertIn("required AGY bridge unavailable", details)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(["cancelled"], self.states())

        fresh = path.parent / "runs" / ("a" * 32) / "preflight.json"
        with patch("agent_preflight_runtime.agy_runtime_bridge_issue", return_value="required AGY bridge unavailable"):
            code, details = self.call("start", "--evidence", str(fresh))
        self.assertNotEqual(0, code)
        self.assertFalse(fresh.parent.exists())
        code, details = self.call("start", "--evidence", str(fresh))
        self.assertEqual(0, code, details)
        self.assertTrue(fresh.is_file())
