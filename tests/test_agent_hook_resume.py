"""The resume hook is the only way a session reaches a continuation packet."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_hook = _load_script("agent_hook_resume_test", "agent-hook.py")

from agent_continuation_store import continuation_path
from agent_continuation_resume import resume_references
from agent_continuation_packet import validate_continuation_packet
from agent_continuation_outbound import assert_no_continuation_outbound
from agent_run_registry import evidence_binding_key, registry_path
from agent_runtime_session import resolve_runtime_evidence
from test_agent_continuation_checkpoint import Fixture
from test_agent_continuation_claim import dead_pid
from test_agent_continuation_resume import age, free_fixture


def run_resume(project: Path, rules: Path, mode: str, *extra: str) -> tuple[int, str]:
    argv = [
        "agent-hook.py",
        "resume",
        mode,
        "--project",
        str(project),
        "--rules",
        str(rules),
        *extra,
    ]
    output = io.StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.dict("os.environ", {}, clear=True),
        redirect_stdout(output),
    ):
        code = agent_hook.main()
    return code, output.getvalue()


def project_bytes(project: Path) -> dict[str, bytes]:
    """Snapshot everything `--list` promises not to touch."""

    project = project.resolve()
    tracked = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".moru" not in path.relative_to(project).parts
    }
    for path in (
        registry_path(project),
        *sorted((project / ".moru" / "runs").rglob("continuation.json")),
        *sorted((project / ".moru" / "runs").rglob("gate-evidence.json")),
    ):
        if path.is_file():
            tracked[path.relative_to(project).as_posix()] = path.read_bytes()
    return tracked


class ListTests(unittest.TestCase):
    def test_the_listing_reports_the_packet_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "finish the lifecycle wiring")

            code, output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertIn("SUCCESS resume", output)
            self.assertIn("unfinished continuation packets: 1", output)
            self.assertIn(fixture.run_id, output)
            self.assertIn("finish the lifecycle wiring", output)
            self.assertIn("checkpoint=scope", output)

    def test_the_listing_changes_no_registry_packet_ledger_or_worktree_byte(self) -> None:
        """Discovery that mutates is not discovery; it is an unannounced claim.

        The heartbeat every other post-start hook writes would be enough to
        break this, which is why `resume` is excluded from it.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "list must not claim anything")
            fixture.gate("scope")
            before = project_bytes(fixture.project)

            code, _output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertEqual(before, project_bytes(fixture.project))
            self.assertGreaterEqual(len(before), 3)

    def test_packets_the_registry_no_longer_records_are_counted_not_hidden(self) -> None:
        """Withdrawing candidacy is not the same as pretending they are gone."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "the run still on record")
            dropped = free_fixture(
                directory, "a dropped run", project=fixture.project, rules=fixture.rules
            )
            path = registry_path(fixture.project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runs"] = [
                run for run in payload["runs"] if run["run_id"] != dropped.run_id
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")

            code, output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertIn("unfinished continuation packets: 1", output)
            self.assertIn("the registry no longer records: 1", output)
            self.assertIn("cannot be claimed", output)
            self.assertNotIn(dropped.run_id, output)

    def test_an_invalid_packet_is_listed_without_rendering_its_prose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "prose that must never be rendered")
            path = continuation_path(fixture.project, fixture.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["notes"] = "a transcript"
            path.write_text(json.dumps(payload), encoding="utf-8")

            code, output = run_resume(fixture.project, fixture.rules, "--list")

            self.assertEqual(0, code)
            self.assertIn("status=invalid_packet", output)
            self.assertNotIn("prose that must never be rendered", output)


class LastTests(unittest.TestCase):
    def test_the_newest_free_packet_is_claimed_and_reported_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "resume the wiring after a crash")

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(0, code)
            self.assertIn("SUCCESS resume", output)
            self.assertIn("resume result: ready", output)
            self.assertIn("resume checkpoint: scope", output)
            self.assertIn("objective: resume the wiring after a crash", output)
            self.assertIn(str(fixture.binding_path), output)

    def test_a_blocked_newest_packet_is_refused_and_no_older_one_is_offered(self) -> None:
        """The caller asking for the last thing they were doing has the least
        context in which to notice they were handed something else."""

        with tempfile.TemporaryDirectory() as directory:
            older = free_fixture(directory, "an older task that must not be resumed")
            newer = Fixture(directory, project=older.project, rules=older.rules)
            newer.checkpoint("initial", work={"objective": "the newest task, still held"})
            age(newer, minutes=0, owner_pid=1, run_id=newer.run_id)
            before = json.loads(registry_path(older.project).read_text(encoding="utf-8"))

            code, output = run_resume(older.project, older.rules, "--last")

            self.assertEqual(1, code)
            self.assertIn("FAIL resume", output)
            self.assertIn("resume result: live_owner_refused", output)
            self.assertIn(newer.run_id, output)
            self.assertNotIn(older.run_id, output)
            self.assertNotIn("an older task that must not be resumed", output)
            self.assertEqual(before, json.loads(registry_path(older.project).read_text(encoding="utf-8")))

    def test_a_refusal_renders_no_semantic_work_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "prose behind an invalid packet")
            path = continuation_path(fixture.project, fixture.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["work"]["objective"] = "x" * 400
            path.write_text(json.dumps(payload), encoding="utf-8")

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(1, code)
            self.assertIn("resume result: invalid_packet", output)
            self.assertNotIn("x" * 300, output)

    def test_an_empty_checkout_refuses_instead_of_inventing_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()

            code, output = run_resume(project, project, "--last")

            self.assertEqual(1, code)
            self.assertIn("resume result: not_found", output)
            self.assertIn("start a fresh run", output)


class RecordedSessionSurvivesTheClaimTests(unittest.TestCase):
    """A claim that renames nobody must not un-name the session it had."""

    def _stamped_fixture(self, directory: str, objective: str, session: dict) -> Fixture:
        """A free run whose evidence carries a session, as `start` writes it.

        The stamp goes in before the first checkpoint: the packet binds to the
        evidence bytes, so editing them afterwards is a moved binding and the
        claim refuses the packet instead of reaching the question under test.

        The registry key is moved onto the run directory too. `start` registers
        the run against the evidence file it actually writes, and session
        resolution is keyed on that; the shared fixture registers the default
        path instead, which resolves to no run at all.
        """

        fixture = Fixture(directory)
        payload = json.loads(fixture.binding_path.read_text(encoding="utf-8"))
        payload["runtime_session"] = dict(session)
        fixture.preflight = payload
        fixture.binding_path.write_text(json.dumps(payload), encoding="utf-8")
        registry = registry_path(fixture.project)
        recorded = json.loads(registry.read_text(encoding="utf-8"))
        for run in recorded["runs"]:
            if run["run_id"] == fixture.run_id:
                run["evidence_key"] = evidence_binding_key(
                    fixture.project, fixture.binding_path
                )
        registry.write_text(json.dumps(recorded), encoding="utf-8")
        fixture.checkpoint("initial", work={"objective": objective})
        age(fixture, minutes=0, owner_pid=dead_pid(), run_id=fixture.run_id)
        return fixture

    def test_resume_without_runtime_flags_keeps_the_run_resolvable(self) -> None:
        """`resume --last` alone used to make the run unfindable for good.

        The claim advances the registry's `resume_generation`; the binding in
        the evidence still named the generation it was stamped at, and the
        matcher compares the two. Nothing rebound it, so every later hook and
        the pre-tool gate stopped resolving the run -- and `finish` then
        settled it, which left no call able to repair the binding. The
        post-finish `git add` the finished-work allowance exists to permit was
        the first thing to notice.
        """

        session = {"runtime": "claude", "session_id": "9035e9f5-resume"}
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._stamped_fixture(
                directory, "the run that must stay findable", session
            )

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(0, code)
            self.assertIn("resume result: ready", output)
            self.assertIn("resume generation: 1", output)
            bound = json.loads(fixture.binding_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {**session, "resume_generation": 1}, bound["runtime_session"]
            )
            self.assertEqual(
                fixture.binding_path.resolve(),
                resolve_runtime_evidence(fixture.project, session),
            )

    def test_a_claim_with_no_recorded_session_is_still_ready(self) -> None:
        """Evidence written before session binding existed has none to carry."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "evidence with no session stamp")

            code, output = run_resume(fixture.project, fixture.rules, "--last")

            self.assertEqual(0, code)
            self.assertIn("resume result: ready", output)
            self.assertNotIn(
                "runtime_session",
                json.loads(fixture.binding_path.read_text(encoding="utf-8")),
            )

    def test_naming_one_flag_still_refuses_instead_of_reusing_the_record(self) -> None:
        """Half a new binding is a caller error, not a request to keep the old one."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = self._stamped_fixture(
                directory,
                "a half-named rebinding",
                {"runtime": "claude", "session_id": "the-recorded-session"},
            )

            code, output = run_resume(
                fixture.project, fixture.rules, "--last", "--runtime", "claude"
            )

            self.assertEqual(1, code)
            self.assertIn("resume result: runtime_binding_refused", output)


class NamedRunTests(unittest.TestCase):
    """Several sessions share one checkout, so the newest slot is not mine."""

    def test_naming_a_run_claims_it_while_another_session_holds_the_newest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "the task this session left behind")
            newer = Fixture(directory, project=mine.project, rules=mine.rules)
            newer.checkpoint("initial", work={"objective": "another session, still running"})
            age(newer, minutes=0, owner_pid=1, run_id=newer.run_id)

            blocked, _ = run_resume(mine.project, mine.rules, "--last")
            code, output = run_resume(mine.project, mine.rules, "--last", "--run-id", mine.run_id)

            self.assertEqual(1, blocked)
            self.assertEqual(0, code)
            self.assertIn("resume result: ready", output)
            self.assertIn(f"run: {mine.run_id}", output)
            self.assertIn("objective: the task this session left behind", output)
            self.assertNotIn("another session, still running", output)

    def test_a_run_id_alone_claims_that_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "the run named without --last")

            code, output = run_resume(
                fixture.project, fixture.rules, f"--run-id={fixture.run_id}"
            )

            self.assertEqual(0, code)
            self.assertIn("resume result: ready", output)
            self.assertIn(f"run: {fixture.run_id}", output)

    def test_naming_a_run_that_is_not_unfinished_claims_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "a task that must not be handed over")
            before = json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))

            code, output = run_resume(fixture.project, fixture.rules, "--last", "--run-id", "0" * 32)

            self.assertEqual(1, code)
            self.assertIn("resume result: not_found", output)
            self.assertIn("refusal reason: run_id_not_unfinished", output)
            self.assertNotIn("a task that must not be handed over", output)
            self.assertEqual(
                before, json.loads(registry_path(fixture.project).read_text(encoding="utf-8"))
            )

    def test_a_mistyped_run_id_is_not_reported_as_an_empty_checkout(self) -> None:
        """The advice has to match which of the two `not_found` cases happened.

        A checkout with nothing to resume needs a fresh start. A run id that
        matches none of several unfinished packets needs the listing -- telling
        that caller there is nothing here contradicts what `--list` shows.
        """

        with tempfile.TemporaryDirectory() as directory:
            fixture = free_fixture(directory, "one of several unfinished packets")
            free_fixture(directory, "another", project=fixture.project, rules=fixture.rules)

            _code, output = run_resume(
                fixture.project, fixture.rules, "--last", "--run-id", "0" * 32
            )

            self.assertIn("--list", output)
            self.assertNotIn("no unfinished continuation packet for this checkout", output)

    def test_a_refusal_names_the_targeted_packet_not_the_newest(self) -> None:
        """Guidance that says "the newest" describes a packet nobody asked about."""

        with tempfile.TemporaryDirectory() as directory:
            mine = free_fixture(directory, "this session's own task")
            held = Fixture(directory, project=mine.project, rules=mine.rules)
            held.checkpoint("initial", work={"objective": "a second session's task"})
            age(held, minutes=0, owner_pid=1, run_id=held.run_id)
            newest = Fixture(directory, project=mine.project, rules=mine.rules)
            newest.checkpoint("initial", work={"objective": "a third session's task"})
            age(newest, minutes=0, owner_pid=1, run_id=newest.run_id)

            _code, output = run_resume(
                mine.project, mine.rules, "--last", "--run-id", held.run_id
            )

            self.assertIn("resume result: live_owner_refused", output)
            self.assertIn(f"run: {held.run_id}", output)
            self.assertNotIn(newest.run_id, output)
            self.assertNotIn("newest", output)


class ModeTests(unittest.TestCase):
    def test_a_run_id_is_rejected_for_the_listing_it_cannot_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            argv = [
                "agent-hook.py",
                "resume",
                "--list",
                "--run-id",
                "0" * 32,
                "--project",
                str(project),
                "--rules",
                str(project),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.dict("os.environ", {}, clear=True),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    agent_hook.main()
            self.assertEqual(2, raised.exception.code)

    def test_exactly_one_mode_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for flags in ([], ["--list", "--last"]):
                argv = [
                    "agent-hook.py",
                    "resume",
                    "--project",
                    str(project),
                    "--rules",
                    str(project),
                    *flags,
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.dict("os.environ", {}, clear=True),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        agent_hook.main()
                self.assertEqual(2, raised.exception.code)


class EvidenceReferenceTests(unittest.TestCase):
    def _fixture(self, directory):
        fixture = Fixture(directory)
        fixture.preflight["request_intake"] = {
            **fixture.preflight["request_intake"], "request": "ORIGINAL_INTAKE_NOT_FOR_AUTOMATIC_INJECTION",
        }
        fixture.binding_path.write_text(json.dumps(fixture.preflight))
        report = (Path(directory) / "external-report.json").resolve()
        report.write_text('{"result": "do not inject this report body"}')
        reference = {
            "id": "experiment", "path": str(report),
            "sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            "status": "contradicted", "summary": "Measured results require reconciliation",
        }
        fixture.checkpoint("initial", work={
            "objective": "compare prior evidence", "non_goals": ["Do not change the report"],
            "decisions": [{"id": "scope", "status": "accepted", "text": "Keep native compaction"}],
            "acceptance_criteria": ["Find the original experiment without injecting its body"],
            "evidence_refs": [reference],
        })
        return fixture, report, reference

    def test_cli_recovers_external_pointer_without_claim_or_content_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, report, _ref = self._fixture(directory)
            before = project_bytes(fixture.project)
            code, output = run_resume(fixture.project, fixture.rules, "--references",
                                      "--run-id", fixture.run_id)
            self.assertEqual(0, code, output)
            self.assertIn(str(report), output)
            self.assertIn("unchecked", output)
            self.assertIn("contradicted", output)
            self.assertNotIn("do not inject this report body", output)
            self.assertEqual(before, project_bytes(fixture.project))

    def test_cli_explicitly_reports_changed_and_missing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, report, _ref = self._fixture(directory)
            for content, expected in (("changed", "changed"), (None, "missing")):
                if content is None:
                    report.unlink()
                else:
                    report.write_text(content)
                code, output = run_resume(fixture.project, fixture.rules, "--references",
                                          "--run-id", fixture.run_id, "--check-files")
                self.assertEqual(0, code, output)
                self.assertIn(expected, output)

    def test_completed_drifted_work_is_discoverable_but_never_current_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            registry = registry_path(fixture.project)
            data = json.loads(registry.read_text())
            data["runs"][0]["state"] = "completed"
            registry.write_text(json.dumps(data))
            (fixture.project / "src/module.py").write_text("value = 2\n")
            before = project_bytes(fixture.project)
            result = resume_references(fixture.project, fixture.run_id, check_files=True)
            self.assertEqual("ok", result["result"])
            self.assertEqual("match", result["references"][0]["freshness"])
            self.assertEqual("unchecked", result["context_validity"])
            self.assertFalse(result["verification_reuse"])
            self.assertNotIn("work", result)
            with self.assertRaises(ValueError):
                assert_no_continuation_outbound(result, boundary="export")
            self.assertEqual(before, project_bytes(fixture.project))

    def test_checkpoint_updates_preserve_pointers_and_legacy_packets_still_read(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, reference = self._fixture(directory)
            fixture.checkpoint("decision", work={"blockers": ["check current applicability"]})
            packet = fixture.packet()
            self.assertEqual([reference], packet["work"]["evidence_refs"])
            self.assertEqual([], validate_continuation_packet(packet))
            del packet["work"]["evidence_refs"]
            self.assertEqual([], validate_continuation_packet(packet))
            packet["work"]["evidence_refs"] = 42
            self.assertTrue(validate_continuation_packet(packet))

    def test_discovery_does_not_weaken_drift_refusal_or_claim_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            age(fixture, minutes=90, owner_pid=dead_pid())
            (fixture.project / "src/module.py").write_text("value = 3\n")
            before = project_bytes(fixture.project)
            self.assertEqual("ok", resume_references(fixture.project, fixture.run_id)["result"])
            self.assertEqual(before, project_bytes(fixture.project))
            code, output = run_resume(fixture.project, fixture.rules, "--last",
                                      "--run-id", fixture.run_id)
            self.assertNotEqual(0, code)
            self.assertIn("drift_refused", output)
            self.assertEqual("ok", resume_references(fixture.project, fixture.run_id)["result"])

    def test_invalid_binding_and_unknown_run_do_not_expose_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            fixture.binding_path.write_text("{}")
            self.assertEqual([], resume_references(fixture.project, fixture.run_id)["references"])
            self.assertEqual("invalid_binding", resume_references(fixture.project, fixture.run_id)["result"])
            self.assertEqual("not_found", resume_references(fixture.project, "0" * 32)["result"])
            self.assertEqual("invalid_run_id", resume_references(fixture.project, "../other")["result"])

    def test_normal_resume_names_retained_references_without_reading_their_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            age(fixture, minutes=90, owner_pid=dead_pid())
            code, output = run_resume(fixture.project, fixture.rules, "--last",
                                      "--run-id", fixture.run_id)
            self.assertEqual(0, code, output)
            self.assertIn("retained evidence references: 1", output)
            self.assertIn("resume --context --run-id", output)
            self.assertNotIn("do not inject this report body", output)

    def test_reference_mode_rejects_claim_flags_and_requires_exact_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            cases = ((), ("--last",), ("--list",), ("--runtime", "codex"))
            for extra in cases:
                flags = [] if not extra else ["--run-id", fixture.run_id, *extra]
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    run_resume(fixture.project, fixture.rules, "--references", *flags)
                self.assertEqual(2, raised.exception.code)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_resume(fixture.project, fixture.rules, "--list", "--check-files")

    def test_fresh_process_recovers_requirements_and_intake_pointer_after_context_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, report, _ref = self._fixture(directory)
            before = project_bytes(fixture.project)
            completed = subprocess.run([
                sys.executable, str(SCRIPTS / "agent-hook.py"), "resume", "--context",
                "--project", str(fixture.project), "--rules", str(fixture.rules),
                "--run-id", fixture.run_id,
            ], capture_output=True, text=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            self.assertIn("Do not change the report", completed.stdout)
            self.assertIn("Keep native compaction", completed.stdout)
            self.assertIn("Find the original experiment", completed.stdout)
            self.assertIn(str(fixture.binding_path), completed.stdout)
            self.assertIn(str(report), completed.stdout)
            self.assertNotIn("ORIGINAL_INTAKE_NOT_FOR_AUTOMATIC_INJECTION", completed.stdout)
            self.assertEqual(before, project_bytes(fixture.project))

    def test_requirement_limits_fail_closed_and_explicit_revisions_replace_prior_criteria(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _report, _ref = self._fixture(directory)
            packet = fixture.packet()
            for invalid in (42, ["x" * 161], ["criterion"] * 9):
                packet["work"]["acceptance_criteria"] = invalid
                self.assertTrue(validate_continuation_packet(packet))
            fixture.checkpoint("decision", work={"acceptance_criteria": ["Revised by current request"]})
            result = resume_references(fixture.project, fixture.run_id)
            self.assertEqual(["Revised by current request"], result["work_contract"]["acceptance_criteria"])
            self.assertEqual("recorded", result["requirements_status"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_corrupt_special_and_oversized_bindings_refuse_without_hanging(self):
        for corrupt in ("binding_fifo", "packet_fifo", "oversized_binding"):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                fixture, _report, _ref = self._fixture(directory)
                target = (continuation_path(fixture.project, fixture.run_id)
                          if corrupt == "packet_fifo" else fixture.binding_path)
                target.unlink()
                if corrupt == "oversized_binding":
                    target.write_bytes(b" " * (8 * 1024 * 1024 + 1))
                else:
                    os.mkfifo(target, 0o600)
                completed = subprocess.run([
                    sys.executable, str(SCRIPTS / "agent-hook.py"), "resume", "--context",
                    "--project", str(fixture.project), "--rules", str(fixture.rules),
                    "--run-id", fixture.run_id,
                ], capture_output=True, text=True, timeout=3, check=False)
                self.assertNotEqual(0, completed.returncode)
                self.assertIn("lookup refused", completed.stdout)
                self.assertNotIn("compare prior evidence", completed.stdout)


if __name__ == "__main__":
    unittest.main()
