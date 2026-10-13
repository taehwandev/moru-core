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
    generated_worker_path,
    new_worktree_path,
    resolve_base_ref,
    validate_worker_worktree_identity,
    worktree_root,
)


class WorktreeIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary_directory.name) / "project"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(".tao/\n", encoding="utf-8")
        (self.project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        for args in (
            ("init", "-q"),
            ("config", "user.email", "tests@example.invalid"),
            ("config", "user.name", "Tao Agent OS Tests"),
            ("add", "-A"),
            ("commit", "-qm", "initial"),
        ):
            subprocess.run(
                ["git", *args],
                cwd=self.project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_rejects_standalone_repo_under_worker_root(self) -> None:
        impostor = worktree_root(self.project) / ("f" * 16)
        impostor.mkdir(parents=True)
        subprocess.run(
            ["git", "init", "-q"],
            cwd=impostor,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        with self.assertRaisesRegex(WorktreeSessionError, "same git repository"):
            validate_worker_worktree_identity(self.project, impostor)

    def test_validates_linked_worktree_as_same_repository(self) -> None:
        worktree_path = new_worktree_path(self.project)
        worktree_path.parent.mkdir(parents=True)
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree_path),
                resolve_base_ref(self.project),
            ],
            cwd=self.project,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(
            worktree_path.resolve(),
            validate_worker_worktree_identity(self.project, worktree_path),
        )

    def test_rejects_symlinked_worker_root(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            tao_dir = self.project / ".tao"
            tao_dir.mkdir()
            (tao_dir / "worktrees").symlink_to(
                Path(outside_dir),
                target_is_directory=True,
            )

            with self.assertRaisesRegex(WorktreeSessionError, "symlink"):
                generated_worker_path(
                    self.project,
                    new_worktree_path(self.project),
                )

    def test_migrated_project_creates_worker_paths_under_moru(self) -> None:
        moru_dir = self.project / ".moru"
        moru_dir.mkdir()
        (moru_dir / "state-ready").touch()
        (self.project / ".tao").symlink_to(moru_dir, target_is_directory=True)

        candidate = new_worktree_path(self.project)
        self.assertEqual(moru_dir / "worktrees", candidate.parent)
        self.assertEqual(candidate.resolve(), generated_worker_path(self.project, candidate))

    def test_resolve_base_ref_rejects_non_repository(self) -> None:
        with tempfile.TemporaryDirectory() as plain_dir:
            with self.assertRaises(WorktreeSessionError):
                resolve_base_ref(Path(plain_dir))


if __name__ == "__main__":
    unittest.main()
