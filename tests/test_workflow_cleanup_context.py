"""Git state context stays scoped without weakening application/risk guidance."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_route import resolve_docs

OPERATING = "common/skills/agent-operating-skill/SKILL.md"
CLEANUP = "common/skills/branch-cleanup/references/current-guidance.md"


class CleanupContextRoutingTests(unittest.TestCase):
    def test_git_state_cleanup_keeps_the_fixed_deletion_contract(self):
        for concerns in (["state"], ["branch", "worktree", "state"]):
            with (
                self.subTest(concerns=concerns),
                patch("workflow_route.infer_surface_docs", return_value=([], [])) as surfaces,
                patch("workflow_route.search_docs_outcome") as search,
                patch("workflow_route.expand_required_doc_matches") as graph,
            ):
                route = resolve_docs(
                    "cleanup", None, concerns, request_classified=True,
                    request_text="main에 머지된것 기준 정리해줘 워크트리/브랜치/스테시",
                )
                self.assertEqual([OPERATING, CLEANUP], route["required_docs"])
                self.assertEqual("fixed-route", route["document_search"]["backend"])
                surfaces.assert_not_called()
                search.assert_not_called()
                graph.assert_not_called()

    def test_application_state_still_loads_its_own_guidance(self):
        route = resolve_docs("task", None, ["state"], request_classified=True)
        self.assertIn("common/skills/state-modeling/references/current-guidance.md",
                      route["required_docs"])

    def test_cleanup_with_security_still_loads_risk_guidance(self):
        route = resolve_docs("cleanup", None, ["state", "security"], request_classified=True)
        self.assertEqual("deterministic-route", route["document_search"]["backend"])
        self.assertTrue(any("security" in doc for doc in route["required_docs"]))
