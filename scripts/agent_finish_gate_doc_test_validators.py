"""Documentation and test finish gate validators."""

from __future__ import annotations

import re

from agent_finish_gate_skip_policy import _evidence_records_skip_reason
from agent_finish_gate_validators import (
    DOC_COVERAGE_STATE_PHRASES,
    DOC_INSPECTION_PROOF_PHRASES,
    NO_DOC_DECISIONS,
    accepted,
    UNCHANGED_DECISIONS,
    _explicit_documentation_decision,
    _has_durable_doc_change_signal,
    _unchanged_evidence_is_grounded,
    documentation_decision_has_any,
    has_any,
)


DOCUMENTATION_EVIDENCE_REQUIRED = (
    "documentation evidence is required and cannot be empty: name the "
    "documentation decision (updated/created/unchanged), the affected "
    "source-of-truth doc path, and why that decision matches the change"
)

# Skipping documentation is never self-approved. When the agent believes docs
# should truly not be written, it must ask the user ("문서를 스킵할까요?" /
# "Should I skip the doc?") and record their explicit approval. A reason alone
# is not enough — these phrases prove the human review happened.
DOC_SKIP_APPROVAL_PHRASES = (
    "user approved", "user confirmed", "user agreed", "user reviewed and approved",
    "approved skipping", "approved the skip", "skip approved by",
    "user said skip", "user asked to skip", "user chose to skip",
    "human approved", "operator approved", "confirmed with the user to skip",
    "user approved skipping",
    "사용자 승인", "사용자가 승인", "사용자 확인", "사용자 검토 후",
    "검토받아", "검토받고", "스킵 승인", "문서 스킵 승인", "물어보고 승인",
    "사용자에게 확인받",
)

DOCUMENTATION_SKIP_NEEDS_APPROVAL = (
    "documentation cannot be skipped (not-applicable/no-docs/skipped) on the "
    "agent's own judgment or a reason alone: ask the user '문서를 스킵할까요?' / "
    "'Should I skip the doc?', get explicit approval, and record that approval "
    "in the evidence — otherwise write the doc"
)


