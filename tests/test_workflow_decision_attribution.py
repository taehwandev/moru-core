"""Tests for deterministic decision-source attribution and Grill-Me open-choice gating."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from argparse import ArgumentParser, Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_decision_attribution_test", "agent-hook.py")

from agent_block_lessons import NEXT_ACTIONS, record_block  # noqa: E402
from workflow_effect_policy import effect_decision  # noqa: E402
from workflow_intent_dual_run import route_intake_decision  # noqa: E402
from workflow_intent_envelope import validate_envelope  # noqa: E402


SESSION = {"runtime": "codex", "session_id": "decision-attribution-session"}


class _Refused(Exception):
    """Capture parser.error without exiting the test runner."""


class DecisionAttributionUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        session = patch.object(agent_hook, "runtime_session", return_value=SESSION)
        session.start()
        self.addCleanup(session.stop)
        self.parser = ArgumentParser(prog="agent-hook.py")

    def _materialize(self, **overrides) -> Namespace:
        args = Namespace(
            project=ROOT,
            command="feature",
            request="Update the billing table to use a compact 3-column layout",
            continuation_scope="",
            request_classified=False,
            classification_evidence="",
            intent="update_billing_table",
            target_summary="billing table 3-column layout",
            requested_effect="",
            approved_effect="",
            prohibited_effect=[],
            decision_source=[],
            open_choice=[],
            ambiguity="",
            intent_envelope="",
            approval_record="",
            runtime_session_id="",
        )
        args.__dict__.update(overrides)
        agent_hook._materialize_compact_start_authority(self.parser, args)
        return args

    def _refusal(self, **overrides) -> str:
        def refuse(message: str) -> None:
            raise _Refused(message)

        with patch.object(self.parser, "error", side_effect=refuse):
            with self.assertRaises(_Refused) as refused:
                self._materialize(**overrides)
        return str(refused.exception)

    def test_cli_parser_registers_decision_attribution_flags(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "start",
                "--command",
                "feature",
                "--request",
                "Update the billing table",
                "--continuation-scope",
                "네",
                "--intent",
                "update_billing_table",
                "--target-summary",
                "billing table",
                "--decision-source",
                "request:billing table",
                "--decision-source",
                "conversation:네",
                "--open-choice",
                "Columns: 3 vs 4",
                "--ambiguity",
                "blocking",
            ]
        )
        self.assertEqual(["request:billing table", "conversation:네"], parsed.decision_source)
        self.assertEqual(["Columns: 3 vs 4"], parsed.open_choice)
        self.assertEqual("blocking", parsed.ambiguity)
        self.assertEqual("네", parsed.continuation_scope)

    def test_verified_request_and_repo_citations_pass_and_record_on_envelope(self) -> None:
        args = self._materialize(
            decision_source=[
                "request:compact 3-column layout",
                "repo:AGENTS.md:1-15",
            ],
        )
        envelope = json.loads(args.intent_envelope)
        self.assertEqual("resolved", envelope["ambiguity"])
        self.assertEqual(
            [
                {"kind": "request", "value": "compact 3-column layout"},
                {"kind": "repo", "value": "AGENTS.md:1-15"},
            ],
            envelope["decision_sources"],
        )
        self.assertEqual([], validate_envelope(envelope))

    def test_verbatim_matching_preserves_case_and_internal_spacing(self) -> None:
        case_mismatch = self._refusal(
            request="Format region code as US",
            decision_source=["request:us"],
        )
        self.assertIn("not a verbatim substring of --request", case_mismatch)

        spacing_mismatch = self._refusal(
            request="Replace token a  b with c",
            decision_source=["request:a b"],
        )
        self.assertIn("not a verbatim substring of --request", spacing_mismatch)

    def test_single_character_korean_confirmation_in_continuation_scope_passes(self) -> None:
        for answer in ("네", "예", "응", "A"):
            with self.subTest(answer=answer):
                args = self._materialize(
                    request="진행해줘",
                    continuation_scope=answer,
                    decision_source=[f"conversation:{answer}"],
                )
                envelope = json.loads(args.intent_envelope)
                self.assertEqual("resolved", envelope["ambiguity"])

    def test_conversation_source_does_not_fallback_to_request(self) -> None:
        message = self._refusal(
            request="compact 3-column layout",
            continuation_scope="",
            decision_source=["conversation:compact 3-column layout"],
        )
        self.assertIn("not a verbatim substring of --continuation-scope", message)

    def test_fabricated_request_quote_not_in_user_request_is_rejected(self) -> None:
        message = self._refusal(
            request="대시보드 화면 좀 개선해줘",
            decision_source=["request:card grid with dark glassmorphism"],
        )
        self.assertIn("not a verbatim substring of --request", message)
        self.assertIn("--open-choice", message)

    def test_nonexistent_or_internal_git_repo_path_or_line_is_rejected(self) -> None:
        missing_file = self._refusal(
            decision_source=["repo:scripts/does_not_exist_anywhere.py:10"],
        )
        self.assertIn("does not match an existing file", missing_file)

        git_internal = self._refusal(
            decision_source=["repo:.git/HEAD"],
        )
        self.assertIn("cannot cite internal `.git` or `.moru`", git_internal)

        bad_line = self._refusal(
            decision_source=["repo:AGENTS.md:999999"],
        )
        self.assertIn("line range is out of bounds", bad_line)

    def test_compatibility_intent_envelope_verifies_decision_sources_at_intake(self) -> None:
        from agent_route_state import request_fingerprint

        req = "대시보드 화면 좀 개선해줘"
        fp = request_fingerprint({"request": req, "continuation_scope": "", "request_classified": False, "classification_evidence": ""})
        explicit_envelope = {
            "schema_version": 1,
            "request_fingerprint": fp,
            "runtime_session_id": "decision-attribution-session",
            "mode": "work",
            "intent": "improve_dashboard",
            "target_summary": "dashboard layout",
            "requested_effects": ["local_write"],
            "ambiguity": "resolved",
            "decision_sources": [
                {"kind": "request", "value": "card grid with dark glassmorphism"},
            ],
        }
        classification, failures = route_intake_decision(
            "feature",
            explicit_envelope,
            request_fingerprint=fp,
            runtime_session_id="decision-attribution-session",
            project=ROOT,
            request_text=req,
            continuation_scope="",
        )
        self.assertIsNone(classification)
        self.assertTrue(any("not a verbatim substring of --request" in f for f in failures), failures)

    def test_open_choice_or_assumed_source_blocks_writable_start_with_grill_me_guidance(self) -> None:
        for kwargs in (
            {"open_choice": ["Layout density: compact table vs card grid"]},
            {"decision_source": ["assumed:conversational essay tone across chapters 1-2"]},
            {"ambiguity": "blocking"},
        ):
            with self.subTest(kwargs=kwargs):
                message = self._refusal(
                    command="feature",
                    request="대시보드랑 소개글 다듬어줘",
                    **kwargs,
                )
                self.assertIn("blocked by unresolved open choice(s)", message)
                self.assertIn("2-3 line copy sample or design sketch", message)
                self.assertIn("--continuation-scope", message)

    def test_once_user_answers_in_continuation_scope_writable_start_succeeds(self) -> None:
        args = self._materialize(
            command="feature",
            request="응 그걸로 진행해줘",
            continuation_scope=(
                "User confirmed: use compact 3-column table and keep conversational "
                "essay tone in chapter 1 and chapter 2"
            ),
            decision_source=[
                "conversation:compact 3-column table",
                "conversation:conversational essay tone in chapter 1 and chapter 2",
            ],
        )
        envelope = json.loads(args.intent_envelope)
        self.assertEqual("resolved", envelope["ambiguity"])
        self.assertEqual([], validate_envelope(envelope))
        self.assertEqual(
            [],
            effect_decision(
                "feature",
                envelope,
                request_fingerprint=envelope["request_fingerprint"],
                runtime_session_id=envelope["runtime_session_id"],
            ),
        )

    def test_contradictory_resolved_ambiguity_with_open_choices_is_rejected(self) -> None:
        message = self._refusal(
            open_choice=["Tone: analytical vs narrative"],
            ambiguity="resolved",
        )
        self.assertIn("--ambiguity resolved cannot be combined", message)

        bad_envelope = {
            "schema_version": 1,
            "request_fingerprint": "a1b2c3d4e5f60718",
            "runtime_session_id": "decision-attribution-session",
            "mode": "work",
            "intent": "edit_prose",
            "target_summary": "chapter 1 prose",
            "requested_effects": ["local_write"],
            "ambiguity": "resolved",
            "open_choices": ["Tone: analytical vs narrative"],
        }
        self.assertTrue(validate_envelope(bad_envelope))

    def test_minimal_triage_and_ambiguity_starts_propagate_blocking_envelope_and_grill_me(self) -> None:
        for command in ("triage", "ambiguity"):
            with self.subTest(command=command):
                args = self._materialize(
                    command=command,
                    request="소개 페이지 톤 좀 바꿔줘",
                    intent="",
                    target_summary="",
                    open_choice=["Voice: analytical essay vs first-person narrative"],
                )
                envelope = json.loads(args.intent_envelope)
                self.assertEqual("blocking", envelope["ambiguity"])
                self.assertEqual(
                    ["Voice: analytical essay vs first-person narrative"],
                    envelope["open_choices"],
                )
                self.assertTrue(
                    any("open choices recorded for Grill-Me alignment" in n for n in getattr(args, "start_notes", []))
                )
                classification, failures = route_intake_decision(
                    command,
                    envelope,
                    request_fingerprint=envelope["request_fingerprint"],
                    runtime_session_id=envelope["runtime_session_id"],
                    project=ROOT,
                    request_text=args.request,
                )
                self.assertEqual([], failures)
                self.assertIsNotNone(classification)
                assert classification is not None
                self.assertEqual("ambiguous", classification["clarity"])
                self.assertTrue(classification["grill_me"])
                self.assertEqual("clarify_first", classification["response_mode"])

    def test_new_start_block_codes_are_registered_in_agent_block_lessons(self) -> None:
        for code in ("start_open_choice_grill_me_required", "start_decision_source_invalid"):
            with self.subTest(code=code):
                self.assertIn(code, NEXT_ACTIONS["agent_hook_start"])


if __name__ == "__main__":
    unittest.main()
