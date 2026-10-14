from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_gate_evidence import (
    CAPSULE_BINDING_FIELD,
    gate_evidence_path_for_preflight,
    read_gate_evidence_ledger,
    synthesize_gate_evidence,
)
from agent_hook_gate_records import (
    _validate_records_before_write,
    record_hook_gate_batch,
)


class GenericGateEvidenceTests(unittest.TestCase):
    def test_fields_only_release_gate_synthesizes_finish_visible_evidence(self) -> None:
        evidence, missing = synthesize_gate_evidence(
            "package",
            "",
            {
                "artifact": "universal app and dmg",
                "result": "generated",
                "verification": "package check passed",
                CAPSULE_BINDING_FIELD: "opaque-binding",
            },
        )

        self.assertEqual([], missing)
        self.assertEqual(
            "artifact=universal app and dmg; result=generated; "
            "verification=package check passed",
            evidence,
        )
        self.assertNotIn("opaque-binding", evidence)

    def test_capsule_binding_alone_does_not_create_gate_evidence(self) -> None:
        evidence, missing = synthesize_gate_evidence(
            "handoff",
            "",
            {CAPSULE_BINDING_FIELD: "opaque-binding"},
        )

        self.assertEqual([], missing)
        self.assertEqual("", evidence)

    def test_gate_write_rejects_evidence_that_finish_would_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ambiguity check", "alignment brief"],
                    "required_docs": [],
                }
            }
            records = [
                {
                    "gate": "ambiguity check",
                    "status": "SUCCESS",
                    "evidence": "Scope is clear.",
                    "fields": {},
                },
                {
                    "gate": "alignment brief",
                    "status": "SUCCESS",
                    "evidence": "User-visible alignment established.",
                    "fields": {},
                },
            ]

            with self.assertRaisesRegex(ValueError, "ambiguity check evidence"):
                _validate_records_before_write(args, preflight, records)

    def test_gate_write_accepts_finish_valid_core_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ambiguity check", "alignment brief"],
                    "required_docs": [],
                }
            }
            records = [
                {
                    "gate": "ambiguity check",
                    "status": "SUCCESS",
                    "evidence": "No blockers; scope and safe assumptions are explicit.",
                    "fields": {},
                },
                {
                    "gate": "alignment brief",
                    "status": "SUCCESS",
                    "evidence": (
                        "Shared understanding recorded; possible differences are explicit; "
                        "unsupported assumptions are none; user-visible checkpoint was "
                        "presented before edits."
                    ),
                    "fields": {},
                },
            ]

            _validate_records_before_write(args, preflight, records)

    def test_gate_write_rejects_invalid_required_grill_me_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ask blockers"],
                    "required_docs": [],
                    "request_classification": {"grill_me": True},
                }
            }
            records = [
                {
                    "gate": "ask blockers",
                    "status": "SUCCESS",
                    "evidence": "The user answered the blocker question.",
                    "fields": {},
                }
            ]

            with self.assertRaisesRegex(ValueError, "Grill-Me evidence"):
                _validate_records_before_write(args, preflight, records)

    def test_gate_write_accepts_valid_required_grill_me_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ask blockers"],
                    "required_docs": [],
                    "request_classification": {"grill_me": True},
                }
            }
            records = [
                {
                    "gate": "ask blockers",
                    "status": "SUCCESS",
                    "evidence": (
                        "Grill-Me protocol /grilling session output completed: "
                        "the user answered one blocker question and resolved the scope."
                    ),
                    "fields": {},
                }
            ]

            _validate_records_before_write(args, preflight, records)

    def test_gate_write_accepts_structured_ambiguity_and_alignment_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ambiguity check", "alignment brief"],
                    "required_docs": [],
                }
            }
            records = [
                {
                    "gate": "ambiguity check",
                    "status": "SUCCESS",
                    "fields": {
                        "blocker_status": "none",
                        "assumptions": "only reversible local wording changes",
                        "decision": "proceed",
                    },
                },
                {
                    "gate": "alignment brief",
                    "status": "SUCCESS",
                    "fields": {
                        "shared_understanding": "strengthen all failed evidence contracts",
                        "possible_differences": "keep detailed rules in owning skills",
                        "assumptions": "no product behavior changes",
                        "checkpoint": "user_visible_before_edits",
                    },
                },
            ]

            _validate_records_before_write(args, preflight, records)

    def test_gate_write_rejects_unresolved_structured_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": ["ambiguity check"],
                    "required_docs": [],
                }
            }
            records = [
                {
                    "gate": "ambiguity check",
                    "status": "SUCCESS",
                    "fields": {
                        "blocker_status": "unresolved",
                        "assumptions": "none",
                        "decision": "proceed",
                    },
                }
            ]

            with self.assertRaisesRegex(ValueError, "blocker_status"):
                _validate_records_before_write(args, preflight, records)

    def test_gate_write_reports_all_batch_contract_failures_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(project=Path(temp_dir))
            preflight = {
                "route": {
                    "gates": [
                        "source docs",
                        "ambiguity check",
                        "alignment brief",
                        "retrospective check",
                    ],
                    "required_docs": [],
                }
            }
            records = [
                {"gate": "source docs", "status": "SUCCESS", "fields": {}},
                {"gate": "ambiguity check", "status": "SUCCESS", "fields": {}},
                {"gate": "alignment brief", "status": "SUCCESS", "fields": {}},
                {
                    "gate": "retrospective check",
                    "status": "SUCCESS",
                    "fields": {
                        "skills_checked": "retrospective-learning",
                        "outcome": "guidance_updated",
                        "observation": "captured",
                    },
                },
            ]

            with self.assertRaises(ValueError) as context:
                _validate_records_before_write(args, preflight, records)

            message = str(context.exception)
            self.assertIn("source docs missing required fields", message)
            self.assertIn("ambiguity check missing required fields", message)
            self.assertIn("alignment brief missing required fields", message)
            self.assertIn("retrospective check outcome", message)
            self.assertIn("retrospective check observation", message)

    def test_source_docs_record_binds_route_manifest_before_validation_and_write(self) -> None:
        # Given a routed agent that read a non-empty required-doc manifest,
        # when it records source-doc evidence without self-declaring that
        # manifest (or with a false empty claim), then both pre-write semantic
        # validation and persistence must use the current route as authority.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            evidence_path = project / ".moru" / "preflight.json"
            evidence_path.parent.mkdir(parents=True)
            preflight = {
                "route": {
                    "gates": ["source docs"],
                    "required_docs": [
                        "AGENTS.md",
                        "common/skills/agent-operating-skill/SKILL.md",
                    ],
                }
            }
            evidence_path.write_text(json.dumps(preflight), encoding="utf-8")
            args = SimpleNamespace(project=project, evidence=evidence_path)
            records = [
                {
                    "gate": "source docs",
                    "status": "SUCCESS",
                    "evidence": "Opened the routed workflow card before edits.",
                    "fields": {
                        "required_docs": "required_docs manifest: FAKE-DOC.md",
                        "source": "workflow card",
                        "takeaway": "applied exact route-manifest binding",
                    },
                }
            ]

            entries = record_hook_gate_batch(args, records)

            self.assertEqual(
                "required_docs manifest: AGENTS.md, "
                "common/skills/agent-operating-skill/SKILL.md",
                entries[0]["fields"]["required_docs"],
            )
            self.assertNotIn("FAKE-DOC.md", entries[0]["fields"]["required_docs"])
            ledger = read_gate_evidence_ledger(
                gate_evidence_path_for_preflight(evidence_path)
            )
            self.assertEqual(
                "required_docs manifest: AGENTS.md, "
                "common/skills/agent-operating-skill/SKILL.md",
                ledger["entries"][0]["fields"]["required_docs"],
            )

if __name__ == "__main__":
    unittest.main()
