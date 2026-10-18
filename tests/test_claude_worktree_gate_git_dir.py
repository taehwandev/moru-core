"""The gate reads git's own files instead of running git, and must agree with it."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claude_worktree_gate as gate


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def _repository(base: Path) -> tuple[Path, Path]:
    main = base / "main"
    _git("init", "-q", "-b", "main", str(main))
    _git("-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--allow-empty", "-m", "init")
    linked = base / "linked"
    _git("-C", str(main), "worktree", "add", "-q", "-b", "task/one", str(linked))
    return main, linked


def _without_disk_reads():
    return patch.multiple(
        gate,
        _checkout_git_dir=lambda root: None,
        _common_dir_from_disk=lambda root: None,
    )


class GitDirFromDiskTests(unittest.TestCase):
    def test_disk_reads_match_git_for_main_and_linked_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main, linked = _repository(Path(tmp))
            for root in (main, linked):
                with self.subTest(root=root.name):
                    from_disk = (gate.git_common_dir(root), gate.current_branch(root))
                    with _without_disk_reads():
                        from_git = (gate.git_common_dir(root), gate.current_branch(root))
                    self.assertEqual(from_git, from_disk)
            self.assertEqual("task/one", gate.current_branch(linked))
            self.assertTrue(gate.same_git_repository(main, linked))

    def test_plain_checkouts_spawn_no_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main, linked = _repository(Path(tmp))
            with patch.object(gate.subprocess, "run", side_effect=AssertionError("git ran")):
                self.assertEqual(gate.git_common_dir(main), gate.git_common_dir(linked))
                self.assertEqual("main", gate.current_branch(main))

    def test_detached_head_is_left_to_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main, _ = _repository(Path(tmp))
            _git("-C", str(main), "checkout", "-q", "--detach")
            self.assertEqual("", gate.current_branch(main))

    def test_shapes_git_rejects_fall_back_to_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            (empty / ".git").mkdir(parents=True)
            dangling = Path(tmp) / "dangling"
            dangling.mkdir()
            (dangling / ".git").write_text("gitdir: ../missing/worktrees/x\n", encoding="utf-8")
            for root in (empty, dangling):
                with self.subTest(root=root.name):
                    self.assertIsNone(gate._common_dir_from_disk(root))
                    self.assertIsNone(gate.git_common_dir(root))


if __name__ == "__main__":
    unittest.main()
