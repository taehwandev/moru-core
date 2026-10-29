"""The compact entrypoint retains safety and reaches conditional mechanics."""

from pathlib import Path
import unittest

from workflow_route import resolve_docs

ROOT = Path(__file__).resolve().parents[1]
REFS = "common/skills/agent-operating-skill/references/"


class AgentEntrypointDietTests(unittest.TestCase):
    def test_entrypoint_budget_and_authority_boundary(self):
        entry = (ROOT / "AGENTS.md").read_bytes()
        self.assertLessEqual(len(entry), 15000)
        text = " ".join(entry.decode().split())
        for rule in ("runtime system/developer instructions", "separate matching approval",
                     "minimum effect `read` is non-mutating", "finish rejects drift",
                     "`retrospective_repair_verify_resume`", "Never bypass VibeGuard",
                     "allowed imports", "forbidden imports", "matching authority/checks",
                     "relay a finish `For the user:` context nudge"):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)
        self.assertIn("<!-- vibeguard:start version=1 -->", text)
        self.assertIn("<!-- vibeguard:end -->", text)

    def test_moved_contracts_are_reachable_and_remain_on_demand(self):
        entry = (ROOT / "AGENTS.md").read_text()
        contracts = {
            "entrypoint-lifecycle.md": ("--intent-envelope", "at most four hops",
                                       "source docs", "deployment count", "not_found"),
            "request-continuation.md": ("--reuse-inputs", "--continuation-scope",
                                        "input_paths", "unknown lifecycle version",
                                        "no action is not evidence"),
            "document-memory.md": ("requires_docs", "CodeGraph", "~/.claude/projects/*/memory",
                                   "Never capture secrets", "--analysis-question", "work-cards close"),
            "collaboration-review.md": ("<= 4", "~250K", "~6", "context nudge",
                                        "300 added lines", "plain lowercase functions"),
        }
        for name, rules in contracts.items():
            path = REFS + name
            with self.subTest(path=path):
                self.assertIn(path, entry)
                detail = " ".join((ROOT / path).read_text().split())
                for rule in rules:
                    self.assertIn(rule, detail)
        for command in ("build", "bugfix", "docs", "commit", "analysis"):
            route = resolve_docs(command, None, [])
            self.assertTrue(set(REFS + name for name in contracts).isdisjoint(route["required_docs"]))

    def test_external_goal_guidance_does_not_claim_completion_or_override(self):
        detail = " ".join((ROOT / (REFS + "runtime-collaboration.md")).read_text().split())
        for rule in ("outside this runtime's control", "state the dependency once",
                     "recommend clearing the goal, and stop", "Do not repeat",
                     "or claim the goal succeeded", "cannot clear or override"):
            self.assertIn(rule, detail)


if __name__ == "__main__":
    unittest.main()
