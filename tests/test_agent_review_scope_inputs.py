from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_review_scope_inputs import reviewed_local_unit_matches, scoped_review_binding, scoped_review_digest


class UnbornReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.git("init", "-q")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.project, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_untracked_scope_and_staging_are_bound(self):
        selected = self.project / "screen.jsx"
        selected.write_text("initial")
        original = scoped_review_digest(self.project, ["screen.jsx"], include_index=True)
        self.assertEqual(["screen.jsx"], scoped_review_binding(self.project, ["screen.jsx"])["changed_paths"])
        (self.project / "other.jsx").write_text("unrelated")
        self.assertEqual(original, scoped_review_digest(self.project, ["screen.jsx"], include_index=True))
        selected.write_text("changed")
        edited = scoped_review_digest(self.project, ["screen.jsx"], include_index=True)
        self.assertNotEqual(original, edited)
        self.git("add", "screen.jsx")
        staged = scoped_review_digest(self.project, ["screen.jsx"], include_index=True)
        self.assertNotEqual(edited, staged)
        selected.write_text("edited after staging")
        self.assertNotEqual(staged, scoped_review_digest(self.project, ["screen.jsx"], include_index=True))

    def test_first_commit_invalidates_unborn_binding(self):
        (self.project / "screen.jsx").write_text("reviewed")
        before = scoped_review_digest(self.project, ["screen.jsx"], include_index=True)
        self.git("add", "screen.jsx")
        recorded = scoped_review_binding(self.project, ["screen.jsx"], include_index=True)
        self.assertTrue(reviewed_local_unit_matches(self.project, ["screen.jsx"], recorded))
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "first")
        self.assertNotEqual(before, scoped_review_digest(self.project, ["screen.jsx"], include_index=True))
        self.assertFalse(reviewed_local_unit_matches(self.project, ["screen.jsx"], recorded))


if __name__ == "__main__":
    unittest.main()
