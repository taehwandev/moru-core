"""Content-scoped gate evidence expires on actual selected-input changes."""
import os
import hashlib
import subprocess
from unittest import mock
import unittest

from agent_evidence_inputs import EvidenceInputs
from native_pretool_support import environment
import test_native_next_ledger as ledger_tests


class NativeNextFreshnessTests(unittest.TestCase):
    call = ledger_tests.NativeNextLedgerTests.call
    ledger = ledger_tests.NativeNextLedgerTests.ledger
    parity = ledger_tests.NativeNextLedgerTests.parity
    passed = staticmethod(ledger_tests.NativeNextLedgerTests.passed)

    def setUp(self):
        ledger_tests.NativeNextLedgerTests.setUp(self)
        self.rules = self.base / "rules"
        self.rules.mkdir()
        subprocess.run(["git", "init", "-q", str(self.rules)], check=True,
                       env=environment(self.base), capture_output=True)
        (self.rules / "guide.txt").write_text("synthetic rules\n")
        self.preflight.update(project=str(self.project), rules=str(self.rules))
        self.selected = self.project / "selected.txt"
        self.selected.write_text("original\n")

    def snapshot(self, paths=None):
        paths = ["selected.txt"] if paths is None else paths
        with mock.patch.dict(os.environ, environment(self.base), clear=True):
            return {"schema_version": 2, "project": str(self.project), "rules": str(self.rules),
                "input_paths": paths, "states": {
                    "project": EvidenceInputs.capture(self.project, paths),
                    "rules": EvidenceInputs.capture(self.rules, [])}}

    def record(self, paths=None):
        snapshot = self.snapshot(paths)
        self.ledger([self.passed(reuse_snapshot=snapshot)])

    def check(self, fresh, native=True):
        expected = ["review hook", "retrospective check"] if fresh else self.preflight["route"]["gates"]
        self.parity(expected, native=native)

    def test_selected_content_changes_but_unrelated_changes_do_not_expire_evidence(self):
        self.record()
        self.check(True)
        (self.project / "unrelated.txt").write_text("unselected\n")
        self.check(True)
        self.selected.write_text("changed\n")
        self.check(False)
        self.selected.write_text("original\n")
        self.check(True)

    def test_rule_files_and_selected_permissions_are_covered(self):
        self.record()
        self.selected.chmod(0o755)
        self.check(False)
        self.record()
        (self.rules / "guide.txt").write_text("changed rules\n")
        self.check(False)

    def test_explicit_absence_differs_from_empty_file(self):
        self.record(["missing.txt", "selected.txt", "selected.txt"])
        self.check(True)
        (self.project / "missing.txt").touch()
        self.check(False)
        (self.project / "missing.txt").unlink()
        self.check(True)

    def test_all_files_tracks_untracked_inputs_but_not_ignored_files(self):
        (self.project / ".gitignore").write_text("ignored.txt\n")
        self.record([])
        self.check(True)
        (self.project / "ignored.txt").write_text("ignored\n")
        self.check(True)
        (self.project / "new-input.txt").write_text("new\n")
        self.check(False)

    def test_symlinks_hash_targets_without_reading_referent_contents(self):
        target = self.base / "target-雪😀.txt"
        target.write_text("outside initial\n")
        link = self.project / "link-雪😀"
        link.symlink_to(target)
        self.record([link.name])
        self.check(True)
        target.write_text("outside changed\n")
        self.check(True)
        link.unlink()
        link.symlink_to(self.base / "missing-target")
        self.check(False)

    def test_raw_git_paths_and_default_json_unicode_escaping_match(self):
        (self.rules / "line\r\n雪😀.txt").write_text("unicode path\n")
        self.record()
        self.check(True)
        (self.rules / "line\r\n雪😀.txt").write_text("changed\n")
        self.check(False)

    def test_invalid_input_scope_cannot_reuse_success(self):
        snapshot = self.snapshot()
        for paths in (["../outside"], [".git/config"], [str(self.selected)], [""], ["selected.txt"] * 5001):
            with self.subTest(paths=paths[:2]):
                self.ledger([self.passed(reuse_snapshot={**snapshot, "input_paths": paths})])
                self.check(False)

    def test_parent_symlink_cannot_hide_changed_selected_content(self):
        directory = self.project / "directory"
        directory.mkdir()
        (directory / "input.txt").write_text("original")
        self.record(["directory/input.txt"])
        (directory / "input.txt").unlink()
        directory.rmdir()
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "input.txt").write_text("original")
        directory.symlink_to(outside, target_is_directory=True)
        self.check(False)

    def test_oversized_or_nonregular_inputs_are_rejected_before_reading(self):
        self.record()
        with self.selected.open("wb") as stream:
            stream.truncate(256 * 1024 * 1024 + 1)
        self.check(False)
        self.selected.unlink()
        os.mkfifo(self.selected)
        self.check(False)

    def test_relative_empty_roots_follow_python_path_normalization(self):
        for name in ("relative-project", "relative-rules"):
            target = self.project / name
            target.mkdir()
            subprocess.run(["git", "init", "-q", str(target)], check=True,
                           env=environment(self.base), capture_output=True)
        self.preflight.update(project="./relative-project", rules="./relative-rules")
        empty = hashlib.sha256(b"").hexdigest()
        value = {"schema_version": 2, "project": "relative-project", "rules": "relative-rules",
                 "input_paths": [], "states": {"project": empty, "rules": empty}}
        self.ledger([self.passed(reuse_snapshot=value)])
        self.check(True)


if __name__ == "__main__":
    unittest.main()
