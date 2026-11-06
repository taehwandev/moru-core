from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_hook_runtime import run_command  # noqa: E402
from agent_review_structure import changed_source_paths  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
