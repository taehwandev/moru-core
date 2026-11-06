"""Recorded-gate advice must honor binding, later failures and field validity."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_gate_evidence import _new_ledger
from native_next_support import invoke_next, prepare_next, seed
from native_pretool_support import result


class NativeNextLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-next-ledger-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare_next(self.base)
        self.evidence = seed(self.project, "running")
        self.preflight = json.loads(self.evidence.read_text())
        self.ledger_path = self.evidence.with_name("gate-evidence.json")
        self.git_only = self.base / "git-only"
        self.git_only.mkdir()
        (self.git_only / "git").symlink_to(shutil.which("git"))

    def call(self, output="json", backend="auto", no_python=False):
        return invoke_next(self.launcher, self.base, self.project,
            ["--project", str(self.project), "--evidence", str(self.evidence), "--format", output],
            backend=backend, **({"PATH": str(self.git_only)} if no_python else {}))

    def ledger(self, entries, **changes):
        self.evidence.write_text(json.dumps(self.preflight))
        ledger = {**_new_ledger(self.evidence, self.preflight), "entries": entries, **changes}
        self.ledger_path.write_text(json.dumps(ledger))

    def parity(self, expected, native=True):
        before = {p: p.read_bytes() for p in (self.evidence, self.ledger_path)}
        for output in ("json", "markdown"):
            reference = self.call(output, backend="python")
            self.assertEqual(0, reference.returncode, reference.stderr)
            if output == "json":
                self.assertEqual(expected, json.loads(reference.stdout)["remaining_gates"])
            self.assertEqual(result(reference), result(self.call(output)))
            actual = self.call(output, no_python=True)
            if native:
                self.assertEqual(result(reference), result(actual))
            else:
                self.assertEqual(127, actual.returncode)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    @staticmethod
    def passed(gate="tests", **extra):
        return {"gate": gate, "status": "SUCCESS", "evidence": "", "fields": {
            "check": "focused tests", "result": "1 passed"}, **extra}

    def test_recorded_successes_advance_review_closeout_and_finish(self):
        entries = [self.passed(reuse_snapshot={"schema_version": 1})]
        self.ledger(entries)
        self.parity(["review hook", "retrospective check"])
        entries.append(self.passed("review hook", evidence="review passed"))
        self.ledger(entries)
        self.parity(["retrospective check"])
        entries.append(self.passed("retrospective check", fields={"skills_checked": "testing",
            "outcome": "no_reusable_gap", "observation": "not_needed"}))
        self.ledger(entries)
        self.parity([])

    def test_latest_failure_invalid_status_and_incomplete_success_revoke_success(self):
        for latest in (self.passed(status="FAIL"), self.passed(status="unknown"),
                       self.passed(fields={"check": "only check"}), self.passed(fields={})):
            with self.subTest(latest=latest):
                self.ledger([self.passed(), latest])
                self.parity(self.preflight["route"]["gates"])
        self.ledger([self.passed(status="FAIL"), self.passed()])
        self.parity(["review hook", "retrospective check"])

    def test_stale_binding_cannot_remove_required_gates(self):
        (self.base / "other.json").write_text("{}")
        for changes in ({"preflight_evidence_sha256": "0" * 64},
                        {"route_fingerprint": "0" * 64}, {"schema_version": 2},
                        {"preflight_evidence": str(self.base / "other.json")}):
            with self.subTest(changes=changes):
                self.ledger([self.passed()], **changes)
                self.parity(self.preflight["route"]["gates"])

    def test_content_scoped_snapshot_does_not_bypass_freshness(self):
        self.ledger([self.passed(reuse_snapshot={"schema_version": 2})])
        self.parity(self.preflight["route"]["gates"], native=False)

    def test_nonexistent_path_component_does_not_falsely_invalidate_binding(self):
        recorded = str(self.evidence.parent / "absent" / ".." / self.evidence.name)
        self.ledger([self.passed()], preflight_evidence=recorded)
        self.parity(["review hook", "retrospective check"], native=False)

    def test_symlink_target_with_missing_parent_preserves_reference_binding(self):
        alias = self.evidence.with_name("alias")
        alias.symlink_to("absent/../preflight.json")
        self.ledger([self.passed()], preflight_evidence=str(alias))
        self.parity(["review hook", "retrospective check"], native=False)

    def test_surface_verification_trailing_whitespace_cannot_hide_unknown_value(self):
        self.preflight["route"]["gates"] = ["work surface resolution"]
        fields = {"result": "resolved", "owner": "scripts/owner.py", "anchors": "src",
            "evidence": "src -> scripts/owner.py", "surface_paths": "scripts/owner.py",
            "concerns": "none", "search_hops": "1", "verification": "unknown\t"}
        self.ledger([self.passed("work surface resolution", fields=fields)])
        self.parity(["work surface resolution"])

    def test_route_projection_binds_nested_contract_and_organization(self):
        from agent_route_state import preflight_evidence_sha256
        route = self.preflight["route"]
        route.update(lifecycle_version=3,
            project_memory_contract={"enabled": True, "version": 2, "scope": ["한글"]},
            organization={"id": "synthetic", "commit": "abc", "ignored_metadata": "original",
                          "required_docs": [{"path": "rules/한글.md", "sha256": "a" * 64}]})
        self.ledger([self.passed()])
        self.parity(["review hook", "retrospective check"])
        for key, value, expected in (
            ("ignored_metadata", "changed", ["review hook", "retrospective check"]),
            ("commit", "different", route["gates"])):
            route["organization"][key] = value
            self.evidence.write_text(json.dumps(self.preflight))
            ledger = json.loads(self.ledger_path.read_text())
            ledger["preflight_evidence_sha256"] = preflight_evidence_sha256(self.evidence)
            self.ledger_path.write_text(json.dumps(ledger))
            self.parity(expected)

    def test_generic_evidence_truthiness_and_capsule_only_fields(self):
        self.preflight["route"]["gates"] = ["custom gate"]
        for entry, expected in (
            (self.passed("custom gate", evidence="   ", fields={}), []),
            (self.passed("custom gate", fields={"execution_capsule_binding": "binding"}), ["custom gate"]),
            (self.passed("custom gate", fields={"detail": "observed"}), [])):
            with self.subTest(entry=entry):
                self.ledger([entry])
                self.parity(expected)

    def test_structured_gate_requirements_use_canonical_acceptance(self):
        from agent_gate_evidence import FIELD_REQUIREMENTS, merge_gate_evidence_from_ledger
        self.preflight["route"]["gates"] = list(FIELD_REQUIREMENTS)
        entries = [self.passed(gate, fields={key: "synthetic" for key in required})
                   for gate, required in FIELD_REQUIREMENTS.items()]
        self.ledger(entries)
        accepted, _ = merge_gate_evidence_from_ledger(route=self.preflight["route"], evidence_path=self.evidence)
        expected = [entry["gate"] for entry in entries if entry["gate"] not in accepted]
        self.parity(expected)


if __name__ == "__main__":
    unittest.main()
