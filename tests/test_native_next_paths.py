"""Real next path and evidence-name parity without runtime Python."""
import json
import os
from pathlib import Path
import pwd
import unittest
from unittest.mock import patch

from agent_evidence_inputs import EvidenceInputs

from agent_gate_evidence import _new_ledger, gate_evidence_path_for_preflight
from native_next_support import invoke_next
from native_pretool_support import result, environment
import test_native_next_active as active_tests


class NativeNextPathTests(unittest.TestCase):
    setUp = active_tests.NativeNextActiveTests.setUp

    def parity(self, project=None, evidence=None, **env):
        project = self.project if project is None else project
        for output in ("json", "markdown"):
            args = ["--project", str(project), "--format", output]
            if evidence is not None:
                args += ["--evidence", str(evidence)]
            reference = invoke_next(self.launcher, self.base, self.project, args,
                                    backend="python", **env)
            self.assertEqual(0, reference.returncode, reference.stderr)
            actual = invoke_next(self.launcher, self.base, self.project, args,
                                 PATH=str(self.git_only), **env)
            self.assertEqual(result(reference), result(actual))
            if output == "json":
                value = json.loads(reference.stdout)
        return value

    def test_home_aliases_preserve_lexical_launcher_and_project_resolution(self):
        home = self.base / "home"
        alias = self.base / "home-alias"
        alias.symlink_to(home, target_is_directory=True)
        (home / "project-link").symlink_to(self.project, target_is_directory=True)
        for raw_home in (str(home) + "/.", str(home) + "//", str(alias),
                         str(home / ".." / "home")):
            with self.subTest(home=raw_home):
                value = self.parity("~/project-link", self.evidence, HOME=raw_home)
                self.assertEqual(str(self.project), value["project"])
                self.assertTrue(value["copyable_command"].startswith(
                    str(Path(raw_home) / ".moru/bin/moru-hook") + " "))

    def test_project_and_evidence_links_resolve_before_selecting_sibling_ledger(self):
        alias = self.base / "project-alias"
        alias.symlink_to(self.project, target_is_directory=True)
        evidence_alias = self.base / "alias-evidence.json"
        evidence_alias.symlink_to(self.evidence)
        self.assertEqual(str(self.evidence), self.parity(alias, evidence_alias)["evidence"])

    def test_named_user_expansion_uses_passwd_home_without_writing_it(self):
        user = pwd.getpwuid(os.getuid())
        suffix = os.path.relpath(self.project, user.pw_dir)
        value = self.parity("~" + user.pw_name + "/" + suffix, self.evidence)
        self.assertEqual(str(self.project), value["project"])

    def test_hidden_and_trailing_dot_evidence_names_bind_the_correct_ledger(self):
        preflight = json.loads(self.evidence.read_text())
        for name in ("review.", "review..", "...", ".hidden", "..hidden", ".hidden.", "review.tar."):
            with self.subTest(name=name):
                evidence = self.evidence.with_name(name)
                evidence.write_text(json.dumps(preflight))
                ledger = _new_ledger(evidence, preflight)
                ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
                    "fields": {"check": "synthetic", "result": "1 passed"},
                    "reuse_snapshot": {"schema_version": 1}}]
                gate_evidence_path_for_preflight(evidence).write_text(json.dumps(ledger))
                value = self.parity(evidence=evidence)
                self.assertEqual(["review hook", "retrospective check"], value["remaining_gates"])

    def test_case_insensitive_filesystem_preserves_supplied_component_spelling(self):
        alias = self.project.with_name(self.project.name.upper())
        if not alias.exists() or alias == self.project:
            self.skipTest("filesystem is case sensitive")
        evidence = alias / self.evidence.relative_to(self.project)
        preflight = json.loads(evidence.read_text())
        ledger = _new_ledger(evidence, preflight)
        ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
            "fields": {"check": "synthetic", "result": "1 passed"},
            "reuse_snapshot": {"schema_version": 1}}]
        gate_evidence_path_for_preflight(evidence).write_text(json.dumps(ledger))
        value = self.parity(alias, evidence)
        self.assertEqual(str(alias), value["project"])
        self.assertEqual(str(evidence), value["evidence"])
        self.assertEqual(["review hook", "retrospective check"], value["remaining_gates"])
        implicit = self.parity(alias, CODEX_THREAD_ID="synthetic-next")
        self.assertEqual(str(evidence), implicit["evidence"])
        self.assertEqual(["review hook", "retrospective check"], implicit["remaining_gates"])

    def test_case_preserving_schema2_binding_expires_on_actual_content_change(self):
        alias = self.project.with_name(self.project.name.upper())
        if not alias.exists() or alias == self.project:
            self.skipTest("filesystem is case sensitive")
        evidence = alias / self.evidence.relative_to(self.project)
        selected = alias / "selected.txt"
        selected.write_text("before\n")
        preflight = json.loads(evidence.read_text())
        preflight.update(project=str(alias), rules=str(alias))
        evidence.write_text(json.dumps(preflight))
        with patch.dict(os.environ, environment(self.base), clear=True):
            snapshot = {"schema_version": 2, "project": str(alias), "rules": str(alias),
                "input_paths": ["selected.txt"], "states": {
                    "project": EvidenceInputs.capture(alias, ["selected.txt"]),
                    "rules": EvidenceInputs.capture(alias, [])}}
        ledger = _new_ledger(evidence, preflight)
        ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
            "fields": {"check": "synthetic", "result": "1 passed"}, "reuse_snapshot": snapshot}]
        gate_evidence_path_for_preflight(evidence).write_text(json.dumps(ledger))
        self.assertEqual(["review hook", "retrospective check"],
                         self.parity(alias, evidence)["remaining_gates"])
        selected.write_text("after\n")
        self.assertIn("tests", self.parity(alias, evidence)["remaining_gates"])


if __name__ == "__main__":
    unittest.main()
