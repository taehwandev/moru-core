"""Business artifact work loads its skill before writing, without global bloat."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_required_doc_delivery import delivery_text
from workflow_request import classify_request
from workflow_route import resolve_docs

HANDOFF = "common/skills/product-spec-to-implementation/references/artifact-handoff.md"
SKILLS = ("product-planning", "marketing-planning", "sales-proposal")
REQUESTS = (
    ("product-planning", "작은 팀의 예약 관리 서비스 아이디어를 제품 제안서로 정리해줘"),
    ("product-planning", "Draft a product proposal from this rough scheduling idea."),
    ("marketing-planning", "프로토타입의 타깃 고객과 메시지를 담은 마케팅 기획서를 작성해줘"),
    ("marketing-planning", "Prepare a campaign brief with an audience and message hypothesis."),
    ("sales-proposal", "고객 요구를 바탕으로 내부 검토용 영업 제안서를 작성해줘"),
    ("sales-proposal", "Draft an internal sales proposal for this prospect."),
)


def skill_docs(skill):
    base = f"product-patterns/skills/{skill}"
    return {f"{base}/SKILL.md", f"{base}/references/current-guidance.md"}


class BusinessSkillRoutingTests(unittest.TestCase):
    def test_natural_artifact_requests_require_only_the_matching_business_skill(self):
        for skill, request in REQUESTS:
            with self.subTest(request=request):
                route = resolve_docs("docs", None, [], request_classified=True,
                                     request_text=request)
                required = set(route["required_docs"])
                self.assertFalse(route["missing"])
                self.assertTrue(skill_docs(skill) <= required)
                self.assertIn(HANDOFF, required)
                for other in set(SKILLS) - {skill}:
                    self.assertFalse(skill_docs(other) & required)

    def test_named_stage_is_required_without_phrase_matching(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                route = resolve_docs("planning", None, [skill],
                                     request_classified=True,
                                     request_text="Continue the established artifact stage.")
                self.assertTrue(skill_docs(skill) <= set(route["required_docs"]))
                self.assertIn(HANDOFF, route["required_docs"])

    def test_prd_handoff_keeps_the_existing_prd_owner(self):
        route = resolve_docs("prd", None, ["product-planning"], request_classified=True,
                             request_text="Prepare the product requirements from the brief.")
        required = route["required_docs"]
        self.assertTrue(any("workflows/skills/prd-creation/" in d for d in required))
        self.assertTrue(skill_docs("product-planning") <= set(required))

    def test_existing_cro_work_does_not_require_campaign_planning(self):
        route = resolve_docs("feature", "web", ["cro"], request_classified=True,
                             request_text="Fix allocation for the existing funnel.")
        self.assertTrue(any("growth-conversion-optimization/" in d
                            for d in route["required_docs"]))
        self.assertFalse(any(skill in d for d in route["required_docs"] for skill in SKILLS))

    def test_unrelated_code_and_lookup_work_does_not_load_business_skills(self):
        cases = (
            ("bugfix", "Fix JSON parsing in the sales dashboard."),
            ("feature", "Add a button beside the marketing plan link."),
            ("docs", "마케팅 버튼의 오타를 고쳐줘"),
            ("analysis", "Where is the sales proposal stored?"),
            ("analysis", "제품 제안서를 어떻게 작성하는지 설명해줘"),
            ("commit", "Commit the marketing planning skill."),
        )
        for command, request in cases:
            with self.subTest(command=command, request=request):
                route = resolve_docs(command, None, [], request_classified=True,
                                     request_text=request)
                self.assertFalse(any(skill in d for d in route["required_docs"]
                                     for skill in SKILLS))

    def test_natural_language_selection_does_not_grant_work_authority(self):
        for _, request in REQUESTS:
            with self.subTest(request=request):
                self.assertNotEqual("work", classify_request(request)["response_mode"])

    def test_cli_accepts_named_business_stages(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                result = subprocess.run(
                    [sys.executable, "-B", str(ROOT / "scripts/workflow.py"),
                     "route", "docs", "--concern", skill, "--advisory", "--format", "json"],
                    cwd=ROOT, capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                route = json.loads(result.stdout)
                self.assertTrue(skill_docs(skill) <= set(route["required_docs"]))
                self.assertFalse(route["missing"])

    def test_first_edit_delivers_actual_unread_business_guidance_once(self):
        for skill, request in REQUESTS[::2]:
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as directory:
                project = Path(directory).resolve()
                run = project / ".moru/runs" / ("a" * 32)
                run.mkdir(parents=True)
                (project / ".moru/run-registry.json").write_text("{}")
                route = resolve_docs("docs", None, [skill], request_classified=True,
                                     request_text=request)
                evidence = run / "preflight.json"
                evidence.write_text(json.dumps({"project": str(project), "rules": str(ROOT),
                    "timestamp": "2026-10-26T00:00:00+00:00", "route": route}))
                transcript = project / "synthetic-transcript.jsonl"
                transcript.write_text("")
                payload = {"cwd": str(project), "transcript_path": str(transcript),
                           "tool_input": {"file_path": str(project / "proposal.md")}}
                first = delivery_text(payload, lambda root: evidence)
                for doc in skill_docs(skill) | {HANDOFF}:
                    self.assertIn(f"=== {doc} ===", first)
                    body = (ROOT / doc).read_text().split("---", 2)[-1].strip()
                    self.assertIn(body, first)
                self.assertEqual("", delivery_text(payload, lambda root: evidence))


if __name__ == "__main__":
    unittest.main()
