import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_review_hook  # noqa: E402
from agent_review_hook import review_scope_invocation_failure_details  # noqa: E402


class SmallChangeReviewHintTest(unittest.TestCase):
    def test_small_change_cap_does_not_suggest_raising_the_limit(self):
        details = review_scope_invocation_failure_details(
            "review scope has 26 changed paths; limit is 4", "commit-range", 26, small_change_cap=True
        )
        joined = "\n".join(details)
        self.assertNotIn("--max-changed-paths 26", joined)
        self.assertIn("cannot raise it above 4", joined)
        self.assertIn("--command feature", joined)

    def test_other_routes_keep_the_raise_limit_hint(self):
        details = review_scope_invocation_failure_details(
            "review scope has 26 changed paths; limit is 25", "working-tree", 26
        )
        self.assertTrue(any("--max-changed-paths 26" in line for line in details))

    def test_review_hook_passes_the_small_change_cap_into_the_hint(self):
        changed = [f" M src/file_{index}.py" for index in range(6)]
        status = {"command": ["git", "status"], "cwd": str(ROOT), "returncode": 0,
                  "stdout": "\n".join(changed), "stderr": ""}
        payload: dict[str, object] = {}

        def git_status(_project):
            return status, changed

        def unexpected(*_args, **_kwargs):
            self.fail("substantive review checks must not run when the scope limit is exceeded")

        def finish(name, success, details, output, checks, repair_cycle, invocation_error=False):
            payload.update(details=details, invocation_error=invocation_error)
            return 0 if success else 1

        def small_change_prerequisites(args, checks, failures):
            # Mirrors the small-change branch of record_review_prerequisite_readiness.
            args.max_changed_paths = min(args.max_changed_paths, 4)
            checks["small_change_path_cap"] = True

        args = SimpleNamespace(project=ROOT, evidence=None, review_path=[], review_scope="working-tree",
                               max_changed_paths=25, output=None, repair_cycle=0)
        with (
            patch("agent_review_hook.record_review_prerequisite_readiness", side_effect=small_change_prerequisites),
            patch("agent_review_hook.record_review_failure"),
        ):
            result = agent_review_hook.review_hook(args, unexpected, git_status, unexpected, unexpected, finish)

        self.assertEqual(1, result)
        self.assertTrue(payload["invocation_error"])
        joined = "\n".join(payload["details"])
        self.assertNotIn("--max-changed-paths 6", joined)
        self.assertIn("allows at most 4 changed paths", joined)


if __name__ == "__main__":
    unittest.main()
