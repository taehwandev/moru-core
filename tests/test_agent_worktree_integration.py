from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_worktree_identity import (
    WorktreeSessionError,
    new_worktree_path,
    resolve_base_ref,
    worktree_root,
)
from agent_worktree_integration import finalize_worker_worktree
from agent_worktree_session import create_worker_worktree


class FinalizeWorkerWorktreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary_directory.name) / "project"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(".moru/\n", encoding="utf-8")
        (self.project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Moru Core Tests")
        self._git("add", "-A")
        self._git("commit", "-qm", "initial")
        self.baseline_worktrees = self._git("worktree", "list", "--porcelain").stdout
        self.worktree = new_worktree_path(self.project)
        create_worker_worktree(
            self.project,
            resolve_base_ref(self.project),
            self.worktree,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=self.project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_unintegrated_result_is_rejected_and_preserved(self) -> None:
        (self.worktree / "worker-only.txt").write_text("worker result\n", encoding="utf-8")

        with self.assertRaisesRegex(WorktreeSessionError, "not integrated"):
            finalize_worker_worktree(self.project, self.worktree)

        self.assertEqual(
            "worker result\n",
            (self.worktree / "worker-only.txt").read_text(encoding="utf-8"),
        )
        self.assertIn(
            str(self.worktree.resolve()),
            self._git("worktree", "list").stdout.decode("utf-8"),
        )

    def test_integrated_result_removes_worktree_and_restores_persistent_state(self) -> None:
        (self.worktree / "worker-only.txt").write_text("worker result\n", encoding="utf-8")
        (self.worktree / "tracked.txt").write_text("updated\n", encoding="utf-8")
        (self.project / "worker-only.txt").write_text("worker result\n", encoding="utf-8")
        (self.project / "tracked.txt").write_text("updated\n", encoding="utf-8")

        result = finalize_worker_worktree(self.project, self.worktree)

        self.assertEqual(2, result.integrated_path_count)
        self.assertFalse(self.worktree.exists())
        self.assertEqual(
            self.baseline_worktrees,
            self._git("worktree", "list", "--porcelain").stdout,
        )
        self.assertFalse(worktree_root(self.project).exists())
        self.assertEqual(
            "worker result\n",
            (self.project / "worker-only.txt").read_text(encoding="utf-8"),
        )

    def test_ignored_worker_file_requires_explicit_discard_policy(self) -> None:
        (self.worktree / ".gitignore").write_text(
            ".moru/\nignored-output.txt\n",
            encoding="utf-8",
        )
        (self.project / ".gitignore").write_text(
            ".moru/\nignored-output.txt\n",
            encoding="utf-8",
        )
        (self.worktree / "ignored-output.txt").write_text("not collected\n", encoding="utf-8")

        with self.assertRaisesRegex(WorktreeSessionError, "ignored worker files"):
            finalize_worker_worktree(self.project, self.worktree)

        self.assertTrue((self.worktree / "ignored-output.txt").exists())

    def test_explicit_policy_can_discard_ignored_files_after_other_results_integrate(self) -> None:
        (self.worktree / ".gitignore").write_text(
            ".moru/\nignored-output.txt\n",
            encoding="utf-8",
        )
        (self.project / ".gitignore").write_text(
            ".moru/\nignored-output.txt\n",
            encoding="utf-8",
        )
        (self.worktree / "ignored-output.txt").write_text("disposable\n", encoding="utf-8")

        result = finalize_worker_worktree(
            self.project,
            self.worktree,
            discard_ignored=True,
        )

        self.assertEqual(1, result.integrated_path_count)
        self.assertEqual(1, result.discarded_ignored_path_count)
        self.assertFalse(self.worktree.exists())


if __name__ == "__main__":
    unittest.main()
