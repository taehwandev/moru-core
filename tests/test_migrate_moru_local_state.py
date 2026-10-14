from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from migrate_moru_local_state import apply_plan, legacy_state_dirs, plan, tracked_paths  # noqa: E402
from support import legacy_names  # noqa: E402


class MoruLocalStateMigrationTests(unittest.TestCase):
    def _git(self, project: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)

    def test_moves_records_without_links_and_keeps_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            old = project / legacy_names.STATE_DIR
            (old / "skills").mkdir(parents=True)
            (old / "skills" / "SKILL.md").write_text("tracked", encoding="utf-8")
            project.mkdir(exist_ok=True)
            self._git(project, "init", "-q")
            self._git(project, "add", "-f", f"{legacy_names.STATE_DIR}/skills/SKILL.md")
            (old / "runs").mkdir()
            (old / "runs" / "one.json").write_text("record", encoding="utf-8")
            new = project / ".moru"

            kept = apply_plan(old, new, plan(old, new, tracked_paths(old)), is_global=False)

            self.assertEqual([old / "skills" / "SKILL.md"], kept)
            self.assertEqual("tracked", (old / "skills" / "SKILL.md").read_text())
            self.assertFalse((old / "runs").exists() or (old / "runs").is_symlink())
            self.assertEqual("record", (new / "runs" / "one.json").read_text())
            self.assertEqual("# Moru Core local runtime records\n/*\n", (new / ".gitignore").read_text())
            self.assertFalse((new / "state-ready").exists())

    def test_links_are_removed_and_a_drained_tree_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            old, new = project / legacy_names.STATE_DIR, project / ".moru"
            (new / "runs").mkdir(parents=True)
            old.mkdir()
            (old / "runs").symlink_to(os.path.relpath(new / "runs", old), target_is_directory=True)
            (old / "state-ready").touch()

            apply_plan(old, new, plan(old, new, set()), is_global=False)

            self.assertFalse(old.exists())
            self.assertTrue((new / "runs").is_dir())

    def test_the_newer_copy_wins_and_directories_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            old, new = project / legacy_names.STATE_DIR, project / ".moru"
            (old / "runs" / "a").mkdir(parents=True)
            (new / "runs" / "b").mkdir(parents=True)
            (new / "snapshot.json").write_text("older", encoding="utf-8")
            time.sleep(0.01)
            (old / "snapshot.json").write_text("newer", encoding="utf-8")

            apply_plan(old, new, plan(old, new, set()), is_global=False)

            self.assertEqual("newer", (new / "snapshot.json").read_text())
            self.assertTrue((new / "runs" / "a").is_dir())
            self.assertTrue((new / "runs" / "b").is_dir())
            self.assertFalse(old.exists())

    def test_a_type_collision_stops_before_any_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            old, new = project / legacy_names.STATE_DIR, project / ".moru"
            (old / "runs").mkdir(parents=True)
            new.mkdir()
            (new / "runs").write_text("file", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                plan(old, new, set())
            self.assertTrue((old / "runs").is_dir())

    def test_inventory_finds_nested_worktree_state_deepest_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            outer = workspace / "repo" / legacy_names.STATE_DIR
            inner = outer / "worktrees" / "task" / legacy_names.STATE_DIR
            inner.mkdir(parents=True)

            self.assertEqual([inner, outer], legacy_state_dirs(workspace))


if __name__ == "__main__":
    unittest.main()
