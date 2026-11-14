"""Cross-platform and Swift package/module separation guidance & check tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_purpose import (  # noqa: E402
    package_role_failures,
    top_level_declaration_failures,
    top_level_type_declarations,
)
from agent_structure_imports import import_candidates, imports_for_path  # noqa: E402
from agent_structure_rules import structure_rule_review  # noqa: E402
from workflow_doc_resolution import doc_size  # noqa: E402
from workflow_platform_inference import infer_platform  # noqa: E402
from workflow_route import REQUIRED_DOC_BUDGET_BYTES, resolve_docs  # noqa: E402

SHARED_NODE = "common/nodes/package-module-boundaries.md"
SWIFT_BUNDLE = "platforms/swift/skills/swift-code-structure"
SWIFT_CORE = f"{SWIFT_BUNDLE}/references/current-guidance.md"
SWIFT_BOUNDARIES = f"{SWIFT_BUNDLE}/references/package-boundaries.md"
SWIFT_LAYOUT = f"{SWIFT_BUNDLE}/references/package-layout-and-migration.md"
IOS_CORE = "platforms/ios/skills/ios-module-structure/references/current-guidance.md"


class SharedNodeAndPlatformGuidanceTests(unittest.TestCase):
    def test_shared_package_boundary_node_stays_compact_and_complete(self) -> None:
        text = (ROOT / SHARED_NODE).read_text(encoding="utf-8")
        self.assertIn("use_when:", text)
        self.assertIn("skip_when:", text)
        self.assertIn("## Boundary Promotion Ladder", text)
        self.assertIn("## Root-Package Audit And Complete Role Moves", text)
        self.assertIn("## Verification", text)
        self.assertLessEqual(doc_size(ROOT, SHARED_NODE), REQUIRED_DOC_BUDGET_BYTES)

    def test_every_platform_structure_reference_links_shared_boundary_node(self) -> None:
        docs = (
            "common/skills/code-structure-ownership/references/current-guidance.md",
            SWIFT_CORE,
            IOS_CORE,
            "platforms/android/skills/android-module-structure/references/feature-package-structure.md",
            "platforms/kmp/skills/kmp-module-structure/references/package-layout.md",
            "platforms/flutter/skills/flutter-project-structure/references/current-guidance.md",
            "platforms/web/skills/web-code-structure/references/current-guidance.md",
            "platforms/react-native/skills/react-native-app/references/current-guidance.md",
            "platforms/application/skills/application-architecture/references/current-guidance.md",
            "platforms/server/skills/server-architecture/references/current-guidance.md",
            "platforms/python/skills/python-web-service/references/current-guidance.md",
        )
        for doc in docs:
            with self.subTest(doc=doc):
                self.assertIn("package-module-boundaries.md", (ROOT / doc).read_text(encoding="utf-8"))

    def test_swift_and_ios_keep_route_value_separate_from_screen_holder(self) -> None:
        swift_boundaries = (ROOT / SWIFT_BOUNDARIES).read_text(encoding="utf-8")
        ios_guidance = (ROOT / IOS_CORE).read_text(encoding="utf-8")

        for doc_text in (swift_boundaries, ios_guidance):
            self.assertIn("FeatureProfileContract", doc_text)
            self.assertIn("ProfileRoute.swift", doc_text)
            self.assertIn("ProfileScreen.swift", doc_text)
            self.assertIn("ProfileContent.swift", doc_text)
        self.assertNotIn("ProfileRoute.swift          dependency and navigation wiring", ios_guidance)
        self.assertIn("ProfileID.swift", swift_boundaries)
        self.assertIn("ProfileEvent.swift", swift_boundaries)

        swift_core = (ROOT / SWIFT_CORE).read_text(encoding="utf-8")
        swift_layout = (ROOT / SWIFT_LAYOUT).read_text(encoding="utf-8")
        self.assertIn("Swift 5.9+, SE-0386", swift_core)
        self.assertIn("Swift 6.0+, SE-0409", swift_core)
        self.assertIn("#externalMacro", swift_layout)

    def test_swift_bundle_documents_stay_under_required_doc_budget(self) -> None:
        for path in (SWIFT_CORE, SWIFT_BOUNDARIES, SWIFT_LAYOUT, IOS_CORE):
            with self.subTest(path=path):
                self.assertLessEqual(doc_size(ROOT, path), REQUIRED_DOC_BUDGET_BYTES)


class PackageSeparationRoutingTests(unittest.TestCase):
    def test_swift_and_ios_module_concerns_deliver_boundary_and_layout_docs(self) -> None:
        for platform in ("swift", "ios"):
            for concern in ("module", "structure"):
                with self.subTest(platform=platform, concern=concern):
                    required = resolve_docs(
                        "feature",
                        platform,
                        [concern],
                        request_classified=True,
                        request_text=f"{platform} {concern} separation",
                    )["required_docs"]
                    self.assertIn(SHARED_NODE, required)
                    self.assertIn(SWIFT_BOUNDARIES, required)
                    self.assertIn(SWIFT_LAYOUT, required)

    def test_korean_swift_package_split_request_routes_without_explicit_concern(self) -> None:
        required = resolve_docs(
            "feature",
            "swift",
            [],
            request_classified=True,
            request_text="스위프트 앱에서 로컬 패키지 분리와 타겟 분리를 적용해줘",
        )["required_docs"]
        self.assertIn(SHARED_NODE, required)
        self.assertIn(SWIFT_BOUNDARIES, required)
        self.assertIn(SWIFT_LAYOUT, required)

    def test_package_swift_surface_path_promotes_swift_package_boundaries(self) -> None:
        required = resolve_docs(
            "feature",
            "ios",
            [],
            request_classified=True,
            request_text="Add profile target",
            surface_paths=["Packages/AppModules/Package.swift"],
        )["required_docs"]
        self.assertIn(SWIFT_BOUNDARIES, required)
        self.assertIn(SWIFT_LAYOUT, required)

    def test_all_platforms_route_module_and_structure_concerns_with_shared_node(self) -> None:
        expected_platform_docs = {
            "android": "platforms/android/skills/android-module-structure/references/current-guidance.md",
            "kmp": "platforms/kmp/skills/kmp-module-structure/references/package-layout.md",
            "flutter": "platforms/flutter/skills/flutter-project-structure/references/current-guidance.md",
            "swift": SWIFT_CORE,
            "ios": IOS_CORE,
            "web": "platforms/web/skills/web-code-structure/references/current-guidance.md",
            "react-native": "platforms/react-native/skills/react-native-app/references/current-guidance.md",
            "application": "platforms/application/skills/application-architecture/references/current-guidance.md",
            "server": "platforms/server/skills/server-architecture/references/current-guidance.md",
            "python": "platforms/python/skills/python-web-service/references/current-guidance.md",
        }
        for platform, expected_doc in expected_platform_docs.items():
            for concern in ("structure", "module"):
                with self.subTest(platform=platform, concern=concern):
                    required = resolve_docs(
                        "feature",
                        platform,
                        [concern],
                        request_classified=True,
                        request_text=f"{platform} {concern} boundary check",
                    )["required_docs"]
                    self.assertIn(SHARED_NODE, required)
                    self.assertIn(expected_doc, required)

    def test_korean_package_split_intent_reaches_android_and_other_platforms(self) -> None:
        android_req = resolve_docs(
            "refactor",
            "android",
            [],
            request_classified=True,
            request_text="안드로이드 기능 패키지 분리 정리해줘",
        )["required_docs"]
        self.assertIn(SHARED_NODE, android_req)
        self.assertIn(
            "platforms/android/skills/android-module-structure/references/module-boundaries.md",
            android_req,
        )

        expected_by_platform = {
            "ios": IOS_CORE,
            "kmp": "platforms/kmp/skills/kmp-module-structure/references/package-layout.md",
            "flutter": "platforms/flutter/skills/flutter-project-structure/references/current-guidance.md",
            "web": "platforms/web/skills/web-code-structure/references/current-guidance.md",
            "react-native": "platforms/react-native/skills/react-native-app/references/current-guidance.md",
            "application": "platforms/application/skills/application-architecture/references/current-guidance.md",
            "python": "platforms/python/skills/python-web-service/references/current-guidance.md",
            "server": "platforms/server/skills/server-architecture/references/current-guidance.md",
        }
        for platform, expected_doc in expected_by_platform.items():
            with self.subTest(platform=platform):
                req = resolve_docs(
                    "refactor",
                    platform,
                    [],
                    request_classified=True,
                    request_text=f"{platform} 프로젝트 패키지 분리 리팩터링",
                )["required_docs"]
                self.assertIn(SHARED_NODE, req)
                self.assertIn(expected_doc, req)
                if platform == "application":
                    self.assertFalse(any(doc.startswith("platforms/swift/") for doc in req))

        macos_app_req = resolve_docs(
            "refactor",
            "application",
            [],
            request_classified=True,
            request_text="macOS 데스크톱 앱에서 Package.swift 로컬 패키지 분리",
        )["required_docs"]
        self.assertIn("platforms/application/skills/application-architecture/references/current-guidance.md", macos_app_req)
        self.assertIn(SWIFT_BOUNDARIES, macos_app_req)

    def test_unflagged_framework_and_korean_requests_route_package_boundaries(self) -> None:
        cases = (
            ("스위프트 앱에서 로컬 패키지 분리해줘", SWIFT_BOUNDARIES),
            ("iOS 타겟 분리랑 위젯 타겟 공유 패키지 정리해줘", IOS_CORE),
            ("WidgetKit 위젯 타겟 분리해줘", IOS_CORE),
            ("Next.js 모노레포에서 feature 폴더랑 패키지 분리해줘", "platforms/web/skills/web-code-structure/references/current-guidance.md"),
            ("React Native 앱에서 기능별 패키지 분리해줘", "platforms/react-native/skills/react-native-app/references/current-guidance.md"),
            ("FastAPI 서비스에서 도메인별로 패키지 분리해줘", "platforms/python/skills/python-web-service/references/current-guidance.md"),
            ("백엔드 서버에서 도메인 모듈 경계랑 패키지 분리해줘", "platforms/server/skills/server-architecture/references/current-guidance.md"),
            ("Tauri 데스크톱 앱에서 패키지 분리해줘", "platforms/application/skills/application-architecture/references/current-guidance.md"),
            ("패키지 분리와 모듈 경계 정리해줘", "common/skills/code-structure-ownership/references/current-guidance.md"),
        )
        for request_text, expected_doc in cases:
            with self.subTest(request=request_text):
                inferred = infer_platform(request_text)
                required = resolve_docs(
                    "refactor",
                    inferred,
                    [],
                    request_classified=True,
                    request_text=request_text,
                )["required_docs"]
                self.assertIn(SHARED_NODE, required)
                self.assertIn(expected_doc, required)

    def test_unrelated_or_excluded_requests_do_not_load_boundary_node(self) -> None:
        for platform, request_text in (
            ("swift", "로그인 버튼 텍스트 오타 수정해줘"),
            ("web", "패키지 분리는 건드리지 말고 버튼 색상만 바꿔줘"),
        ):
            with self.subTest(platform=platform, request=request_text):
                required = resolve_docs(
                    "bugfix",
                    platform,
                    [],
                    request_classified=True,
                    request_text=request_text,
                )["required_docs"]
                self.assertNotIn(SHARED_NODE, required)


class SwiftReviewPurposeAndImportChecksTests(unittest.TestCase):
    def test_swift_attribute_prefixed_types_count_as_top_level_owners(self) -> None:
        path = Path("Sources/FeatureProfile/ProfileFeature.swift")
        lines = [
            "@MainActor final class ProfileViewModel {",
            "}",
            "@Observable final class AccountStore {",
            "}",
        ]
        declarations = top_level_type_declarations(path, lines)
        failures = top_level_declaration_failures(path, declarations)

        self.assertEqual(2, len(declarations))
        self.assertTrue(any("declares 2 public/exported top-level owners" in item for item in failures))

    def test_swift_fileprivate_and_package_modifiers_classify_visibility_and_roles(self) -> None:
        path = Path("Sources/FeatureProfile/ProfileScreen.swift")
        clean_lines = [
            "@MainActor public struct ProfileScreen {",
            "}",
            "package struct ProfileLayoutMetrics {",
            "}",
            "fileprivate struct ProfilePreviewSeed {",
            "}",
        ]
        clean_decls = top_level_type_declarations(path, clean_lines)
        self.assertEqual([], top_level_declaration_failures(path, clean_decls))

        mixed_lines = [
            "package struct ProfileScreen {",
            "}",
            "package final class ProfileRepositoryImpl {",
            "}",
        ]
        mixed_decls = top_level_type_declarations(path, mixed_lines)
        mixed_failures = top_level_declaration_failures(path, mixed_decls)
        self.assertTrue(any("mixes top-level owner roles" in item for item in mixed_failures))

        open_lines = [
            "open class BaseCoordinator {",
            "}",
            "public struct ProfileRoute {",
            "}",
        ]
        open_decls = top_level_type_declarations(path, open_lines)
        open_failures = top_level_declaration_failures(path, open_decls)
        self.assertTrue(any("declares 2 public/exported top-level owners" in item for item in open_failures))

        body_and_param_lines = [
            "struct FirstOwner { fileprivate let secret: Int }",
            "struct SecondOwner { private let token: String }",
            '@available(*, deprecated, message: "use public API") private struct LegacyHelper {',
            "}",
            "private func configure(package: String, open: Bool) {",
            "}",
        ]
        body_decls = top_level_type_declarations(path, body_and_param_lines)
        self.assertEqual(["FirstOwner", "SecondOwner", "LegacyHelper"], [d["name"] for d in body_decls])
        self.assertFalse(body_decls[0]["private"])
        self.assertTrue(body_decls[2]["private"])
        self.assertFalse(body_decls[2]["exported"])
        body_failures = top_level_declaration_failures(path, body_decls)
        self.assertTrue(any("declares 2 public/exported top-level owners" in item for item in body_failures))

    def test_swift_sources_root_strips_container_folder_but_catches_grab_bag_targets(self) -> None:
        safe_path = Path("Packages/Shared/Sources/CoreAuth/TokenStore.swift")
        bad_target = Path("Packages/Shared/Sources/Common/StringHelper.swift")
        bad_subfolder = Path("Sources/FeatureProfile/Utils/DateHelper.swift")

        self.assertEqual(
            [],
            package_role_failures(
                Path("."),
                [safe_path],
                {str(safe_path): {"status": "A"}},
                lambda _root, _p: True,
                lambda _p: False,
            ),
        )
        for bad_path in (bad_target, bad_subfolder):
            with self.subTest(path=str(bad_path)):
                failures = package_role_failures(
                    Path("."),
                    [bad_path],
                    {str(bad_path): {"status": "A"}},
                    lambda _root, _p: True,
                    lambda _p: False,
                )
                self.assertEqual(1, len(failures))
                self.assertIn("grab-bag package segment", failures[0])

    def test_swift_and_dart_imports_parse_access_attributes_and_kind_qualifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            swift_file = project / "Sources" / "FeatureProfileContract" / "ProfileRoute.swift"
            swift_file.parent.mkdir(parents=True)
            swift_file.write_text(
                "@preconcurrency public import Foundation\n"
                "package import CoreNavigation\n"
                "@testable import FeatureProfileTestSupport\n"
                "import struct FeatureProfile.InternalRow\n"
                "private import CoreAnalytics\n",
                encoding="utf-8",
            )
            extracted = imports_for_path(swift_file)
            self.assertEqual(
                [
                    "Foundation",
                    "CoreNavigation",
                    "FeatureProfileTestSupport",
                    "FeatureProfile.InternalRow",
                    "CoreAnalytics",
                ],
                extracted,
            )

            ts_file = project / "src" / "ButtonView.tsx"
            ts_file.parent.mkdir(parents=True)
            ts_file.write_text("import Button from '../ui/button';\n", encoding="utf-8")
            self.assertEqual(["../ui/button"], imports_for_path(ts_file))

            self.assertIn(
                "feature_profile/src/internal.dart",
                import_candidates("package:feature_profile/src/internal.dart", Path("lib/main.dart")),
            )
            self.assertIn(
                "lib/src/impl.dart",
                import_candidates("src/impl.dart", Path("lib/api.dart")),
            )
            self.assertIn(
                "FeatureProfile",
                import_candidates("FeatureProfile.InternalRow", Path("Sources/App/Main.swift")),
            )

            (project / ".agents").mkdir()
            (project / ".agents" / "structure-rules.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "name": "contract_never_imports_impl",
                                "paths": ["Sources/*Contract/**"],
                                "forbidden_imports": ["FeatureProfile"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rel_swift = Path("Sources/FeatureProfileContract/ProfileRoute.swift")
            review = structure_rule_review(
                project,
                [rel_swift],
                {str(rel_swift): {"status": "A"}},
                lambda root, path: (root / path).exists(),
                lambda _path: False,
            )
            self.assertEqual(1, len(review["failures"]))
            self.assertIn("contract_never_imports_impl", review["failures"][0])


if __name__ == "__main__":
    unittest.main()
