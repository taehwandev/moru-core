from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDANCE = ROOT / "common/skills/branch-cleanup/references/current-guidance.md"


class BranchCleanupGuidanceTests(unittest.TestCase):
    def test_merged_pr_fast_path_avoids_redundant_content_checks(self) -> None:
        text = GUIDANCE.read_text(encoding="utf-8")
        collapsed = " ".join(text.split())

        self.assertIn("query the forge once for all candidates", text)
        self.assertIn("recorded head SHA equals the fetched remote branch tip", collapsed)
        self.assertIn("without an ancestry check, `git cherry`, content diff", collapsed)
        self.assertIn("batch the approved deletes into one push", text)
        self.assertIn("--force-with-lease=refs/heads/<branch>:<sha>", text)

    def test_unmerged_or_moved_pr_tip_is_preserved_without_heuristics(self) -> None:
        text = GUIDANCE.read_text(encoding="utf-8")
        collapsed = " ".join(text.split())

        self.assertIn("closed without merge", text)
        self.assertIn("head SHA no longer matches", collapsed)
        self.assertIn("Preserve it and stop", text)
        self.assertIn("do not run content-equivalence heuristics", text)

    def test_multi_item_and_non_pr_integration_are_in_scope(self) -> None:
        text = " ".join(GUIDANCE.read_text(encoding="utf-8").split())
        for rule in ("inventory every in-scope branch, worktree and stash",
                     "Continue independent checks and approved deletions",
                     "inspect all branch-only commits with patch equivalence",
                     "Never override an authoritative unmerged PR",
                     "does not narrow the rest of an existing request",
                     "A successful cleanup gate or a partial deletion is not proof"):
            self.assertIn(rule, text)


if __name__ == "__main__":
    unittest.main()
