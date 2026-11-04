from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_structure import structure_review


class MergeStructureBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Merge Baseline Test")
        self.git("config", "user.email", "merge@example.invalid")
        self.write("src/combined.py", "first = 0\n" + "\n" * 12 + "last = 0\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args, expected=0):
        result = subprocess.run(
            ["git", *args], cwd=self.project, text=True, capture_output=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr)
        return result

    def write(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def merge(self, conflict=False):
        self.git("checkout", "-qb", "incoming")
        self.write("src/large.py", "".join(f"value_{i} = {i}\n" for i in range(355)))
        self.write("src/owners.py", "".join(f"class Owner{i}:\n    pass\n\n" for i in range(5)))
        self.write("src/combined.py", "first = 1\n" + "\n" * 12 + "last = 0\n")
        self.commit("incoming")
        self.incoming = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-qb", "task", self.base)
        combined = "first = 2\n" + "\n" * 12 + "last = 0\n" if conflict else (
            "first = 0\n" + "\n" * 12 + "last = 1\n"
        )
        self.write("src/combined.py", combined)
        self.commit("task")
        self.git("merge", "--no-commit", "--no-ff", "incoming", expected=1 if conflict else 0)

    @staticmethod
    def run_command(command, cwd):
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

    def review(self, runner=None, **kwargs):
        return structure_review(self.project, 500, 120, runner or self.run_command, **kwargs)

    def test_parent_files_are_baseline_and_full_scope_is_preserved(self):
        self.merge()
        review = self.review()
        self.assertEqual([], review["failures"])
        self.assertEqual(self.incoming, review["inherited_merge_paths"]["src/large.py"])
        self.assertIn("src/owners.py", review["inherited_merge_paths"])
        self.assertEqual(
            {"src/large.py", "src/owners.py", "src/combined.py"},
            set(review["discovery"]["path_metadata"]),
        )
        self.assertIn("src/combined.py", review["strict_checked_paths"])
        self.assertNotIn("src/combined.py", review["inherited_merge_paths"])

    def test_identical_files_outside_a_merge_keep_ordinary_structure_checks(self):
        self.merge()
        self.git("merge", "--quit")
        review = self.review()
        self.assertEqual({}, review["inherited_merge_paths"])
        self.assertTrue(any("adds 355 lines" in item for item in review["failures"]))
        self.assertTrue(any("top-level owners" in item for item in review["failures"]))

    def test_staged_new_edit_is_checked(self):
        self.merge()
        with (self.project / "src/large.py").open("a") as stream:
            stream.write("new_value = 356\n")
        self.git("add", "src/large.py")
        review = self.review()
        self.assertNotIn("src/large.py", review["inherited_merge_paths"])
        self.assertTrue(any("adds 356 lines" in item for item in review["failures"]))

    def test_unstaged_edits_disable_parent_reuse(self):
        self.merge()
        self.write("src/combined.py", "unstaged = 1\n")
        review = self.review()
        self.assertEqual({}, review["inherited_merge_paths"])
        self.assertTrue(review["failures"])

    def test_unresolved_conflict_disables_parent_reuse(self):
        self.merge(conflict=True)
        review = self.review()
        self.assertEqual({}, review["inherited_merge_paths"])
        self.assertTrue(review["failures"])

    def test_untracked_new_source_is_checked(self):
        self.merge()
        self.write("src/new.py", "".join(f"value_{i} = {i}\n" for i in range(355)))
        review = self.review()
        self.assertNotIn("src/new.py", review["inherited_merge_paths"])
        self.assertTrue(any("src/new.py adds 355 lines" in item for item in review["failures"]))

    def test_changed_file_mode_is_checked(self):
        self.merge()
        (self.project / "src/large.py").chmod(0o755)
        self.git("add", "src/large.py")
        review = self.review()
        self.assertNotIn("src/large.py", review["inherited_merge_paths"])
        self.assertTrue(review["failures"])

    def test_git_query_failure_retains_ordinary_checks(self):
        self.merge()

        def runner(command, cwd):
            if command[:2] == ["git", "ls-tree"]:
                return {"returncode": 1, "stdout": "", "stderr": "query unavailable"}
            return self.run_command(command, cwd)

        review = self.review(runner)
        self.assertEqual({}, review["inherited_merge_paths"])
        self.assertTrue(review["failures"])

    def test_commit_range_uses_its_committed_subject(self):
        self.merge()
        review = self.review(review_commits=(self.base, self.incoming))
        self.assertEqual({}, review["inherited_merge_paths"])
        self.assertTrue(review["failures"])


if __name__ == "__main__":
    unittest.main()
