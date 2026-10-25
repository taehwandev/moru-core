"""Adaptive mobile guidance must be reachable without broad UI over-selection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_route import resolve_docs


SKILL = "common/skills/foldable-adaptive-layout/SKILL.md"


class FoldableLayoutRoutingTests(unittest.TestCase):
    def route(self, platform, request, concerns=(), command="feature"):
        return resolve_docs(
            command, platform, list(concerns), request_classified=True,
            request_text=request,
        )

    def test_normal_mobile_requests_require_the_entrypoint(self):
        cases = [
            ("android", "Fix Galaxy Z Fold list-detail layout across fold/unfold"),
            ("android", "Pixel Fold tabletop controls overlap the hinge"),
            ("android", "Compose 대화면 레이아웃을 구현해줘"),
            ("kmp", "Implement adaptive layout for Compose Multiplatform"),
            ("kmp", "KMP 폴더블 화면의 상태를 접기/펴기 전환에도 유지해줘"),
            ("ios", "Adapt SwiftUI navigation for iPhone Duo"),
            ("ios", "UIKit 듀오 화면에서 세로 툴바 인셋을 수정해줘"),
            ("swift", "Implement large-screen layout with NavigationSplitView"),
            ("ios", "Make the layout respond to size class changes"),
        ]
        for platform, request in cases:
            with self.subTest(platform=platform, request=request):
                route = self.route(platform, request)
                self.assertIn(SKILL, route["required_docs"])
                # Platform-specific details remain conditional reads.
                self.assertFalse(any(
                    doc.startswith("common/skills/foldable-adaptive-layout/references/")
                    for doc in route["required_docs"]
                ))

    def test_verified_concerns_work_without_keyword_inference(self):
        for concern in ("foldable", "dual-posture", "adaptive", "large-screen"):
            for platform in ("android", "kmp", "ios"):
                with self.subTest(concern=concern, platform=platform):
                    route = self.route(platform, "Adjust the existing pane owner", [concern])
                    self.assertIn(SKILL, route["required_docs"])

    def test_verified_layout_owner_paths_require_the_skill(self):
        for platform, path in (
            ("android", "app/src/main/ui/FoldableScreen.kt"),
            ("kmp", "shared/src/commonMain/kotlin/ui/AdaptiveLayout.kt"),
            ("ios", "Sources/UI/HingeLayout.swift"),
        ):
            with self.subTest(platform=platform, path=path):
                route = resolve_docs(
                    "bugfix", platform, [], request_classified=True,
                    request_text="Fix pane spacing", surface_paths=[path],
                )
                self.assertIn(SKILL, route["required_docs"])

    def test_verification_and_review_routes_reach_the_skill(self):
        for command in ("test", "review", "bugfix", "refactor"):
            with self.subTest(command=command):
                self.assertIn(SKILL, self.route(
                    "ios", "Check iPhone Duo fold/unfold state continuity", command=command,
                )["required_docs"])

    def test_unrelated_ui_and_nonmobile_requests_do_not_select_it(self):
        cases = [
            ("android", "Change the Compose button color"),
            ("android", "Update adaptive icons"),
            ("ios", "Fix a SwiftUI List row label"),
            ("kmp", "Resize the desktop window"),
            ("web", "Implement adaptive layout for a large-screen dashboard"),
            ("server", "Fold duplicate rows in the response"),
            ("ios", "Fix only the parser without touching iPhone Duo layout"),
        ]
        for platform, request in cases:
            with self.subTest(platform=platform, request=request):
                route = self.route(platform, request)
                self.assertNotIn(SKILL, route["required_docs"] + route["reference_docs"])


if __name__ == "__main__":
    unittest.main()
