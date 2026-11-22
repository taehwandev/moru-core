from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_hook_runtime import run_command  # noqa: E402
from agent_review_hook import initial_import_comparison  # noqa: E402
from agent_review_structure import changed_source_paths  # noqa: E402
from agent_worktree_fingerprint import worktree_fingerprint  # noqa: E402
from agent_worktree_scan import WorktreeFingerprintLimitExceeded  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root, check=True,
                   capture_output=True)


def write_module(root: Path, name: str, lines: int) -> None:
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / name).write_text("\n".join(f"export const v{i} = {i};" for i in range(lines)) + "\n")


class EmptyHeadIsNoBaselineTests(unittest.TestCase):
    def metadata(self, root: Path) -> dict:
        info, checked = changed_source_paths(root, run_command)
        self.assertTrue(checked, "the new module must be among the checked paths")
        return info["path_metadata"]

    def test_a_head_with_an_empty_tree_keeps_the_initial_full_build_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            git(root, "commit", "-q", "--allow-empty", "-m", "init")
            write_module(root, "big.js", 416)
            git(root, "add", ".")
            records = self.metadata(root)
        self.assertTrue(all(r.get("initial_full_build") for r in records.values()), records)

    def test_a_head_with_content_still_applies_the_incremental_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            write_module(root, "first.js", 3)
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "first")
            write_module(root, "big.js", 416)
            git(root, "add", ".")
            records = self.metadata(root)
        self.assertFalse(any(r.get("initial_full_build") for r in records.values()), records)

    def test_a_commit_that_deleted_everything_keeps_the_incremental_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            write_module(root, "old.js", 3)
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "first")
            git(root, "rm", "-q", "-r", "src")
            git(root, "commit", "-q", "-m", "delete all")
            write_module(root, "big.js", 416)
            git(root, "add", ".")
            records = self.metadata(root)
        self.assertFalse(any(r.get("initial_full_build") for r in records.values()), records)

    def test_an_unborn_head_is_still_an_initial_full_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            write_module(root, "big.js", 416)
            records = self.metadata(root)
        self.assertTrue(all(r.get("initial_full_build") for r in records.values()), records)


class InitialImportReviewTests(unittest.TestCase):
    def test_import_compares_only_the_staged_upstream_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            write_module(root, "inherited.js", 416)
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "upstream")
            upstream = run_command(["git", "rev-parse", "HEAD"], root)["stdout"].strip()
            args = SimpleNamespace(project=root, review_scope="working-tree", initial_import_base=upstream)
            with self.assertRaisesRegex(ValueError, "unborn"):
                initial_import_comparison(args, run_command, [])
            git(root, "symbolic-ref", "HEAD", "refs/heads/import")
            write_module(root, "changed.js", 5)
            with self.assertRaisesRegex(ValueError, "fully staged|all paths staged"):
                initial_import_comparison(args, run_command, [])
            git(root, "add", ".")
            comparison = initial_import_comparison(args, run_command, [])
            _, paths = changed_source_paths(root, run_command, review_commits=comparison)
            self.assertEqual(paths, [Path("src/changed.js")])
            with self.assertRaisesRegex(ValueError, "whole working-tree"):
                initial_import_comparison(args, run_command, ["src/changed.js"])
            write_module(root, "changed.js", 6)
            with self.assertRaisesRegex(ValueError, "all paths staged"):
                initial_import_comparison(args, run_command, [])

    def test_only_fully_staged_first_imports_use_the_larger_fingerprint_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            write_module(root, "one.js", 1)
            write_module(root, "two.js", 2)
            with patch("agent_worktree_fingerprint.MAX_UNTRACKED_FILES", 1):
                with self.assertRaises(WorktreeFingerprintLimitExceeded):
                    worktree_fingerprint(root)
                git(root, "add", ".")
                previous = worktree_fingerprint(root)
                write_module(root, "two.js", 3)
                with self.assertRaises(WorktreeFingerprintLimitExceeded):
                    worktree_fingerprint(root)
                git(root, "add", ".")
                self.assertNotEqual(previous, worktree_fingerprint(root))


if __name__ == "__main__":
    unittest.main()