def validate_documentation(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return [DOCUMENTATION_EVIDENCE_REQUIRED]
    has_decision = any(
        phrase in text
        for phrase in (
            "updated",
            "created",
            "added",
            "not applicable",
            "unchanged",
            "no doc update",
            "no docs update",
            "docs unchanged",
            "source-of-truth updated",
            "source of truth updated",
        )
    )
    names_target = any(
        phrase in text
        for phrase in (
            ".md",
            "readme",
            "agents",
            "prd",
            "spec",
            "ard",
            "runbook",
            "wiki",
            "source-of-truth",
            "source of truth",
            "docs/",
            "workflows/",
            "common/",
            "platforms/",
            "product-patterns/",
        )
    )
    explains_reason = any(
        phrase in text
        for phrase in (
            "because",
            "reason",
            "why",
            "due to",
            "changed",
            "no durable",
            "no user-visible",
            "workflow policy",
            "public contract",
            "acceptance criteria",
            "behavior",
            "architecture",
            "operator action",
            "왜",
            "이유",
            "변경",
            "문서 영향",
        )
    )
    if documentation_decision_has_any(text, NO_DOC_DECISIONS) and _has_durable_doc_change_signal(text):
        return [
            "documentation evidence cannot use not-applicable/no-docs when it "
            "also names a durable planning, requirements, acceptance, workflow "
            "policy, public contract, operator, architecture, API, release, or "
            "test-plan change"
        ]
    if _is_documentation_skip_decision(text) and not has_any(text, DOC_SKIP_APPROVAL_PHRASES):
        return [DOCUMENTATION_SKIP_NEEDS_APPROVAL]
    if documentation_decision_has_any(text, UNCHANGED_DECISIONS) and not _unchanged_evidence_is_grounded(text):
        return [
            "documentation evidence can use unchanged only when it names the "
            "existing doc path it opened/inspected and states why that "
            "already-read doc covers the planning, behavior, contract, or "
            "acceptance change; a bare coverage claim is not enough."
            + accepted(DOC_INSPECTION_PROOF_PHRASES).replace(
                "accepted wording includes", "inspection proof is recognised on"
            )
            + accepted(DOC_COVERAGE_STATE_PHRASES, limit=6).replace(
                "accepted wording includes", "and the coverage claim on"
            )
        ]
    if has_decision and names_target and explains_reason:
        return []
    return [
        "documentation evidence must name the documentation decision "
        "(updated/created/unchanged/not applicable), the affected source-of-truth "
        "doc path or doc class, and why that decision matches the behavior, "
        "workflow policy, public contract, or durable acceptance criteria changed"
    ]


def _is_documentation_skip_decision(text: str) -> bool:
    """True when the documentation evidence declares a skip: an explicit
    not-applicable/no-docs decision or any recorded skip/생략 reason."""
    explicit = _explicit_documentation_decision(text)
    if explicit is not None:
        return has_any(explicit, NO_DOC_DECISIONS)
    return has_any(text, NO_DOC_DECISIONS) or _evidence_records_skip_reason(text)


# validate_tests renders these in its refusal, so the wording it accepts and the
# wording it advertises cannot drift apart.
TEST_SIGNAL_PHRASES = (
    "test", "pytest", "unittest", "unit", "integration", "regression",
    "smoke", "verification", "manual", "not applicable",
)
TEST_PASSED_PHRASES = (
    "passed", "pass", "0 failures", "no failures", "green", "성공", "통과",
)

# A pass word on its own is not a result: "통과" and "passed" are equally true of
# a suite that never ran, which is how a finish gate reports SUCCESS for work
# whose checks were never executed. This gate cannot run the project's suite, so
# it requires the claim to be falsifiable by whoever reads it -- either a
# positive outcome the run produced (exit 0, an explicit zero-error result, a
# full success ratio N/N with N>0, or a positive count with a verification unit)
# or a recognized test runner/selector. Path-like script commands count only
# together with a falsifiable result, and zero-run or nonzero-failure claims
# are rejected as success evidence.
_COUNT_ADJECTIVE = (
    r"(?:captured|sampled|exact|unit|integration|regression|smoke|e2e|visual|"
    r"automated|manual|passing|passed|verified|total|changed|exported)\s+"
)
_COUNT_UNIT = (
    r"(?:tests?|cases?|specs?|scenarios?|checks?|assertions?|suites?|examples?|"
    r"frames?|stills?|screenshots?|shots?|captures?|renders?|clips?|animations?|"
    r"pages?|screens?|routes?|views?|endpoints?|files?|modules?|targets?|"
    r"findings?|finding\(s\))"
)
_ZERO_ERROR_NOUN = (
    r"(?:errors?|failures?|failed|findings?|finding\(s\)|violations?|"
    r"regressions?|crashes?|exceptions?|warnings?)"
)
_KO_ZERO_ERROR_NOUN = r"(?:오류|에러|실패|경고|결함|문제|위반|이슈|크래시)"
_KO_FAIL_NOUN = r"(?:오류|에러|실패|결함|크래시)"
_TEST_NEGATION_RE = re.compile(
    r"\b(?:never|nothing\s+ran|not\s+loaded|did\s+not\s+run|didn't\s+run)\b"
    r"|(?<!\b0\s)\bskipped\b"
)
_TEST_FAILING_OR_ZERO_RE = re.compile(
    r"(?:exit|return|returncode|status|rc)\s*(?:code|status)?\s*[:=]?\s*[1-9]\d*\b"
    r"|(?<![0-9.-])\b[1-9]\d*\s+(?:failures?|failed|errors?)\b"
    r"|\b(?:failures?|failed|errors?)\s*[:=]\s*[1-9]\d*\b"
    r"|(?<![0-9.-])\b[1-9]\d*\s*(?:건|개)?\s*(?:의\s*)?" + _KO_FAIL_NOUN
    + r"|" + _KO_FAIL_NOUN + r"\s*[:=]?\s*[1-9]\d*\s*(?:건|개)?(?!\d)"
    r"|(?<![0-9.-])\b0\s+(?:tests?|cases?|specs?|checks?|assertions?|scenarios?|run|passed|executed)\b"
    r"|\b(?:ran|executed|run)\s+0\b"
    r"|\b(?:tests?|cases?|specs?|checks?|passed)\s*[:=]\s*0\b(?!\s+(?:" + _ZERO_ERROR_NOUN + r"))"
)
_PATH_EXEC_PASS_RE = re.compile(
    r"(?:(?:python3?|node|deno|bun|bash|sh|zsh|ruby|perl|php|pwsh)\s+|\./)"
    r"[\w./-]*/[\w.-]+\.(?:py|mjs|cjs|js|ts|sh|bash|zsh|rb|pl|php)"
    r"(?:\s+[^\n;,]+?)?"
    r"\s*(?:->|:)?\s*(?:\b(?:passed|pass|ok|succeeded)\b|(?:통과|성공))"
)
_TEST_RESULT_RE = re.compile(
    r"(?:exit|return|returncode|status|rc)\s*(?:code|status)?\s*[:=]?\s*0\b"
    r"|(?<![0-9.-])\b(?:0|zero)\b(?:\s+[a-z0-9_/-]+){0,4}\s+" + _ZERO_ERROR_NOUN + r"(?!\w)"
    r"|(?<![0-9.-])\b0\s*(?:건|개)?\s*(?:의\s*)?" + _KO_ZERO_ERROR_NOUN
    + r"|" + _KO_ZERO_ERROR_NOUN + r"\s*[:=]?\s*0\s*(?:건|개)?(?!\d)"
    r"|\b(?:failed|errors?|failures?|findings?)\s*[:=]?\s*\[\s*\]"
    r"|\b(?:errors?|failures?|findings?)\s*[:=]\s*0\b"
    r"|(?<![-/.\w])[1-9]\d*\s*(?:개|건)"
    r"|(?<![-/.\w])[1-9]\d*\s+(?:" + _COUNT_ADJECTIVE + r"){0,2}" + _COUNT_UNIT + r"(?!\w)"
    r"|\b(?:tests?|cases?|specs?|checks?|assertions?)\s*[:=]\s*[1-9]\d*\b"
    r"|\bok\s*\(?\s*[1-9]\d*"
)
# Counted ratios like `14/14 frames` or `18 / 18 checks passed` are falsifiable
# success outcomes only when numerator == denominator > 0 and followed by a
# verification unit word (or preceded by a verification unit and followed by a
# pass verb such as `regression tests 1560/1560 passed`). Unitless ratios (`3/3`)
# and time/occurrence/non-test units (`14/14 seconds`, `14/14 times`, `1/1 pr`)
# are rejected.
_TEST_RATIO_RE = re.compile(r"(?<![-/.\w])(\d+)\s*/\s*(\d+)(?![-/.\w])")
_RATIO_UNIT_AFTER_RE = re.compile(
    r"^\s+(?:" + _COUNT_ADJECTIVE + r"){0,2}" + _COUNT_UNIT + r"(?!\w)"
)
_RATIO_UNIT_BEFORE_RE = re.compile(r"(?:\b" + _COUNT_UNIT + r")\s+$")
_RATIO_PASS_AFTER_RE = re.compile(r"^\s+(?:\b(?:passed|pass|ok|succeeded)\b|(?:통과|성공))")
_TEST_RUNNER_COMMAND_RE = re.compile(
    r"\b(?:gradlew|pytest|unittest|jest|vitest|mocha|rspec|phpunit|mvn|make|"
    r"cargo|xcodebuild|swift\s+test|go\s+test|npm\s+(?:run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|detekt|ktlint|eslint|mypy|ruff|tsc)\b"
    r"|[\w.-]+/[\w./-]*\btest[\w./-]*"
    r"|\btest[\w.-]*\.(?:py|kt|kts|swift|ts|tsx|js|jsx|rb|go|java|cs)\b"
    r"|\b[\w.-]+_test\.[a-z]+\b"
    r"|\b[\w.-]+(?:test|spec)s?\b\s*(?:::|#|\.)\s*\w+"
)

TESTS_RESULT_REQUIRED = (
    "tests evidence claims a check ran but is not falsifiable: name either a "
    "passing result (exit 0, a positive verification count such as \"1163 tests\" "
    "or \"35 captured stills\", a unit-qualified ratio such as \"14/14 frames\", "
    "explicit zero-error output such as \"0 console errors\", \"0 findings\", "
    "\"검증 0건 오류\", \"failed []\", or an executed script with pass outcome "
    "such as \"node tools/check.mjs passed\") or a recognized test runner/selector. "
    "A pass word alone is equally true of a suite that never ran"
)
TESTS_FAILING_OR_ZERO_EVIDENCE = (
    "tests evidence reports zero tests run, negated/skipped execution, a nonzero "
    "failure/error count, or a nonzero exit status and cannot satisfy a passing tests gate"
)


def _ratio_verdict(text: str) -> tuple[bool, bool]:
    """Return (has_success_ratio, has_failing_ratio)."""
    has_success = False
    has_failing = False
    for match in _TEST_RATIO_RE.finditer(text):
        raw_num, raw_den = match.group(1), match.group(2)
        num, den = int(raw_num), int(raw_den)
        if num == 0:
            has_failing = True
            continue
        if raw_den.startswith("0"):
            continue
        after = text[match.end() :]
        before = text[: match.start()]
        has_unit_after = bool(_RATIO_UNIT_AFTER_RE.match(after))
        has_framed_pass = bool(
            _RATIO_UNIT_BEFORE_RE.search(before) and _RATIO_PASS_AFTER_RE.match(after)
        )
        if not (has_unit_after or has_framed_pass):
            continue
        if num == den and den > 0:
            has_success = True
        elif num < den:
            has_failing = True
    return has_success, has_failing


def _has_failing_or_zero_evidence(text: str) -> bool:
    if _TEST_NEGATION_RE.search(text):
        return True
    if _TEST_FAILING_OR_ZERO_RE.search(text):
        return True
    _, has_failing_ratio = _ratio_verdict(text)
    return has_failing_ratio


def _has_falsifiable_result(text: str) -> bool:
    if _TEST_RESULT_RE.search(text) or _PATH_EXEC_PASS_RE.search(text):
        return True
    has_success_ratio, _ = _ratio_verdict(text)
    return has_success_ratio


def validate_tests(evidence: str) -> list[str]:
    text = evidence.lower()
    if not text:
        return []
    if _TEST_NEGATION_RE.search(text):
        return [TESTS_FAILING_OR_ZERO_EVIDENCE]
    has_result = _has_falsifiable_result(text)
    has_runner = bool(_TEST_RUNNER_COMMAND_RE.search(text))
    has_test_signal = (
        any(phrase in text for phrase in TEST_SIGNAL_PHRASES)
        or has_result
        or has_runner
    )
    skipped = any(phrase in text for phrase in ("skipped", "not run", "unable", "cannot run"))
    explained_skip = any(
        phrase in text
        for phrase in (
            "because", "reason", "not applicable", "docs-only", "no useful test",
            "by design", "environment-gated", "environment gated", "intentional",
            "설계", "의도", "환경",
        )
    )
    # A suite that ran and passed is a named test run even when it mentions
    # skipped subtests; the skip guard is for runs that never happened.
    ran_and_passed = any(phrase in text for phrase in TEST_PASSED_PHRASES)
    if _claims_a_run(text, skipped, explained_skip) and _has_failing_or_zero_evidence(text):
        return [TESTS_FAILING_OR_ZERO_EVIDENCE]
    if has_test_signal and (not skipped or explained_skip or ran_and_passed):
        if (
            _claims_a_run(text, skipped, explained_skip)
            and not has_result
            and not has_runner
        ):
            return [TESTS_RESULT_REQUIRED]
        return []
    return [
        "tests evidence must name the test/check run or explain skipped/not-applicable tests with a reason."
        + accepted(TEST_SIGNAL_PHRASES)
        + accepted(TEST_PASSED_PHRASES, limit=6).replace(
            "accepted wording includes", "a run that passed also clears it on"
        )
    ]


def _claims_a_run(text: str, skipped: bool, explained_skip: bool) -> bool:
    """True when the evidence asserts a check executed rather than was waived.

    An approved skip and a not-applicable decision owe no result, so the outcome
    requirement applies only to the positive claim.
    """

    if "not applicable" in text:
        return False
    return not (skipped and explained_skip)
