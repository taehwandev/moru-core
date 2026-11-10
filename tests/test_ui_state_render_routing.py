"""UI work must load the generation boundary; unrelated work must stay narrow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_request import infer_concerns_from_request
from workflow_route import resolve_docs


BOUNDARY = "common/nodes/ui-state-render-boundary.md"
COMPOSE = "platforms/compose/nodes/ui-screen-structure.md"
ANDROID = "platforms/android/skills/android-compose-ui/SKILL.md"
KMP = "platforms/kmp/skills/kmp-compose-ui/"


def route(platform, request="", paths=(), command="feature"):
    concerns = infer_concerns_from_request(request)
    return resolve_docs(
        command, platform, concerns, request_classified=True,
        inferred_concerns=concerns, request_text=request,
        surface_paths=list(paths),
    )


class UiStateRenderRoutingTests(unittest.TestCase):
    def test_android_authoring_core_is_required_for_requests_and_verified_paths(self):
        for request, paths in (
            ("Compose 프로필 화면을 만들어줘", ()),
            ("", ("app/src/main/kotlin/ui/ProfileScreen.kt",)),
            ("", ("feature/profile/src/main/kotlin/profile/ProfileContent.kt",)),
        ):
            with self.subTest(request=request, paths=paths):
                result = route("android", request, paths)
                self.assertIn(BOUNDARY, result["required_docs"])
                self.assertIn(ANDROID, result["required_docs"])
                self.assertNotIn(KMP + "SKILL.md", result["required_docs"])
                self.assertEqual([], result["missing"])

    def test_shared_and_desktop_compose_require_the_same_structure_and_generation_rules(self):
        for source_set in ("commonMain", "desktopMain", "jvmMain"):
            with self.subTest(source_set=source_set):
                result = route("kmp", paths=(
                    f"composeApp/src/{source_set}/kotlin/ui/ProfileScreen.kt",
                ))
                for doc in (BOUNDARY, COMPOSE, KMP + "SKILL.md",
                            KMP + "references/current-guidance.md"):
                    self.assertIn(doc, result["required_docs"])
                self.assertNotIn(ANDROID, result["required_docs"])
                self.assertEqual([], result["missing"])

    def test_kmp_screen_request_requires_the_shared_contract_without_known_files(self):
        result = route("kmp", "Compose Multiplatform 프로필 화면을 만들어줘")
        for doc in (BOUNDARY, COMPOSE, KMP + "references/current-guidance.md"):
            self.assertIn(doc, result["required_docs"])

    def test_stateless_content_outside_ui_packages_still_selects_compose_guidance(self):
        for source_set in ("commonMain", "desktopMain", "jvmMain"):
            with self.subTest(source_set=source_set):
                result = route("kmp", paths=(
                    f"feature/profile/src/{source_set}/kotlin/profile/ProfileContent.kt",
                ))
                for doc in (BOUNDARY, COMPOSE, KMP + "SKILL.md"):
                    self.assertIn(doc, result["required_docs"])

    def test_other_ui_frameworks_require_the_framework_neutral_contract(self):
        for platform, request, path in (
            ("web", "Create a React profile screen with loading and retry",
             "src/features/profile/ProfileScreen.tsx"),
            ("react-native", "Build a React Native profile screen",
             "packages/mobile/src/screens/ProfileScreen.tsx"),
            ("flutter", "Build a profile screen",
             "lib/features/profile/profile_screen.dart"),
            ("ios", "Build the profile screen", "App/ProfileView.swift"),
            ("application", "Build a desktop settings screen",
             "src/screens/Settings.tsx"),
        ):
            with self.subTest(platform=platform):
                result = route(platform, request, (path,))
                self.assertIn(BOUNDARY, result["required_docs"])
                self.assertNotIn(ANDROID, result["required_docs"])
                self.assertNotIn(COMPOSE, result["required_docs"])
                self.assertEqual([], result["missing"])

    def test_path_only_ui_work_loads_the_boundary_without_a_performance_audit(self):
        for platform, path in (
            ("flutter", "lib/profile/profile_screen.dart"),
            ("swift", "Sources/App/DesignSystem/ProfileComponent.swift"),
            ("react-native", "packages/mobile/src/screens/ProfileScreen.tsx"),
        ):
            with self.subTest(platform=platform):
                result = route(platform, paths=(path,))
                self.assertIn(BOUNDARY, result["required_docs"])
                self.assertNotIn(
                    "common/skills/performance-verification/references/current-guidance.md",
                    result["required_docs"],
                )

    def test_cosmetic_android_edit_keeps_detailed_structure_optional(self):
        result = route(
            "android", "Compose 설정 화면에서 저장 버튼 위치 수정해줘",
            ("app/src/main/kotlin/ui/SettingsScreen.kt",),
        )
        self.assertIn(BOUNDARY, result["required_docs"])
        self.assertIn(ANDROID, result["required_docs"])
        self.assertNotIn(COMPOSE, result["required_docs"])
        self.assertNotIn(
            "platforms/android/skills/android-compose-ui/references/screen-structure.md",
            result["required_docs"],
        )

    def test_wire_parsing_and_read_only_lookups_do_not_load_generation_rules(self):
        for platform, request, path, command in (
            ("android", "안드로이드 응답 DTO의 JSON 파싱 오류 수정해줘",
             "app/src/main/kotlin/data/UserDto.kt", "bugfix"),
            ("kmp", "Fix the response DTO JSON parsing error",
             "core/data/src/commonMain/kotlin/data/UserDto.kt", "bugfix"),
            ("web", "Fix the JSON response parser", "src/api/parseResponse.ts", "bugfix"),
            ("android", "Explain how Compose state hoisting works", "", "analysis"),
            ("kmp", "Explain how this screen is structured", "", "analysis"),
        ):
            with self.subTest(platform=platform, command=command):
                result = route(platform, request, (path,) if path else (), command)
                self.assertNotIn(BOUNDARY, result["required_docs"])
                self.assertNotIn(COMPOSE, result["required_docs"])


if __name__ == "__main__":
    unittest.main()
