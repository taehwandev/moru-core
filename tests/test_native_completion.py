"""Native completion policy through the actual private binary protocol."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from native_pretool_support import environment, prepare
from support.completion_native import completion_native


def contract(revision=1, **overrides):
    return {"revision": revision, "items": [{"id": "r1", "outcome": "Deliver the plan", "owner": "lead",
        "gate": "tests", "artifacts": ["plan.md"], **overrides}]}


class NativeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-completion-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def raw(self, op, value, **overrides):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry), "--completion-probe", op],
            input=json.dumps(value).encode() if not isinstance(value, bytes) else value,
            env={**self.env, "PATH": str(self.empty), **overrides}, cwd=self.project, capture_output=True, timeout=10)

    def check(self, op, value):
        result = self.raw(op, value)
        self.assertEqual((0, b""), (result.returncode, result.stderr), result)
        envelope = json.loads(result.stdout)
        self.assertEqual(1, envelope["schema_version"])
        return envelope["result"]

    def test_quality_warns_without_executing_commands_or_printing_command_content(self):
        marker = self.project / "never-created"
        records = [{"gate": "tests", "status": "SUCCESS", "fields": {"check": cmd, "result": "1 test passed"}}
                   for cmd in ("echo success", "printf 'done'", "true", ":", "exit 0",
                               f"echo ok && touch {marker}", "pytest -q", "echo $OBSERVED")]
        warnings = self.check("quality", {"records": records})["warnings"]
        self.assertEqual(5, len(warnings))
        self.assertTrue(all(row == {"gate": "tests", "rule": "fixed_output_check"} for row in warnings))
        self.assertFalse(marker.exists())
        records[0]["fields"] = {"check": "pytest", "result": "0 tests; exit 0"}
        records[1]["fields"]["result"] = "5 tests; 0 failures"
        rules = [v["rule"] for v in self.check("quality", {"records": records})["warnings"]]
        self.assertEqual(1, rules.count("zero_test_count"))

    def test_requirements_revision_duplicates_and_removal_are_checked(self):
        original = contract()
        self.assertEqual([], self.check("requirements", {"current": original, "previous": None})["failures"])
        changed = contract(owner="other")
        self.assertIn("requirements_revision_must_advance", self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["revision"] = 2
        self.assertEqual([], self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["items"][0]["id"] = "r2"
        self.assertIn("requirements_cannot_disappear", self.check("requirements", {"current": changed, "previous": original})["failures"])
        for value in ({"revision": True, "items": []}, {"revision": 1, "items": []},
                      {"revision": 1, "items": original["items"] * 2}, contract(artifacts=["../outside"]),
                      contract(artifacts=[".moru/hidden"]), contract(artifacts=["plan.md", "plan.md"])):
            with self.subTest(value=value):
                self.assertTrue(self.check("requirements", {"current": value})["failures"])

    def test_coverage_observes_gate_and_actual_artifact_and_rejects_symlinks(self):
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertTrue(self.check("coverage", value)["failures"])
        (self.project / "plan.md").write_text("Delivered plan\n")
        output = self.check("coverage", value)
        self.assertEqual([], output["failures"])
        self.assertEqual(64, len(output["observations"][0]["artifacts"]["plan.md"]))
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertTrue(self.check("coverage", value)["failures"])
        value["gates"] = [{"gate": "tests", "status": "SUCCESS"}]
        value["allowed_gates"] = ["other"]
        self.assertTrue(self.check("coverage", value)["failures"])
        value["allowed_gates"] = ["tests"]
        target = self.project / "actual.md"
        (self.project / "plan.md").rename(target)
        (self.project / "plan.md").symlink_to(target)
        self.assertTrue(self.check("coverage", value)["failures"])

    def test_progress_ignores_metadata_and_order_but_resets_for_acceptance_changes(self):
        work = {"remaining_work": [{"checkpoint": "tests", "action": "Check plan"},
            {"checkpoint": "review", "action": "Review plan"}], "blockers": ["second", "first"], "requirements": contract()}
        value = {"work": work, "gates": [{"gate": "tests", "status": "FAIL", "updated_at": "one"},
                                           {"gate": "review", "status": "SUCCESS"}]}
        first = self.check("progress", value)
        for index in range(2):
            value["previous"] = first
            value["updated_at"] = str(index)
            value["work"]["generation"] = index
            value["work"]["requirements"]["revision"] += 1
            value["work"]["remaining_work"].reverse()
            value["work"]["blockers"].reverse()
            value["gates"].reverse()
            value["gates"][0]["updated_at"] = str(index)
            first = self.check("progress", value)
        self.assertTrue(first["stalled"])
        self.assertEqual(2, first["repeats"])
        value["previous"] = first
        value["gates"][0]["status"] = "SUCCESS"
        final = self.check("progress", value)
        self.assertEqual(0, final["repeats"])
        self.assertFalse(final["stalled"])

    def test_long_gate_history_preserves_latest_failure(self):
        (self.project / "plan.md").write_text("Delivered\n")
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}] * 1024}
        self.assertEqual([], self.check("coverage", value)["failures"])
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertIn("observing gate", self.check("coverage", value)["failures"][0])
        value["gates"].append({"gate": "tests", "status": "SUCCESS"})
        self.assertEqual([], self.check("coverage", value)["failures"])

    def test_artifact_limits_return_specific_failures_at_exact_boundaries(self):
        for name in ("one.bin", "two.bin"):
            with (self.project / name).open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
        value = {"current": contract(artifacts=["one.bin", "two.bin"]), "project": str(self.project),
                 "allowed_gates": ["tests"], "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertEqual([], self.check("coverage", value)["failures"])
        (self.project / "three.bin").write_bytes(b"x")
        value["current"]["items"][0]["artifacts"].append("three.bin")
        self.assertIn("32 MiB total limit", self.check("coverage", value)["failures"][0])
        with (self.project / "one.bin").open("ab") as stream:
            stream.write(b"x")
        self.assertTrue(any("16 MiB file limit" in failure for failure in self.check("coverage", value)["failures"]))
        (self.project / "one.bin").unlink()
        os.mkfifo(self.project / "one.bin")
        self.assertIn("unsafe", self.check("coverage", value)["failures"][0])

    def test_protocol_source_environment_and_python_rollback_boundaries(self):
        for op, payload in (("unknown", {}), ("quality", b"{broken"), ("quality", b" " * (1024 * 1024 + 1))):
            result = self.raw(op, payload, MORU_HOOK_SOFT_FAIL="1")
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(125, self.raw("quality", {"records": []}, PYTHONVERBOSE="1").returncode)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual({"warnings": []}, completion_native("quality", {"records": []}))
            with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertIsNone(completion_native("quality", {"records": []}))


if __name__ == "__main__":
    unittest.main()
