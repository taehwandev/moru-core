"""gate-batch previews the structure review that the review hook will run."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_review_structure_preview import structure_review_preview


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class StructureReviewPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "user.name", "t")
        self.source = self.root / "big.py"
        self.source.write_text("".join(f"VALUE_{i} = {i}\n" for i in range(320)), encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-q", "-m", "init")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_clean_tree_previews_nothing(self) -> None:
        self.assertEqual([], structure_review_preview(self.root))

    def test_large_changed_file_names_the_evidence_review_will_require(self) -> None:
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write("EXTRA = 1\n")
        lines = structure_review_preview(self.root)
        self.assertEqual(1, len(lines))
        self.assertIn("--structure-review-evidence", lines[0])
        self.assertIn("big.py", lines[0])

    def test_oversized_block_is_previewed_as_a_failure(self) -> None:
        body = "".join(f"    x_{i} = {i}\n" for i in range(130))
        (self.root / "small.py").write_text(f"def long():\n{body}", encoding="utf-8")
        lines = structure_review_preview(self.root)
        self.assertTrue(any("will fail on" in line and "small.py" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
