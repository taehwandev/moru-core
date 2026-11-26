from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_structure import changed_source_paths
from agent_workspace_policy import (
    is_git_status_review_only,
    is_non_git_workspace,
    is_writing_workspace,
)


def load_collect_failures():
    spec = importlib.util.spec_from_file_location("agent_preflight_script", ROOT / "scripts" / "agent-preflight.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("agent-preflight.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.collect_failures


class AgentWorkspacePolicyTests(unittest.TestCase):
    def test_writing_workspace_is_detected_from_local_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "drafts").mkdir()
            (project / "AGENTS.md").write_text(
                "# Writing Workspace Instructions\n"
                "Use this folder as the primary workspace for blog posts.\n",
                encoding="utf-8",
            )

            self.assertTrue(is_writing_workspace(project))

    def test_preflight_allows_review_only_git_status_for_writing_workspace(self) -> None:
        collect_failures = load_collect_failures()
        failures = collect_failures(
            {"returncode": 0},
            {"missing": []},
            "",
            {"returncode": 128, "review_only": True},
            {"returncode": 0},
            [],
        )

        self.assertEqual([], failures)

    def test_structure_review_skips_git_discovery_for_non_git_writing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "drafts").mkdir()
            (project / "AGENTS.md").write_text(
                "---\nkeyflow_id: local_writing_workspace\n---\n"
                "# Writing Workspace Instructions\n",
                encoding="utf-8",
            )

            def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
                return {
                    "command": command,
                    "cwd": str(cwd),
                    "returncode": 128,
                    "stdout": "",
                    "stderr": "fatal: not a git repository",
                }

            discovery, paths = changed_source_paths(project, run_command)

            self.assertEqual([], paths)
            self.assertEqual([], discovery["command_errors"])
            self.assertEqual("non_git_workspace", discovery["review_only"])


    def test_git_environment_and_successful_rev_parse_require_git_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "work"
            project.mkdir()
            repo = root / "store.git"
            subprocess.run(["git", "init", "-q", "--bare", str(repo)], check=True)
            self.assertFalse(is_non_git_workspace(repo))  # rev-parse succeeds without a .git child.
            with patch.dict(os.environ, {"GIT_DIR": str(repo), "GIT_WORK_TREE": str(project)}):
                self.assertFalse(is_non_git_workspace(project))
                self.assertFalse(is_git_status_review_only(project, {"returncode": 128}))

    def test_review_and_finish_check_markdown_hard_breaks_in_a_git_writing_workspace(self):
        from agent_command_runtime import run_command
        from agent_finish_final_checks import run_final_checks
        from agent_review_hook import record_review_diff_checks

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "drafts").mkdir()
            instructions = project / "AGENTS.md"
            instructions.write_text("# Writing Workspace Instructions\n")
            draft = project / "drafts/post.md"
            source = project / "script.py"
            draft.write_text("old\n")
            source.write_text("old\n")
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            for hard_break, bad_source, writing, expected in (
                    ("line  ", False, True, True), ("line ", False, True, False),
                    ("line  ", True, True, False), ("line  ", False, False, False)):
                with self.subTest(hard_break=hard_break, bad_source=bad_source, writing=writing):
                    instructions.write_text("# Writing Workspace Instructions\n" if writing else "Project\n")
                    for trailer in ("staged", "worktree"):
                        draft.write_text(trailer + hard_break + "\nnext\n")
                        source.write_text(trailer + ("  " if bad_source else "") + "\n")
                        if trailer == "staged":
                            subprocess.run(["git", "add", "."], cwd=project, check=True)
                    checks, failures = {}, []
                    record_review_diff_checks(SimpleNamespace(project=project), checks, failures, run_command,
                                              [], {"kind": "working-tree"}, status_before={}, local_config_scope=False)
                    for key in ("diff_check", "staged_diff_check"):
                        self.assertEqual(expected, checks[key]["returncode"] == 0)
                    signals = []
                    with patch("agent_finish_final_checks.run_workflow_validate", return_value={"returncode": 0}):
                        _, diff, _, _ = run_final_checks(ROOT, project, ROOT, None, signals, [], read_only=True)
                    self.assertEqual(expected, diff["returncode"] == 0)
                    self.assertFalse(diff.get("skipped"))
                    if expected:
                        self.assertEqual(2, diff["git_returncode"])
                        self.assertIn("Markdown hard breaks", str(signals))

    def test_workspace_root_holding_repos_is_not_itself_a_git_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            (workspace_root / "some-repo" / ".git").mkdir(parents=True)

            self.assertTrue(is_non_git_workspace(workspace_root))
            self.assertFalse(is_non_git_workspace(workspace_root / "some-repo"))

    def test_git_status_failure_is_review_only_outside_any_repository(self) -> None:
        # A path with no repository above it cannot produce git evidence, so the
        # gate must not demand it. This is what made the gate unsatisfiable for
        # $HOME and for the ~/git workspace root.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)

            self.assertTrue(is_git_status_review_only(project, {"returncode": 128}))

    def test_git_status_failure_inside_a_repository_stays_a_real_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / ".git").mkdir()

            self.assertFalse(is_git_status_review_only(project, {"returncode": 128}))

    def test_successful_git_status_is_never_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(is_git_status_review_only(Path(temp_dir), {"returncode": 0}))


if __name__ == "__main__":
    unittest.main()
