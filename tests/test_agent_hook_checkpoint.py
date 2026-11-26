from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_hook_checkpoint
from agent_continuation_fields import MAX_SHORT_TEXT, MAX_TEXT
from agent_continuation_packet import MAX_PACKET_BYTES
from test_agent_runtime_session import RuntimeFixture

_SPEC = importlib.util.spec_from_file_location(
    "agent_hook_checkpoint_parser_test", ROOT / "scripts" / "agent-hook.py"
)
assert _SPEC and _SPEC.loader
agent_hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_hook)


def _args(fixture: RuntimeFixture, **overrides) -> Namespace:
    values = {
        "project": fixture.project,
        "rules": fixture.rules,
        "evidence": fixture.evidence,
        "output": None,
        "repair_cycle": 0,
        "checkpoint_kind": "decision",
        "phase": None,
        "last_completed": None,
        "mutation_kind": None,
        "mutation_path": [],
        "work_stdin": True,
    }
    values.update(overrides)
    return Namespace(**values)


def _stdin(payload: dict) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")))


class CheckpointCommandTests(unittest.TestCase):
    def test_work_file_records_the_parsed_checkpoint_without_touching_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work_file = fixture.project / "work state.json"
            work = {
                "objective": "작업 결정을 보존한다",
                "decisions": [{"id": "file_input", "status": "accepted", "text": "Use one file argument"}],
            }
            work_file.write_text(json.dumps(work, ensure_ascii=False), encoding="utf-8")
            parser = agent_hook.build_parser()
            args = parser.parse_args([
                "checkpoint", "--project", str(fixture.project),
                "--rules", str(fixture.rules), "--evidence", str(fixture.evidence),
                "--checkpoint-kind", "decision", "--work-file", str(work_file),
            ])
            before = fixture.packet()
            with patch.object(sys, "stdin", object()), redirect_stdout(io.StringIO()):
                code = agent_hook._run_checkpoint_hook(parser, args)

            self.assertEqual(0, code)
            packet = fixture.packet()
            self.assertEqual(work["objective"], packet["work"]["objective"])
            self.assertEqual(work["decisions"], packet["work"]["decisions"])
            self.assertEqual(before["generation"] + 1, packet["generation"])
            self.assertEqual(before["binding"], packet["binding"])
            self.assertEqual(before["checkpoint"]["first_unfinished"], packet["checkpoint"]["first_unfinished"])

    def test_work_file_and_stdin_are_mutually_exclusive(self) -> None:
        parser = agent_hook.build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args([
                "checkpoint", "--checkpoint-kind", "decision", "--work-stdin", "--work-file", "work.json",
            ])
        self.assertEqual(2, raised.exception.code)

    def test_work_file_cannot_be_silently_discarded_by_template_or_shape(self) -> None:
        for display in ("--work-template", "--work-shape"):
            with self.subTest(display=display):
                parser = agent_hook.build_parser()
                args = parser.parse_args(["checkpoint", display, "--work-file", "work.json"])
                with (
                    patch.object(agent_hook_checkpoint, "run_binding_path") as binding,
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    agent_hook._run_checkpoint_hook(parser, args)
                self.assertEqual(2, raised.exception.code)
                binding.assert_not_called()

    def test_invalid_work_files_leave_the_packet_unchanged_without_echoing_content(self) -> None:
        scenarios = (
            (b'{"objective":"private-do-not-print"', "valid JSON"),
            (b'{"objective":"private-do-not-print\xff"}', "UTF-8"),
            (b'["private-do-not-print"]', "must be an object"),
            (b'{"transcript":"private-do-not-print"}', "unknown_field"),
            (b"private-do-not-print" + b"x" * MAX_PACKET_BYTES, "packet budget"),
        )
        for encoded, diagnostic in scenarios:
            with self.subTest(diagnostic=diagnostic), tempfile.TemporaryDirectory() as directory:
                fixture = RuntimeFixture(directory)
                work_file = fixture.project / "work.json"
                work_file.write_bytes(encoded)
                before = fixture.packet()
                output = io.StringIO()
                with patch.object(sys, "stdin", object()), redirect_stdout(output):
                    code = agent_hook_checkpoint.checkpoint_hook(
                        _args(fixture, work_stdin=False, work_file=work_file)
                    )
                self.assertNotEqual(0, code)
                self.assertEqual(before, fixture.packet())
                self.assertIn(diagnostic, output.getvalue())
                self.assertNotIn("private-do-not-print", output.getvalue())
                self.assertNotIn("\\xff", output.getvalue())

    def test_work_file_byte_budget_accepts_the_limit_and_refuses_one_extra_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work_file = fixture.project / "work.json"
            encoded = b'{"objective":"bounded"}'
            encoded += b" " * (MAX_PACKET_BYTES - len(encoded))
            work_file.write_bytes(encoded)
            with patch.object(sys, "stdin", object()), redirect_stdout(io.StringIO()):
                code = agent_hook_checkpoint.checkpoint_hook(
                    _args(fixture, work_stdin=False, work_file=work_file)
                )
            self.assertEqual(0, code)
            before = fixture.packet()
            work_file.write_bytes(encoded + b" ")
            with patch.object(sys, "stdin", object()), redirect_stdout(io.StringIO()):
                code = agent_hook_checkpoint.checkpoint_hook(
                    _args(fixture, work_stdin=False, work_file=work_file)
                )
            self.assertNotEqual(0, code)
            self.assertEqual(before, fixture.packet())

    def test_missing_work_file_is_unavailable_without_path_or_state_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            work_file = fixture.project / "private-missing-file.json"
            output = io.StringIO()
            with patch.object(sys, "stdin", object()), redirect_stdout(output):
                code = agent_hook_checkpoint.checkpoint_hook(
                    _args(fixture, work_stdin=False, work_file=work_file)
                )
            self.assertNotEqual(0, code)
            self.assertEqual(before, fixture.packet())
            self.assertIn("checkpoint unavailable: FileNotFoundError", output.getvalue())
            self.assertNotIn(str(work_file), output.getvalue())

    def test_overlong_prose_is_bounded_with_a_warning_without_echoing(self) -> None:
        for field, limit in (("objective", MAX_TEXT), ("non_goals", MAX_SHORT_TEXT)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = RuntimeFixture(directory)
                before = fixture.packet()
                value = "가" * (limit + 1)
                work = {field: [value] if field == "non_goals" else value}
                output = io.StringIO()
                with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(output):
                    code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

                self.assertEqual(0, code, output.getvalue())
                self.assertIn("Warning: truncated", output.getvalue())
                recorded = fixture.packet()["work"][field]
                self.assertEqual(value[:limit], recorded[0] if isinstance(recorded, list) else recorded)
                self.assertNotIn(value, output.getvalue())

    def test_acceptance_criteria_preserve_trailing_qualifiers_or_reject_the_whole_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            exact = "가" * MAX_SHORT_TEXT
            with patch.object(sys, "stdin", _stdin({"acceptance_criteria": [exact]})), redirect_stdout(io.StringIO()):
                self.assertEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
            saved = fixture.packet()
            self.assertEqual([exact], saved["work"]["acceptance_criteria"])
            long = exact + " unless skipped"
            with patch.object(sys, "stdin", _stdin({"acceptance_criteria": [long]})), redirect_stdout(io.StringIO()) as output:
                self.assertNotEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
            self.assertIn(f"acceptance_criteria[0] has {len(long)} Unicode characters", output.getvalue())
            self.assertIn(f"maximum {MAX_SHORT_TEXT}", output.getvalue())
            self.assertIn("Example:", output.getvalue())
            self.assertEqual(saved, fixture.packet())

    def test_checkpoint_shorthand_keeps_partial_acceptance_and_does_not_invent_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work = {"remaining_work": ["15 of 17 verified"], "decisions": "retain partial acceptance",
                    "verification": "unit failed", "changed_scope": {"path": "./src/a.py", "role": "modified"}}
            args = _args(fixture, work_stdin=False, work_json=json.dumps(work))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, agent_hook_checkpoint.checkpoint_hook(args))
            saved = fixture.packet()["work"]
            self.assertEqual("15 of 17 verified", saved["remaining_work"][0]["action"])
            self.assertEqual("retain partial acceptance", saved["decisions"][0]["text"])
            self.assertEqual("fail", saved["verification"][0]["result"])
            self.assertEqual("src/a.py", saved["changed_scope"][0]["path"])
            work["changed_scope"]["path"] = "../private"
            args.work_json = json.dumps(work)
            with redirect_stdout(io.StringIO()) as output:
                self.assertNotEqual(0, agent_hook_checkpoint.checkpoint_hook(args))
            self.assertIn("invalid_path", output.getvalue())
            self.assertIn('"path": "docs/guide.md"', output.getvalue())
            self.assertEqual(saved, fixture.packet()["work"])

    def test_checkpoint_does_not_truncate_away_unsafe_content_or_guess_timezones(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            row = {"id": "unit", "kind": "unit", "result": "fail", "evidence_sha256": None,
                   "completed_at": "2026-11-19T12:00:00"}
            for work, rule in (({"verification": row}, "invalid_timestamp"),
                               ({"objective": "x" * MAX_TEXT + "\nprivate"}, "prose_not_single_line")):
                with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(io.StringIO()) as output:
                    self.assertNotEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
                self.assertIn(rule, output.getvalue())
                self.assertEqual(before, fixture.packet())
            row["completed_at"] += "+09:00"
            with patch.object(sys, "stdin", _stdin({"verification": row})), redirect_stdout(io.StringIO()):
                self.assertEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
            self.assertEqual("2026-11-19T03:00:00+00:00", fixture.packet()["work"]["verification"][0]["completed_at"])

    def test_prose_accepts_unicode_characters_at_the_canonical_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work = {
                "objective": "가" * MAX_TEXT,
                "non_goals": ["나" * MAX_SHORT_TEXT],
            }
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(io.StringIO()):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertEqual(0, code)
            self.assertEqual(work["objective"], fixture.packet()["work"]["objective"])
            self.assertEqual(work["non_goals"], fixture.packet()["work"]["non_goals"])

    def test_a_sentence_as_last_completed_becomes_a_bounded_step_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            sentence = ("All architect findings visually accepted and documented; "
                        "deterministic seek, choreography and structural review passed.")
            args = _args(fixture, last_completed=sentence)
            with patch.object(sys, "stdin", _stdin({"objective": "bounded"})), redirect_stdout(io.StringIO()) as output:
                code = agent_hook_checkpoint.checkpoint_hook(args)
            self.assertEqual(0, code, output.getvalue())
            self.assertEqual("All-architect-findings-visually-accepted-and-documented-determin",
                             fixture.packet()["checkpoint"]["last_completed"])

    def test_checkpoint_aliases_reach_the_same_inputs(self):
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(["checkpoint", "--checkpoint", "decision", "--evidence-file", "preflight.json",
                                    "--work-json", '{"objective":"Deliver A1 rain and grade"}'])
        self.assertEqual("decision", parsed.checkpoint_kind)
        self.assertEqual("preflight.json", parsed.evidence.name)
        self.assertEqual("Deliver A1 rain and grade", json.loads(parsed.work_json)["objective"])
        batch = parser.parse_args(["gate-batch", "--gates-json", "records.json"])
        self.assertEqual("records.json", batch.gate_json.name)

    def test_an_unwritable_run_state_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            output = io.StringIO()
            with redirect_stdout(output), patch.object(
                agent_hook_checkpoint, "run_binding_path", side_effect=PermissionError(1, "denied"),
            ):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertNotEqual(0, code)
            self.assertIn("run state is not writable from this sandbox", output.getvalue())

    def test_template_cannot_silently_discard_a_requested_checkpoint(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args([
            "checkpoint", "--work-template", "--checkpoint-kind", "decision",
        ])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            agent_hook._run_checkpoint_hook(parser, args)
        self.assertEqual(2, raised.exception.code)

    def test_template_is_read_only_json_and_can_be_submitted_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            output = io.StringIO()
            parser = agent_hook.build_parser()
            args = parser.parse_args(["checkpoint", "--work-template"])
            with redirect_stdout(output), patch.object(
                agent_hook_checkpoint, "run_binding_path",
                side_effect=AssertionError("template must not resolve run state"),
            ):
                self.assertEqual(0, agent_hook._run_checkpoint_hook(parser, args))
            work = json.loads(output.getvalue())
            self.assertEqual(before, fixture.packet())
            work["objective"] = "Complete the bounded change"
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(io.StringIO()):
                self.assertEqual(0, agent_hook_checkpoint.checkpoint_hook(_args(fixture)))
            self.assertEqual(work["objective"], fixture.packet()["work"]["objective"])

    def test_semantic_checkpoint_reads_only_the_closed_work_object_from_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            work = {
                "objective": "finish the continuation adapter",
                "decisions": [
                    {
                        "id": "runtime_adapter",
                        "status": "accepted",
                        "text": "Claude supplies only exact lifecycle events",
                    }
                ],
            }
            output = io.StringIO()
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(output):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertEqual(0, code)
            self.assertIn("SUCCESS checkpoint", output.getvalue())
            self.assertEqual(
                "finish the continuation adapter", fixture.packet()["work"]["objective"]
            )

    def test_transcript_shaped_unknown_field_is_refused_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            output = io.StringIO()
            with (
                patch.object(
                    sys,
                    "stdin",
                    _stdin({"transcript": "password=do-not-print"}),
                ),
                redirect_stdout(output),
            ):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertNotEqual(0, code)
            self.assertEqual(before, fixture.packet())
            self.assertNotIn("do-not-print", output.getvalue())
            self.assertIn("unknown_field", output.getvalue())
            self.assertIn("--work-template", output.getvalue())
            self.assertIn("Do not fabricate", output.getvalue())

    def test_rejected_record_lists_show_only_the_relevant_schema_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            before = fixture.packet()
            output = io.StringIO()
            work = {
                "verification": ["private-check-result", "another-private-result"],
                "remaining_work": ["private-next-action"],
            }
            with patch.object(sys, "stdin", _stdin(work)), redirect_stdout(output):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            rendered = output.getvalue()
            self.assertNotEqual(0, code)
            self.assertEqual(before, fixture.packet())
            self.assertIn("Expected work input", rendered)
            self.assertIn("evidence_sha256, completed_at", rendered)
            self.assertNotIn("{checkpoint, action}", rendered)
            self.assertEqual(1, rendered.count("evidence_sha256, completed_at"))
            self.assertNotIn("{id, status:", rendered)
            for value in work["verification"] + work["remaining_work"]:
                self.assertNotIn(value, rendered)

    def test_rejection_shape_is_read_from_the_canonical_shape_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            output = io.StringIO()
            with (
                patch.object(sys, "stdin", _stdin({"decisions": [42]})),
                patch("agent_hook_continuation._work_shape_lines", return_value=[
                    "    decisions[12]: canonical-shape-marker",
                    "    verification[32]: unrelated-shape-marker",
                ]),
                redirect_stdout(output),
            ):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))

            self.assertNotEqual(0, code)
            self.assertIn("canonical-shape-marker", output.getvalue())
            self.assertNotIn("unrelated-shape-marker", output.getvalue())

    def test_unknown_field_suffix_does_not_select_a_different_fields_shape(self) -> None:
        for field in ("work", "criteria", "", "status", "decisions/x", "decisions/0/x", "objective/x"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = RuntimeFixture(directory)
                output = io.StringIO()
                with (
                    patch.object(sys, "stdin", _stdin({field: ["private-next-action"]})),
                    redirect_stdout(output),
                ):
                    code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))
                self.assertNotEqual(0, code)
                self.assertIn("unknown_field", output.getvalue())
                self.assertNotIn("Expected work input", output.getvalue())
                self.assertNotIn("private-next-action", output.getvalue())

    def test_grouped_schema_rows_support_their_second_field(self) -> None:
        for field in ("blockers", "inspected_scope"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = RuntimeFixture(directory)
                output = io.StringIO()
                value = 42 if field == "blockers" else "private-scope-result"
                with patch.object(sys, "stdin", _stdin({field: [value]})), redirect_stdout(output):
                    code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))
                self.assertNotEqual(0, code)
                self.assertIn(f"{field}[", output.getvalue())
                self.assertNotIn("private-scope-result", output.getvalue())

    def test_objective_type_error_shows_its_canonical_scalar_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            output = io.StringIO()
            with (
                patch.object(sys, "stdin", _stdin({"objective": ["private-objective"]})),
                redirect_stdout(output),
            ):
                code = agent_hook_checkpoint.checkpoint_hook(_args(fixture))
            self.assertNotEqual(0, code)
            self.assertIn("objective: one text string", output.getvalue())
            self.assertNotIn("private-objective", output.getvalue())

    def test_parser_exposes_the_provider_neutral_checkpoint_command(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "checkpoint",
                "--checkpoint-kind",
                "pre_mutation",
                "--mutation-kind",
                "update",
                "--mutation-path",
                "src/module.py",
            ]
        )

        self.assertEqual("checkpoint", parsed.hook)
        self.assertEqual(["src/module.py"], parsed.mutation_path)

    def test_parser_exposes_exact_commit_range_review_arguments(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "commit-range",
                "--review-base",
                "base-ref",
                "--review-head",
                "head-ref",
            ]
        )

        self.assertEqual("commit-range", parsed.review_scope)
        self.assertEqual("base-ref", parsed.review_base)
        self.assertEqual("head-ref", parsed.review_head)

    def test_parser_exposes_local_config_review_scope(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "local-config",
                "--review-path",
                ".codex/hooks.json",
            ]
        )

        self.assertEqual("local-config", parsed.review_scope)
        self.assertEqual([".codex/hooks.json"], parsed.review_path)

    def test_parser_exposes_repo_hygiene_review_scope_without_paths(self) -> None:
        parser = agent_hook.build_parser()
        parsed = parser.parse_args(
            [
                "review",
                "--review-scope",
                "repo-hygiene",
            ]
        )

        self.assertEqual("repo-hygiene", parsed.review_scope)
        self.assertEqual([], parsed.review_path)

    def test_invalid_repair_cycle_cli_is_rejected_before_claiming_the_attempt(self) -> None:
        scenarios = (
            ["start", "--repair-cycle", "1"],
            ["review", "--repair-cycle", "1", "--review-scope", "pathspec"],
            ["gate", "--repair-cycle", "1"],
        )

        for arguments in scenarios:
            with self.subTest(hook=arguments[0]):
                stderr = io.StringIO()
                with (
                    patch.object(sys, "argv", ["agent-hook.py", *arguments]),
                    patch.object(agent_hook, "_apply_worker_evidence_boundary", return_value=""),
                    patch.object(agent_hook, "_refresh_run_heartbeat"),
                    patch.object(agent_hook, "_apply_repair_cycle_context") as claim_attempt,
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit),
                ):
                    agent_hook.main()

                claim_attempt.assert_not_called()
                self.assertIn("error:", stderr.getvalue())

    def test_fingerprint_hook_prints_the_bound_request_fingerprint(self) -> None:
        from agent_route_state import request_fingerprint

        parser = agent_hook.build_parser()
        args = parser.parse_args(["fingerprint", "--request", "do the thing"])
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            returncode = agent_hook._fingerprint_hook(parser, args)

        expected = request_fingerprint(
            {
                "request": "do the thing",
                "continuation_scope": "",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        self.assertEqual(0, returncode)
        self.assertIn(expected, stdout.getvalue())
        self.assertIn('"request_fingerprint"', stdout.getvalue())

    def test_fingerprint_uses_the_route_effect_and_prints_git_approval_shape(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(
            ["fingerprint", "--command", "commit", "--request", "commit it"]
        )
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            returncode = agent_hook._fingerprint_hook(parser, args)

        self.assertEqual(0, returncode)
        self.assertIn('"requested_effects": ["git_write"]', stdout.getvalue())
        self.assertIn('"effect": "git_write"', stdout.getvalue())
        self.assertIn('"command": "commit"', stdout.getvalue())

    def test_compact_start_builds_bound_local_authority_without_json(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(
            [
                "start",
                "--command", "bugfix",
                "--request", "fix the parser",
                "--intent", "fix_parser",
                "--target-summary", "the parser authority input",
            ]
        )

        with patch.object(
            agent_hook,
            "runtime_session",
            return_value={"session_id": "runtime-session-01"},
        ):
            agent_hook._validate_hook_arguments_before_repair(parser, args)

        envelope = json.loads(args.intent_envelope)
        self.assertEqual("runtime-session-01", args.runtime_session_id)
        self.assertEqual(["local_write"], envelope["requested_effects"])
        self.assertEqual("fix_parser", envelope["intent"])
        self.assertEqual("", args.approval_record)

    def test_compact_git_start_builds_a_separate_bound_approval(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(
            [
                "start",
                "--command", "commit",
                "--request", "commit it",
                "--intent", "commit_change",
                "--target-summary", "the reviewed parser change",
                "--approved-effect", "git_write",
            ]
        )

        with patch.object(
            agent_hook,
            "runtime_session",
            return_value={"session_id": "runtime-session-01"},
        ):
            agent_hook._validate_hook_arguments_before_repair(parser, args)

        envelope = json.loads(args.intent_envelope)
        approval = json.loads(args.approval_record)
        self.assertEqual(["git_write"], envelope["requested_effects"])
        self.assertEqual(envelope["request_fingerprint"], approval["request_fingerprint"])
        self.assertEqual(envelope["target_summary"], approval["target_summary"])
        self.assertEqual("commit", approval["command"])

    def test_compact_git_start_refuses_to_invent_user_approval(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(
            [
                "start",
                "--command", "commit",
                "--request", "review the change",
                "--intent", "commit_change",
                "--target-summary", "the reviewed parser change",
            ]
        )

        with (
            patch.object(
                agent_hook,
                "runtime_session",
                return_value={"session_id": "runtime-session-01"},
            ),
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            agent_hook._validate_hook_arguments_before_repair(parser, args)

    def test_fingerprint_hook_binds_the_continuation_scope(self) -> None:
        """The helper must hash the same full intake the start call will bind.

        Envelopes bind to the full request intake, so a helper that hashed the
        request alone handed every terse follow-up a fingerprint its own start
        call then rejected as describing a different request -- and the agent's
        recovery was to ask the user to reword the request.
        """

        from agent_route_state import request_fingerprint

        parser = agent_hook.build_parser()
        args = parser.parse_args(
            [
                "fingerprint",
                "--request",
                "응 수정해줘",
                "--continuation-scope",
                "the previously agreed bounded target",
            ]
        )
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            returncode = agent_hook._fingerprint_hook(parser, args)

        full_intake = request_fingerprint(
            {
                "request": "응 수정해줘",
                "continuation_scope": "the previously agreed bounded target",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        request_only = request_fingerprint(
            {
                "request": "응 수정해줘",
                "continuation_scope": "",
                "request_classified": False,
                "classification_evidence": "",
            }
        )
        self.assertEqual(0, returncode)
        self.assertIn(full_intake, stdout.getvalue())
        self.assertNotIn(request_only, stdout.getvalue())
        self.assertIn("binding covers --request, --continuation-scope", stdout.getvalue())

    def test_fingerprint_hook_requires_the_request(self) -> None:
        parser = agent_hook.build_parser()
        args = parser.parse_args(["fingerprint"])

        with self.assertRaises(SystemExit):
            agent_hook._fingerprint_hook(parser, args)


if __name__ == "__main__":
    unittest.main()
