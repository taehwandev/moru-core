"""One plan feeds three metadata gates; it never proves worker execution."""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_collaboration_plan_records import CollaborationPlanRecords as Records
from agent_delegation_plan import delegation_plan_path, validate_delegation_plan_evidence
from agent_gate_evidence import (
    gate_evidence_path_for_preflight, reset_gate_evidence_ledger, read_gate_evidence_ledger,
    merge_gate_evidence_from_ledger,
)
from agent_hook_gate_records import gate_batch_hook
from agent_gate_record_template import remaining_gate_template_lines
from test_agent_continuation_checkpoint import initialize_git


def plan():
    return dict(schema_version=1, mode="parallel", workers=[dict(
        id="one", role="bounded builder", owned_scope=["scripts/a.py"],
        forbidden_scope=["scripts/b.py"], contract="return scoped source and checks",
        acceptance=["preserve input semantics"], verification=["run focused tests"],
    )], integration_review=dict(owner="lead", contract_drift_check="inspect actual diff",
                               final_verification=["integrated tests"]))


class PlanRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        initialize_git(self.project)
        self.path = delegation_plan_path(self.project)
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(plan()))

    def test_single_plan_projects_all_metadata_without_claiming_delivery(self):
        records = Records.build(self.project)
        self.assertEqual(list(Records.GATES), [item["gate"] for item in records])
        self.assertEqual(1, len({item["fields"]["plan_sha256"] for item in records}))
        for item in records:
            self.assertIn("one", item["evidence"])
        self.assertIn("scripts/a.py", records[1]["evidence"])
        self.assertIn("scripts/b.py", records[1]["evidence"])
        self.assertIn("delivery is not attested", records[2]["evidence"])

    def test_recorded_plan_byte_change_is_stale_even_if_still_valid(self):
        evidence = {r["gate"]: r["evidence"] for r in Records.build(self.project)}
        self.assertEqual([], Records.failures(self.project, evidence))
        self.path.write_text(self.path.read_text() + "\n")
        self.assertTrue(Records.failures(self.project, evidence))
        self.assertTrue(validate_delegation_plan_evidence(list(Records.GATES), evidence, plan(), project=self.project))

    def test_missing_and_malformed_plans_do_not_produce_records(self):
        for raw in ("{bad", "[]", "private-unreadable-value", '[' * 2000 + ']' * 2000):
            self.path.write_text(raw)
            with self.assertRaises(ValueError) as error:
                Records.build(self.project)
            self.assertNotIn("private-unreadable-value", str(error.exception))
        self.path.unlink()
        with self.assertRaises(ValueError):
            Records.build(self.project)

    def test_overlap_and_wrong_schema_fail_before_any_projection(self):
        bad = plan()
        bad["workers"].append({**copy.deepcopy(bad["workers"][0]), "id": "two"})
        self.path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "overlap"):
            Records.build(self.project)
        bad = plan()
        bad["schema_version"] = True
        self.path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "schema_version"):
            Records.build(self.project)

    def test_both_plan_readers_handle_invalid_utf8_and_parser_recursion(self):
        from agent_delegation_plan import read_delegation_plan
        self.path.write_bytes(b'\xff')
        with self.assertRaises(ValueError):
            Records.build(self.project)
        self.assertTrue(read_delegation_plan(self.project)['invalid_json'])
        self.path.write_text(json.dumps(plan()))
        with patch('agent_collaboration_plan_records.json.loads', side_effect=RecursionError):
            with self.assertRaises(ValueError):
                Records.build(self.project)
            self.assertTrue(read_delegation_plan(self.project)['invalid_json'])

    def test_hint_is_one_plan_command_instead_of_three_empty_records(self):
        lines = remaining_gate_template_lines([*Records.GATES, "tests"], [])
        text = "\n".join(lines)
        self.assertEqual(1, text.count("gate-batch --from-plan"))
        self.assertNotIn('"fields":{}', text)

    def test_macro_writes_all_three_records_through_the_real_ledger(self):
        evidence = self.path.parent / "preflight.json"
        preflight = dict(project=str(self.project), rules=str(ROOT),
                         route=dict(command="multi-agent", gates=list(Records.GATES), required_docs=[]))
        evidence.write_text(json.dumps(preflight))
        reset_gate_evidence_ledger(evidence, preflight)
        args = SimpleNamespace(project=self.project, rules=ROOT, evidence=evidence,
                               hook="gate-batch", from_plan=True, gate_record=[], gate_json=None,
                               output=None, repair_cycle=0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, gate_batch_hook(args))
        entries = read_gate_evidence_ledger(gate_evidence_path_for_preflight(evidence))["entries"]
        self.assertEqual(list(Records.GATES), [entry["gate"] for entry in entries])
        from agent_finish_check_steps import check_required_gates
        def finish_failures():
            merged, diagnostics = merge_gate_evidence_from_ledger(route=preflight['route'], evidence_path=evidence)
            self.assertEqual([], diagnostics['warnings'])
            self.assertTrue(all(merged[g].startswith(Records.PREFIX) for g in Records.GATES))
            failures = []
            check_required_gates(preflight['route'], merged, [], failures, plan(), project=self.project)
            return failures
        self.assertEqual([], finish_failures())

        self.path.write_text(self.path.read_text() + '\n')
        self.assertTrue(any('stale' in f for f in finish_failures()))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, gate_batch_hook(args))
        self.assertEqual([], finish_failures())


        args.from_plan = False
        args.gate_record = [json.dumps({'gate': 'write scopes', 'status': 'FAIL',
            'source': 'worker', 'evidence': 'observed scope drift', 'fields': {}})]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, gate_batch_hook(args))
        ledger = gate_evidence_path_for_preflight(evidence)
        before = ledger.read_bytes()
        args.from_plan, args.gate_record = True, []
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(1, gate_batch_hook(args))
        self.assertIn('cannot clear a failed', output.getvalue())
        self.assertEqual(before, ledger.read_bytes())

    def test_macro_flag_cannot_be_ignored_or_mixed_with_manual_input(self):
        from test_agent_hook_checkpoint import agent_hook

        for flags in (["verify", "--from-plan"], ["gate-batch", "--from-plan", "--template"],
                      ["gate-batch", "--from-plan", "--gate-record", "{}"]):
            with self.subTest(flags=flags), patch.object(sys, "argv", ["agent-hook.py", *flags]), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                agent_hook._parse_args(agent_hook.build_parser())
            self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
