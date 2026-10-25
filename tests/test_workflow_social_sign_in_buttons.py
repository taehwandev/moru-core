"""Sign-in UI must reach branding rules without burdening backend-only auth."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_route import resolve_docs


SKILL = "common/skills/social-sign-in-buttons/SKILL.md"
AUTH = "product-patterns/skills/auth-rbac-implementation/SKILL.md"


class SocialSignInButtonRoutingTests(unittest.TestCase):
    def route(self, platform, request, concerns=(), command="feature", paths=()):
        return resolve_docs(
            command, platform, list(concerns), request_classified=True,
            request_text=request, surface_paths=list(paths),
        )

    def test_auth_ui_requests_require_the_entrypoint_only(self):
        cases = [
            (None, "SNS 로그인 버튼 가이드도 공통화해서 스킬로 강화해줘"),
            ("ios", "Implement Sign in with Apple using SwiftUI"),
            ("swift", "Fix ASAuthorizationAppleIDButton contrast in UIKit"),
            ("ios", "Replace the outdated GoogleSignInButton style"),
            ("android", "Fix Google login button branding in Compose"),
            ("kmp", "KMP 소셜 로그인 화면을 구현해줘"),
            ("web", "Build an authentication screen with provider options"),
            ("web", "Fix brand assets for the sign-in form"),
            ("web", "네이버 로그인 버튼의 로고를 고쳐줘"),
            ("android", "카카오 로그인 버튼 크기를 맞춰줘"),
            ("web", "Add a GitHub sign-in button"),
        ]
        for platform, request in cases:
            with self.subTest(platform=platform, request=request):
                route = self.route(platform, request)
                self.assertIn(SKILL, route["required_docs"])
                self.assertFalse(any(
                    doc.startswith("common/skills/social-sign-in-buttons/references/")
                    for doc in route["required_docs"]
                ))

    def test_verified_concern_aliases_are_reachable(self):
        for concern in ("sign-in", "login", "social-login", "brand-assets"):
            for platform in ("ios", "android", "kmp", "web"):
                with self.subTest(concern=concern, platform=platform):
                    route = self.route(platform, "Adjust the existing owner", [concern])
                    self.assertIn(SKILL, route["required_docs"])

    def test_auth_concern_keeps_enforcement_and_conditional_ui_guidance(self):
        route = self.route("server", "Reject revoked sessions", ["auth"])
        self.assertIn(AUTH, route["required_docs"])
        self.assertIn(SKILL, route["reference_docs"])
        self.assertNotIn(SKILL, route["required_docs"])
        route = self.route("ios", "Fix the login screen", ["auth"])
        self.assertIn(AUTH, route["required_docs"])
        self.assertIn(SKILL, route["required_docs"])

    def test_verified_button_screen_and_artwork_owners(self):
        cases = [
            ("ios", "Sources/UI/AppleSignInButton.swift"),
            ("android", "app/ui/GoogleContinueButton.kt"),
            ("kmp", "shared/src/commonMain/kotlin/ui/LoginScreen.kt"),
            ("web", "src/components/GoogleSignInButton.tsx"),
            ("web", "src/app/login/page.tsx"),
            ("web", "src/ui/auth/ProviderOptions.vue"),
            ("web", "public/assets/GoogleG.svg"),
        ]
        for platform, path in cases:
            with self.subTest(platform=platform, path=path):
                route = self.route(platform, "Adjust existing spacing", paths=[path])
                self.assertIn(SKILL, route["required_docs"])

    def test_review_test_and_repair_routes_require_the_contract(self):
        for command in ("review", "test", "bugfix", "refactor"):
            with self.subTest(command=command):
                route = self.route("web", "Check the sign-in button", command=command)
                self.assertIn(SKILL, route["required_docs"])

    def test_unrelated_ui_backend_and_excluded_subjects_do_not_require_it(self):
        cases = [
            ("android", "Change the Compose save button color", ()),
            ("ios", "Update a SwiftUI List row", ()),
            ("web", "Replace the homepage brand logo", ()),
            ("server", "Fix OAuth token validation", ("src/auth/TokenValidator.kt",)),
            ("server", "Rotate the session signing key", ()),
            ("ios", "Adjust the payment control", ("Sources/UI/ApplePayButton.swift",)),
            ("android", "Adjust the map control", ("app/ui/GoogleMapsButton.kt",)),
            ("web", "Fix the parser without touching login buttons", ()),
        ]
        for platform, request, paths in cases:
            with self.subTest(platform=platform, request=request):
                route = self.route(platform, request, paths=paths)
                self.assertNotIn(SKILL, route["required_docs"])


if __name__ == "__main__":
    unittest.main()
