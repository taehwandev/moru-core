"""Require the 3D card for real work without widening unrelated startup reads."""

import sys
import tempfile
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

    def test_small_change_route_still_requires_3d_and_structure_cards(self):
        for platform in (None, "web"):
            with self.subTest(platform=platform):
                route = self.route(FIRST_REQUEST, command="small-change", platform=platform)
                self.assertIn(SKILL, route["required_docs"])
                self.assertIn("platforms/web/skills/web-code-structure/references/current-guidance.md", route["required_docs"])

    def test_engine_and_korean_requests_require_card(self):
        for request in (
            "Create a Three.js model viewer with material selection and orbit camera",
            "Fix WebGL camera tracking during the animation",
            "웹에서 3D 로봇 모델을 조립하고 움직이게 만들어줘",
            "3차원 모델 뷰어를 브라우저에서 만들어줘",
        ):
            with self.subTest(request=request):
                self.assertIn(SKILL, self.route(request)["required_docs"])

    def test_paraphrased_request_with_words_between_3d_and_webpage_requires_card(self):
        for command in ("small-change", "build"):
            with self.subTest(command=command):
                route = self.route("Create a polished interactive 3D landing-pad departure webpage", command=command)
                self.assertIn(SKILL, route["required_docs"])

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
            ("Build a 3D printing shop website", "build", "web"),
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


STRUCTURE = "platforms/web/skills/web-code-structure/references/current-guidance.md"
FOLLOW_UPS = (
    "Add a pause/resume control and a way to replay the launch from the beginning. Keep everything that already works.",
    "On a short landscape phone screen the bottom controls are cut off. Fix this without breaking anything.",
    "After zooming in and then rotating the view, the rocket is no longer in the center of the screen.",
)


class Web3DProjectSignalTests(unittest.TestCase):
    def project(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def route(self, request, root, command="small-change", platform=None):
        return resolve_docs(command, platform, [], request_classified=True,
                            request_text=request, project_root=root)

    def test_follow_up_without_3d_words_requires_cards_for_three_module_project(self):
        root = self.project({"index.html": "<canvas></canvas>",
                             "src/main.js": "import * as THREE from 'three';\nnew THREE.Scene();"})
        for request in FOLLOW_UPS:
            for command in ("small-change", "feature", "bugfix"):
                with self.subTest(request=request[:30], command=command):
                    route = self.route(request, root, command)
                    self.assertIn(SKILL, route["required_docs"])
                    self.assertIn(STRUCTURE, route["required_docs"])

    def test_importmap_and_cdn_project_is_detected(self):
        root = self.project({"index.html": '<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js"}}</script>'})
        self.assertIn(SKILL, self.route(FOLLOW_UPS[0], root)["required_docs"])

    def test_package_json_dependency_is_detected(self):
        root = self.project({"package.json": '{"dependencies": {"three": "^0.170.0"}}'})
        self.assertIn(SKILL, self.route(FOLLOW_UPS[1], root)["required_docs"])

    def test_plain_project_and_dependency_directories_do_not_trigger(self):
        root = self.project({"index.html": "<h1>Hello</h1>", "src/main.js": "const three = 3;",
                             "node_modules/three/index.js": "import * as THREE from 'three';"})
        for request in FOLLOW_UPS:
            with self.subTest(request=request[:30]):
                self.assertNotIn(SKILL, self.route(request, root)["required_docs"])

    def test_dependency_only_request_in_three_project_does_not_trigger(self):
        root = self.project({"src/main.js": "import * as THREE from 'three';"})
        route = self.route("Bump the dependency version in package.json", root)
        self.assertNotIn(SKILL, route["required_docs"])

    def test_read_only_commands_and_missing_project_do_not_trigger(self):
        root = self.project({"src/main.js": "import * as THREE from 'three';"})
        self.assertNotIn(SKILL, self.route("What does this camera code do?", root, "analysis")["required_docs"])
        self.assertNotIn(SKILL, resolve_docs("small-change", None, [], request_classified=True,
                                             request_text=FOLLOW_UPS[0])["required_docs"])


if __name__ == "__main__":
    unittest.main()
