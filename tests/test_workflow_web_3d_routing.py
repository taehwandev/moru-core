"""Require the 3D card for real work without widening unrelated startup reads."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_route import resolve_docs


SKILL = "platforms/web/skills/web-3d-interaction/SKILL.md"
FIRST_REQUEST = (
    "Build an interactive 3D webpage where users assemble a small spaceship "
    "from a hull, cockpit, wings, and engine, then launch the assembled ship "
    "and watch it fly. Launch should become available once assembly is complete. "
    "Show the ship lifting off from its assembly pad and flying away. Let users "
    "inspect the ship from different angles, zoom in and out, and reset the view. "
    "Make the assembly-to-flight flow clear and comfortable on desktop and mobile."
)


class Web3DReadingTests(unittest.TestCase):
    def route(self, request, command="build", platform=None, **kwargs):
        return resolve_docs(command, platform, [], request_classified=True,
                            request_text=request, **kwargs)

    def test_original_first_prompt_requires_skill_without_engine_or_platform_flag(self):
        route = self.route(FIRST_REQUEST)
        self.assertIn(SKILL, route["required_docs"])
        self.assertEqual(1, route["required_docs"].count(SKILL))
        self.assertIn("common/skills/ui-visual-verification/SKILL.md", route["required_docs"])

    def test_engine_and_korean_requests_require_card(self):
        for request in (
            "Create a Three.js model viewer with material selection and orbit camera",
            "Fix WebGL camera tracking during the animation",
            "웹에서 3D 로봇 모델을 조립하고 움직이게 만들어줘",
            "3차원 모델 뷰어를 브라우저에서 만들어줘",
        ):
            with self.subTest(request=request):
                self.assertIn(SKILL, self.route(request)["required_docs"])

    def test_verified_web_scope_does_not_require_engine_name(self):
        self.assertIn(SKILL, self.route("Create a 3D model configurator", platform="web")["required_docs"])

    def test_dotted_subject_exclusion_keeps_independent_positive_change(self):
        request = "Fix the Three.js orbit camera without changing the Three.js model geometry"
        self.assertIn(SKILL, self.route(request)["required_docs"])

    def test_unrelated_dependency_name_does_not_select_scene_skill(self):
        self.assertNotIn(SKILL, self.route("Update the Three.js dependency version only")["required_docs"])

    def test_unrelated_negative_and_prose_requests_do_not_require_card(self):
        cases = (
            ("Build an account settings form", "build", "web"),
            ("Animate a card with CSS transform: rotateY and perspective", "build", "web"),
            ("Build a CSS 3D transform card carousel", "build", "web"),
            ("Explain how the Three.js camera works", "analysis", "web"),
            ("Write a blog post about Three.js model viewers", "docs", None),
            ("Create a 3D model in Blender", "build", None),
            ("Do not change the Three.js scene; fix the account form", "build", "web"),
        )
        for request, command, platform in cases:
            with self.subTest(request=request):
                self.assertNotIn(SKILL, self.route(request, command, platform)["required_docs"])

    def test_unrelated_verified_owner_cannot_make_lookup_an_implementation_read(self):
        route = self.route("What does this Three.js camera do?", "analysis", "web",
                           surface_paths=["scripts/workflow_route.py"])
        self.assertNotIn(SKILL, route["required_docs"])

    def test_quality_companion_does_not_force_a_quiet_aesthetic(self):
        route = self.route(FIRST_REQUEST)
        self.assertFalse(route["missing"])
        self.assertNotIn("common/skills/minimal-visual-design/SKILL.md", route["required_docs"])


if __name__ == "__main__":
    unittest.main()
