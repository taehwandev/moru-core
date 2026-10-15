"""Request text may inform answers and documentation, never authorize work."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_request import classify_request, infer_concerns_from_request


class WorkflowRequestIntakeTests(unittest.TestCase):
    def test_branch_cleanup_shape_does_not_grant_authority(self) -> None:
        for request in (
            "머지된 브랜치와 워크트리 정리해줘",
            "Clean up merged branches and worktrees",
            "Delete merged remote branches",
            "Delete merged branch fix/example",
            "Remove the merged worktree",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("cleanup", result["route_shape"])
                self.assertEqual("triage", result["recommended_route"])

    def test_cleanup_phrasings_outside_the_first_grammar_still_reach_cleanup(self) -> None:
        """Each of these was routed to `task` or `ambiguity` and collected
        nineteen gates for a one-second git operation, because the grammar is a
        fullmatch and did not spell them. They differ from the accepted set by
        one construction each: a Korean nominaliser, a connector that closes
        the object list rather than joining another noun, an inflected verb
        stem, and a second verb after `and`.
        """

        for request in (
            "머지된거 워크트리랑 정리해줘",
            "머지된 것들 정리해줘",
            "머지된 브랜치 지워줘",
            "remove the stale worktree and delete the merged branch",
        ):
            with self.subTest(request=request):
                self.assertEqual("cleanup", classify_request(request)["route_shape"])

    def test_widened_cleanup_grammar_still_needs_a_cleanup_object(self) -> None:
        """The nominaliser carries no object of its own, so accepting it must
        not let any short imperative through.
        """

        for request in (
            "머지된 것들 구현해줘",
            "남은거 테스트해줘",
            "이거 정리해줘",
        ):
            with self.subTest(request=request):
                self.assertNotEqual("cleanup", classify_request(request)["route_shape"])

    def test_cleanup_does_not_capture_code_questions_or_bare_continuations(self) -> None:
        for request in (
            "코드 정리해줘", "Review branch cleanup logic",
            "브랜치 정리가 뭐야?", "정리도해줘",
            "Do not delete branches; review them",
            "Fix branch cleanup code",
            "Clean up merged branches and delete the production database",
            "Clean up merged branches and remove all project files",
            "브랜치 정리해줘 그리고 운영 데이터도 삭제해줘",
            "Clean up merged branches; deploy the app",
        ):
            with self.subTest(request=request):
                self.assertNotEqual("cleanup", classify_request(request)["route_shape"])

    def test_bare_cleanup_does_not_default_to_task_or_infer_authority(self) -> None:
        result = classify_request("정리도해줘", continuation_scope="Merged branches and worktrees")
        self.assertEqual("triage", result["route_shape"])
        self.assertEqual("triage", result["recommended_route"])

    def test_natural_language_never_selects_a_work_route(self) -> None:
        requests = (
            "코드 정리해줘",
            "Review the current diff",
            "Fix scripts/workflow.py line 10",
            "커밋하고 푸시해줘",
            "commit and push",
            "v1.2.3 태그를 배포해줘",
            "기획변경 때 문서 정리가 누락되는 걸 막아줘",
        )

        for request in requests:
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertNotEqual("work", classification["response_mode"])
                self.assertEqual("triage", classification["recommended_route"])

    def test_clear_request_needs_intake_preparation_not_repeated_questions(self) -> None:
        for request in ("Fix scripts/workflow.py line 10", "Review the current diff",
                        "Can you fix scripts/workflow.py?"):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("prepare_intent", result["response_mode"])
                self.assertFalse(result["grill_me"])
                self.assertEqual("triage", result["recommended_route"])

    def test_commit_push_pr_follow_up_keeps_the_commit_route_shape(self) -> None:
        for request in (
            "커밋하고 푸시한 뒤 develop 대상 PR까지 생성해줘",
            "커밋 + pr 해줘",
            "현재 브랜치 push하고 PR 만들어줘",
            "현재 브랜치 푸쉬하고 PR 만들어줘",
        ):
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("commit", classification["route_shape"])
                self.assertEqual("work", classification["shape_response_mode"])

    def test_push_to_a_release_destination_still_uses_release_shape(self) -> None:
        for request in (
            "push the signed build to production",
            "서명된 빌드를 프로덕션으로 푸시해줘",
        ):
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("release", classification["route_shape"])
                self.assertEqual("work", classification["shape_response_mode"])

    def test_direct_questions_remain_answer_first(self) -> None:
        for request in (
            "what does this do?",
            "이제 어떻게 동작해?",
            "Fix means the same as repair here, right?",
        ):
            with self.subTest(request=request):
                classification = classify_request(request)
                self.assertEqual("answer_first", classification["response_mode"])
                self.assertEqual("none", classification["recommended_route"])
                self.assertFalse(classification["grill_me"])

    def test_action_shaped_questions_are_not_answer_only(self) -> None:
        classification = classify_request("Can you fix scripts/workflow.py?")

        self.assertEqual("prepare_intent", classification["response_mode"])
        self.assertEqual("triage", classification["recommended_route"])


class ConcernInferenceTests(unittest.TestCase):
    def test_removed_graphify_never_adds_a_concern(self) -> None:
        for request in (
            "Install Graphify and build a project graph.",
            "Graphify는 제외하지 마.",
            "그래피를 실행해줘",
            "Use CodeGraph instead of Graphify.",
        ):
            with self.subTest(request=request):
                self.assertNotIn("graphify", infer_concerns_from_request(request))

    def test_auth_concern_requires_a_korean_term_boundary(self) -> None:
        self.assertNotIn(
            "auth",
            infer_concerns_from_request("클로드가 확인한것 같은 결함인가?"),
        )
        for request in ("인가 정책을 수정해줘", "인증/인가 흐름을 검토해줘"):
            with self.subTest(request=request):
                self.assertIn("auth", infer_concerns_from_request(request))

    def test_request_text_still_infers_non_authoritative_document_concerns(self) -> None:
        cases = (
            ("Add scenario regression tests", "testing"),
            ("Preserve Spill workflow label bridge data", "metering"),
            ("Update the agent skill bundle", "skill-card"),
            ("Review the branch naming strategy", "branch"),
            ("web service React Native Python 스킬 pack 추가", "web-service-stack"),
            ("크리스밴 스킬처럼 활용해서 rn react python 스킬 추가해줘", "web-service-stack"),
            ("React Native 화면을 추가해줘", "react-native"),
            ("FastAPI endpoint를 Python web service에 추가해줘", "python-web-service"),
            ("Create a Python API endpoint", "python-web-service"),
            ("크리스밴 스킬처럼 활용해서 rn react python 스킬 추가해줘", "python-web-service"),
        )
        for request, concern in cases:
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_generic_python_skill_requests_do_not_infer_web_service(self) -> None:
        for request in (
            "Add a Python data science skill card",
            "Create a Python CLI skill",
            "Create a Python exporter skill",
        ):
            with self.subTest(request=request):
                self.assertNotIn(
                    "python-web-service",
                    infer_concerns_from_request(request),
                )
                self.assertNotIn(
                    "web-service-stack",
                    infer_concerns_from_request(request),
                )


class AttachedHangulParticleTests(unittest.TestCase):
    """Attached Hangul particles must preserve complete keyword matches."""

    def test_other_latin_keyword_concerns_share_the_fix(self) -> None:
        """The normalization applies to every Latin keyword hint."""

        for request, concern in (
            ("SwiftUI는 어떻게 쓰지", "swift"),
            ("CI는 어떻게 되어 있어", "ci"),
            ("PR을 만들어줘", "pull-request"),
            ("SEO를 개선하자", "seo"),
        ):
            with self.subTest(request=request):
                self.assertIn(concern, infer_concerns_from_request(request))

    def test_negative_control_latin_identifiers_do_not_match(self) -> None:
        """The junction split must not become a substring match.

        The space only lands between a complete Latin run and an attached
        Hangul syllable, so a longer identifier still has to fail the hint.
        """

        self.assertNotIn("swift", infer_concerns_from_request("swifter를 고쳐줘"))
        self.assertNotIn(
            "swift", infer_concerns_from_request("swifters는 무엇인가")
        )


class MixedScriptRequestTests(unittest.TestCase):
    """A Korean particle attached to an English token hid it from the classifier.

    Hangul is a word character, so `\\bproduction\\b` does not match
    `production으로`: there is no boundary between `n` and `으`. Korean requests
    naming an English artifact, destination, path, or verb therefore classified
    as if those words were absent -- `v1.2.3을 build를 production으로 승격해줘`
    reached triage while its spaced form did not.

    The property under test is not which route each request gets. It is that
    attaching a particle cannot change the answer, which is what makes this a
    normalization bug rather than a pattern list to extend forever.
    """

    def _classification(self, text: str) -> tuple[str, str]:
        result = classify_request(text)
        return result["route_shape"], result["shape_response_mode"]

    def test_a_particle_does_not_change_the_classification(self) -> None:
        for joined, spaced in (
            (
                "v1.2.3을 build를 production으로 승격해줘",
                "v1.2.3 을 build 를 production 으로 승격해줘",
            ),
            (
                "v1.2.3 tag를 production으로 배포해줘",
                "v1.2.3 tag 를 production 으로 배포해줘",
            ),
            ("working tree를 review해줘", "working tree 를 review 해줘"),
            (
                "scripts/workflow.py의 line 10을 fix해줘",
                "scripts/workflow.py 의 line 10 을 fix 해줘",
            ),
        ):
            with self.subTest(request=joined):
                self.assertEqual(
                    self._classification(spaced), self._classification(joined)
                )

    def test_a_scoped_korean_promotion_naming_english_parts_is_a_release(self) -> None:
        # The reviewer's case: every release signal is present and every one of
        # them is an English token carrying a Korean particle.
        shape, mode = self._classification("v1.2.3을 build를 production으로 승격해줘")

        self.assertEqual("release", shape)
        self.assertEqual("work", mode)

    def test_the_request_is_echoed_as_the_user_wrote_it(self) -> None:
        # Normalization is for matching. Spacing the text for the reader would
        # change what every consumer of this field sees.
        request = "v1.2.3을 production으로 승격해줘"

        self.assertEqual(request, classify_request(request)["request"])


class PromotionReleaseActionTests(unittest.TestCase):
    """A promotion is a release, and it did not route like one.

    `RELEASE_ACTION_PATTERNS` named the verbs that start a release -- deploy,
    publish, ship, tag, push -- but not the ones that finish one. "Promote the
    staging build to production" therefore carried no release action, so the
    release branch never fired and the two-signal scope rule never got the
    chance to send it to Grill-Me either. It routed as an ordinary `task` in
    `work` mode: no release readiness, and no clarification.
    """

    def test_a_promotion_to_production_routes_to_release(self) -> None:
        for request in (
            "promote the 1.4.0 staging build to production for the ios app",
            "roll out the 1.4.0 staging build to production for the ios app",
            "1.4.0 스테이징 빌드를 프로덕션으로 승격해줘",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("release", result["route_shape"])
                self.assertEqual("work", result["shape_response_mode"])

    def test_a_bare_promotion_verb_still_asks_for_clarification(self) -> None:
        # Naming no artifact and no destination is a real ambiguity, not a gap.
        for request in ("promote it", "승격해줘"):
            with self.subTest(request=request):
                self.assertEqual(
                    "clarify_first", classify_request(request)["response_mode"]
                )

    def test_a_destination_named_before_the_verb_is_still_a_promotion(self) -> None:
        """Korean puts the destination first, and the anchor read one order.

        `promote` is anchored to a destination so this repo's own promotions --
        lesson candidates -- do not read as deploys. The anchor was written as
        verb-then-destination, which is English word order;
        `production으로 promote해줘` names the destination first and carried no
        release action at all.
        """

        result = classify_request(
            "v26.08.5 build를 staging에서 production으로 promote해줘"
        )

        self.assertEqual("release", result["route_shape"])
        self.assertEqual("work", result["shape_response_mode"])

    def test_a_single_digit_major_version_is_release_scope(self) -> None:
        """The version signal required a two-digit major, so v1.2.3 was not one.

        The pattern was written for this project's date-style versions
        (26.08.5) and excluded ordinary semver. A promotion naming v1.2.3 and a
        destination then had one scope signal where it needed two.
        """

        result = classify_request("v1.2.3을 staging에서 production으로 승격해줘")

        self.assertEqual("release", result["route_shape"])
        self.assertEqual("work", result["shape_response_mode"])

    def test_a_bare_count_is_not_a_version(self) -> None:
        """Widening the major digit must not make every number a version.

        Written first as `v1.2.3 확인해줘`, which proved nothing: with the
        version pattern replaced by `\\b\\d+\\b` that request still had one
        signal and still was not a release. `배포 3건 해줘` is where the
        difference shows -- an action, a count, and nothing else -- and it must
        stay a clarification.
        """

        self.assertNotEqual(
            "release", classify_request("배포 3건 해줘")["route_shape"]
        )
        self.assertNotEqual(
            "release", classify_request("v1.2.3 확인해줘")["route_shape"]
        )

    def test_promoting_something_that_is_not_a_build_keeps_the_commit_route(self) -> None:
        """`promote` is anchored to a destination, and this is what that buys.

        Written first as `assertNotEqual("release", ...)` on a bare promotion,
        which passed with or without the anchor: that request names no release
        scope, so the two-signal rule rejects it either way. The anchor earns
        its keep one level down. `commit_release_substep` is false whenever a
        commit request also carries a release action, so an unanchored
        `promote` costs this request its commit route entirely.
        """

        result = classify_request("commit the fix and promote the lesson candidates")
        self.assertEqual("commit", result["route_shape"])
        self.assertNotEqual("release", result["route_shape"])


class KoreanReleaseScopeSignalTests(unittest.TestCase):
    """Release scope signals were English-only while the action list was not.

    A Korean request could name the action -- 배포 was already in
    RELEASE_ACTION_PATTERNS -- but never the destination, so the two-signal scope
    rule read a real deploy as an unclear ask and sent it to Grill-Me. The English
    phrasing of the same request routed to `release`, which is the asymmetry.
    """

    def test_korean_deploy_with_a_destination_routes_to_release(self) -> None:
        for request in (
            "테스터에게 앱 배포",
            "develop 최신화하고 Firebase App Distribution 으로 테스터에게 배포해줘",
        ):
            with self.subTest(request=request):
                result = classify_request(request)
                self.assertEqual("release", result["route_shape"])
                self.assertEqual("work", result["shape_response_mode"])

    def test_a_bare_deploy_verb_still_asks_for_clarification(self) -> None:
        # Naming no artifact and no destination is a real ambiguity, not a gap.
        result = classify_request("배포해줘")
        self.assertEqual("clarify_first", result["response_mode"])

    def test_unrelated_requests_keep_their_route(self) -> None:
        self.assertEqual("code-simplify", classify_request("리팩터링해줘")["route_shape"])


class DeviceMcpRoutingTests(unittest.TestCase):
    def test_on_device_requests_select_device_preparation(self):
        for request in (
            "실기기로 키보드 포커스 검증해줘",
            "에뮬레이터에서 화면 이동 테스트해줘",
            "안드로이드 UI 테스트 실행해줘",
            "verify navigation on an android device",
            "run mobile UI tests",
        ):
            with self.subTest(request=request):
                self.assertIn("device-testing", infer_concerns_from_request(request))

    def test_source_and_unit_work_do_not_prepare_devices(self):
        for request in (
            "안드로이드 API 응답 필드 조회해줘",
            "Android mapper unit tests",
            "커밋하고 문서 정리해줘",
            "에뮬레이터 없이 단위 테스트만 실행해줘",
        ):
            with self.subTest(request=request):
                self.assertNotIn("device-testing", infer_concerns_from_request(request))

    def test_device_concern_routes_directly_to_compact_contract(self):
        from workflow_concern_docs import CONCERNS
        self.assertEqual(
            ("common/skills/local-tools/references/device-mcp.md",),
            CONCERNS["device-testing"],
        )


class LookupShapeSurvivesIntakeTests(unittest.TestCase):
    """A read-only question must not be shaped as general multi-step work.

    Shaping "does the Android response carry this field" as `task` is what made
    the prompt advisory disagree with the same question run as `analysis`: one
    selected the implementation reading, the other selected one card.
    """

    def test_an_inspection_request_keeps_the_lookup_route(self) -> None:
        for request in (
            "Android 응답에 특정 필드가 있는지 확인해줘",
            "웹 재시도 설정이 어디에 있는지 설명해줘",
            "check the retry config status",
            "explain the retry config in the web client",
        ):
            with self.subTest(request=request):
                result = classify_request(request, conversation_first=True)

                self.assertEqual("analysis", result["route_shape"])
                self.assertEqual("work", result["shape_response_mode"])
                # A shape is never an authorization; intake still routes triage.
                self.assertEqual("triage", result["recommended_route"])

    def test_a_lookup_verb_without_a_target_is_not_a_lookup(self) -> None:
        for request in ("설명해줘", "explain", "확인해줘", "check"):
            with self.subTest(request=request):
                self.assertNotEqual(
                    "analysis",
                    classify_request(request, conversation_first=True)["route_shape"],
                )

    def test_look_and_change_is_not_a_lookup(self) -> None:
        """Reading only the inspection half drops the edit the user asked for."""

        for request in (
            "기본 이미지 필드가 있는지 확인하고 없으면 추가해줘",
            "재시도 설정 확인하고 값 바꿔줘",
            "상태 확인하고 수정해줘",
            "explain the mapper and fix the parsing bug",
            "설명하고 고쳐줘",
        ):
            with self.subTest(request=request):
                self.assertNotEqual(
                    "analysis",
                    classify_request(request, conversation_first=True)["route_shape"],
                )

    def test_an_edit_named_only_to_exclude_it_leaves_the_lookup(self) -> None:
        for request in (
            "수정은 하지 말고 함수 설명해줘",
            "explain the mapper without changing anything",
            "고치지 말고 상태만 확인해줘",
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    "analysis",
                    classify_request(request, conversation_first=True)["route_shape"],
                )

    def test_an_edit_request_is_not_reshaped_into_a_lookup(self) -> None:
        for request in (
            "Android JSON 파싱 오류 수정해줘",
            "add the retry header to the web client",
            "v1.2.0 태그 만들고 릴리즈 노트 써줘",
        ):
            with self.subTest(request=request):
                self.assertNotEqual(
                    "analysis",
                    classify_request(request, conversation_first=True)["route_shape"],
                )


if __name__ == "__main__":
    unittest.main()
