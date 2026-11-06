"""Implicit next selection must belong to exactly the current runtime session."""
import hashlib
import json
import unittest

import test_native_next_ledger as ledger_tests
from native_next_support import invoke_next
from native_pretool_support import result


class NativeNextSessionTests(unittest.TestCase):
    ledger = ledger_tests.NativeNextLedgerTests.ledger
    passed = staticmethod(ledger_tests.NativeNextLedgerTests.passed)

    def setUp(self):
        ledger_tests.NativeNextLedgerTests.setUp(self)
        self.identity = {"CODEX_THREAD_ID": "synthetic-next"}
        self.registry = self.project / ".moru/run-registry.json"

    def call(self, output="json", backend="auto", no_python=False):
        return invoke_next(self.launcher, self.base, self.project,
            ["--project", str(self.project), "--format", output], backend=backend,
            **self.identity, **({"PATH": str(self.git_only)} if no_python else {}))

    def parity(self, active, native=True):
        before = {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()}
        for output in ("json", "markdown"):
            reference = self.call(output, backend="python")
            self.assertEqual(0, reference.returncode, reference.stderr)
            if output == "json":
                self.assertEqual("active_run" if active else "no_active_run", json.loads(reference.stdout)["status"])
            self.assertEqual(result(reference), result(self.call(output)))
            actual = self.call(output, no_python=True)
            if native:
                self.assertEqual(result(reference), result(actual))
            else:
                self.assertEqual(127, actual.returncode)
        after = {p: p.read_bytes() for p in (self.project / ".moru").rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def binding(self, runtime, session="synthetic-next", generation=None):
        self.preflight["runtime_session"] = {"runtime": runtime, "session_id": session}
        if generation is not None:
            self.preflight["runtime_session"]["resume_generation"] = generation
        self.evidence.write_text(json.dumps(self.preflight))

    def add_run(self, run_id, session="foreign", runtime="codex"):
        path = self.evidence.parent.parent / run_id / "preflight.json"
        path.parent.mkdir()
        value = {**self.preflight, "agent_run_id": run_id,
                 "runtime_session": {"runtime": runtime, "session_id": session}}
        path.write_text(json.dumps(value))
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({"run_id": run_id, "state": "running", "evidence_name": path.name,
            "evidence_key": hashlib.sha256(path.relative_to(self.project).as_posix().encode()).hexdigest()})
        self.registry.write_text(json.dumps(registry))
        return path

    def test_runtime_bindings_aliases_and_cli_compatibility(self):
        for runtime, variable in (("claude", "CLAUDE_CODE_SESSION_ID"),
                                  ("codex", "CODEX_THREAD_ID"),
                                  ("antigravity", "ANTIGRAVITY_CONVERSATION_ID"),
                                  ("agy", "ANTIGRAVITY_CONVERSATION_ID"),
                                  ("cli", "CODEX_THREAD_ID")):
            with self.subTest(runtime=runtime):
                self.binding(runtime)
                self.identity = {variable: " \tsynthetic-next\u2003"}
                self.parity(True)

    def test_foreign_session_and_wrong_runtime_are_not_selected(self):
        self.binding("codex", "foreign")
        self.parity(False)
        self.binding("claude")
        self.parity(False)

    def test_runtime_environment_priority_matches_reference(self):
        self.identity = {"CLAUDE_CODE_SESSION_ID": "claude-session", "CODEX_THREAD_ID": "synthetic-next",
                         "ANTIGRAVITY_CONVERSATION_ID": "agy-session"}
        self.parity(False)
        self.binding("claude", "claude-session")
        self.parity(True)

    def test_resume_generation_must_match(self):
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["resume_generation"] = 2
        self.registry.write_text(json.dumps(registry))
        self.binding("codex", generation=1)
        self.parity(False)
        self.binding("codex", generation=2)
        self.parity(True)

    def test_latest_terminal_record_supersedes_older_active_key(self):
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({**registry["runs"][0], "state": "completed"})
        self.registry.write_text(json.dumps(registry))
        self.parity(False)

    def test_complete_foreign_candidates_do_not_hide_current_session(self):
        self.add_run("c" * 32)
        self.parity(True)
        self.ledger([self.passed(reuse_snapshot={"schema_version": 1})])
        self.parity(True)
        self.assertEqual("review", json.loads(self.call(no_python=True).stdout)["next_step"])

    def test_multiple_unowned_matching_claims_do_not_choose_newest(self):
        self.add_run("c" * 32, session="synthetic-next")
        self.parity(False)

    def test_unresolved_key_uses_reference_discovery(self):
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["evidence_key"] = "0" * 64
        self.registry.write_text(json.dumps(registry))
        self.parity(False, native=False)

    def test_nested_checkout_marker_keeps_reference_discovery(self):
        (self.evidence.parent / ".git").symlink_to("absent")
        self.parity(False, native=False)

    def test_malformed_latest_state_preserves_reference_error(self):
        original = json.loads(self.registry.read_text())
        for state in ([], {}):
            registry = {**original, "runs": [{**original["runs"][0], "state": state}]}
            self.registry.write_text(json.dumps(registry))
            reference = self.call(backend="python")
            self.assertNotEqual(0, reference.returncode)
            self.assertEqual(result(reference), result(self.call()))
            self.assertEqual(127, self.call(no_python=True).returncode)

    def test_foreign_generation_conversion_error_is_not_silently_skipped(self):
        self.add_run("c" * 32)
        registry = json.loads(self.registry.read_text())
        registry["runs"][-1]["resume_generation"] = "bad"
        self.registry.write_text(json.dumps(registry))
        reference = self.call(backend="python")
        self.assertNotEqual(0, reference.returncode)
        self.assertEqual(result(reference), result(self.call()))
        self.assertEqual(127, self.call(no_python=True).returncode)

    def test_large_generation_never_rounds_into_another_claim(self):
        generation = 2 ** 53 + 1
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["resume_generation"] = generation
        self.registry.write_text(json.dumps(registry))
        self.binding("codex", generation=generation - 1)
        self.parity(False, native=False)


if __name__ == "__main__":
    unittest.main()
