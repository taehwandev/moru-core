from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path

from scripts.migrate_moru_local_state import migrate_dir, project_state_dirs, tracked_top_level


class MoruLocalStateMigrationTests(unittest.TestCase):
    def test_moves_records_and_preserves_tracked_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            old = project / ".tao"
            (old / "skills").mkdir(parents=True)
            (old / "skills" / "SKILL.md").write_text("tracked", encoding="utf-8")
            (old / ".gitignore").write_text("/*\n", encoding="utf-8")
            (old / "runs").mkdir()
            (old / "runs" / "one.json").write_text("record", encoding="utf-8")
            new = project / ".moru"

            moved = migrate_dir(old, new, protected={"skills", ".gitignore"}, apply=True)

            self.assertEqual(1, moved)
            self.assertEqual("tracked", (old / "skills" / "SKILL.md").read_text())
            self.assertTrue((old / "runs").is_symlink())
            self.assertEqual("record", (new / "runs" / "one.json").read_text())
            self.assertEqual((old / "runs" / "one.json").resolve(),
                             (new / "runs" / "one.json").resolve())
            self.assertTrue((new / "state-ready").is_file())
            self.assertEqual("# Moru Core local runtime records\n/*\n",
                             (new / ".gitignore").read_text())
            self.assertEqual(0, migrate_dir(old, new, protected={"skills", ".gitignore"}, apply=True))

    def test_fails_before_a_name_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            old, new = project / ".tao", project / ".moru"
            old.mkdir()
            new.mkdir()
            (old / "runs").mkdir()
            (new / "runs").mkdir()
            with self.assertRaisesRegex(RuntimeError, "target collision"):
                migrate_dir(old, new, protected=set(), apply=True)
            self.assertTrue((old / "runs").is_dir())
            self.assertFalse((new / "state-ready").exists())

    def test_detects_tracked_guidance_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".tao" / "skills").mkdir(parents=True)
            (project / ".tao" / "skills" / "SKILL.md").write_text("tracked", encoding="utf-8")
            (project / ".tao" / "runs").mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "add", ".tao/skills/SKILL.md"], check=True)
            self.assertEqual({"skills"}, tracked_top_level(project))

    def test_preserves_existing_moru_workspace_during_global_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            old, new = home / ".tao", home / ".moru"
            old.mkdir()
            (old / "tao-root").write_text("root\n", encoding="utf-8")
            (new / "workspace").mkdir(parents=True)
            (new / "workspace" / ".moru-dev").touch()
            migrate_dir(old, new, protected=set(), apply=True, is_global=True)
            self.assertTrue((old / "tao-root").is_symlink())
            self.assertEqual("root\n", (new / "tao-root").read_text())
            self.assertTrue((new / "workspace" / ".moru-dev").exists())
            self.assertFalse((new / ".gitignore").exists())

    def test_scans_linked_worktree_state_but_skips_state_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "project"
            (root / ".tao" / "worktrees" / "slice" / ".tao").mkdir(parents=True)
            (root / ".tao" / "verification" / "fixture" / ".tao").mkdir(parents=True)
            found = project_state_dirs(workspace)
            self.assertEqual([root / ".tao" / "worktrees" / "slice" / ".tao",
                              root / ".tao"], found)

    def test_existing_git_worktree_path_survives_compatibility_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Test",
                            "-c", "user.email=test@example.invalid", "commit",
                            "--allow-empty", "-qm", "initial"], check=True)
            old = project / ".tao"
            old.mkdir()
            worktree = old / "worktrees" / "slice"
            subprocess.run(["git", "-C", str(project), "worktree", "add", "-qb",
                            "slice", str(worktree)], check=True)

            migrate_dir(old, project / ".moru", protected=set(), apply=True)

            self.assertTrue((old / "worktrees").is_symlink())
            result = subprocess.run(["git", "-C", str(project), "worktree", "list",
                                     "--porcelain"], check=True, capture_output=True, text=True)
            self.assertIn(str(worktree), result.stdout)
            subprocess.run(["git", "-C", str(worktree), "status", "--short"], check=True,
                           capture_output=True)


if __name__ == "__main__":
    unittest.main()
