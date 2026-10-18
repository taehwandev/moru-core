from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_loop_inputs import LoopInputs


class LoopInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve() / "project"
        self.project.mkdir()
        for name, value in {
            "owned.txt": "owned\n", "outside.txt": "outside\n",
            "verify.py": "# frozen verifier\n", ".gitignore": ".moru/\nignored/\n",
        }.items():
            (self.project / name).write_text(value, encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.name", "Loop Input Tests")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("add", ".")
        self._git("commit", "-qm", "initial")
        self.inputs = LoopInputs(self.project, ["owned.txt"], ["verify.py"])

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.project, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_snapshot_fields_and_owned_mutation(self) -> None:
        accepted = self.inputs.capture()
        (self.project / "owned.txt").write_text("changed\n", encoding="utf-8")
        current = self.inputs.capture()
        self.assertEqual(set(current), {"head", "index", "outside", "owned", "verifiers"})
        self.inputs.assert_scope(current, accepted)
        with self.assertRaisesRegex(ValueError, "restore"):
            self.inputs.assert_restored(current, accepted)

    def test_nonowned_and_verifier_content_drift_is_refused(self) -> None:
        for name in ("outside.txt", "verify.py"):
            with self.subTest(name=name):
                target = self.project / name
                original = target.read_bytes()
                accepted = self.inputs.capture()
                target.write_bytes(b"changed\n")
                with self.assertRaises(ValueError):
                    self.inputs.assert_scope(self.inputs.capture(), accepted)
                target.write_bytes(original)
                self.inputs.assert_restored(self.inputs.capture(), accepted)

    def test_untracked_changes_and_removal_are_detected(self) -> None:
        target = self.project / "local.txt"
        target.write_text("before\n", encoding="utf-8")
        accepted = self.inputs.capture()
        for value in (b"after\n", None):
            with self.subTest(value=value):
                target.unlink() if value is None else target.write_bytes(value)
                with self.assertRaises(ValueError):
                    self.inputs.assert_scope(self.inputs.capture(), accepted)
        target.write_text("before\n", encoding="utf-8")
        self.inputs.assert_restored(self.inputs.capture(), accepted)

    def test_new_untracked_file_is_refused(self) -> None:
        accepted = self.inputs.capture()
        (self.project / "new.txt").write_text("new\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.inputs.assert_scope(self.inputs.capture(), accepted)

    def test_index_drift_is_refused_even_when_owned_bytes_are_unchanged(self) -> None:
        (self.project / "owned.txt").write_text("candidate\n", encoding="utf-8")
        accepted = self.inputs.capture()
        self._git("add", "owned.txt")
        current = self.inputs.capture()
        self.assertEqual(current["owned"], accepted["owned"])
        with self.assertRaisesRegex(ValueError, "index"):
            self.inputs.assert_scope(current, accepted)

    def test_index_flags_and_hidden_content_drift_are_detected(self) -> None:
        accepted = self.inputs.capture()
        self._git("update-index", "--assume-unchanged", "outside.txt")
        with self.assertRaisesRegex(ValueError, "index"):
            self.inputs.assert_scope(self.inputs.capture(), accepted)
        accepted = self.inputs.capture()
        (self.project / "outside.txt").write_text("hidden\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.inputs.assert_scope(self.inputs.capture(), accepted)

    def test_head_drift_is_refused(self) -> None:
        accepted = self.inputs.capture()
        self._git("commit", "--allow-empty", "-qm", "new head")
        with self.assertRaisesRegex(ValueError, "head"):
            self.inputs.assert_scope(self.inputs.capture(), accepted)

    def test_missing_owned_file_can_be_created_then_restored(self) -> None:
        inputs = LoopInputs(self.project, ["new/owned.txt"], ["verify.py"])
        accepted = inputs.capture()
        (self.project / "new").mkdir()
        target = self.project / "new/owned.txt"
        target.write_text("candidate\n", encoding="utf-8")
        inputs.assert_scope(inputs.capture(), accepted)
        target.unlink()
        inputs.assert_restored(inputs.capture(), accepted)

    def test_deleted_owned_file_and_new_inode_restore_by_content(self) -> None:
        target = self.project / "owned.txt"
        original = target.read_bytes()
        mode = target.stat().st_mode & 0o777
        accepted = self.inputs.capture()
        target.unlink()
        self.inputs.assert_scope(self.inputs.capture(), accepted)
        target.write_bytes(original)
        target.chmod(mode)
        os.utime(target, (1, 1))
        self.inputs.assert_restored(self.inputs.capture(), accepted)

    def test_executable_mode_is_part_of_identity(self) -> None:
        for name in ("owned.txt", "outside.txt", "verify.py"):
            with self.subTest(name=name):
                target = self.project / name
                mode = target.stat().st_mode & 0o777
                accepted = self.inputs.capture()
                target.chmod(mode ^ 0o111)
                current = self.inputs.capture()
                if name == "owned.txt":
                    self.inputs.assert_scope(current, accepted)
                    with self.assertRaises(ValueError):
                        self.inputs.assert_restored(current, accepted)
                else:
                    with self.assertRaises(ValueError):
                        self.inputs.assert_scope(current, accepted)
                target.chmod(mode)

    def test_ignored_runtime_artifacts_do_not_drift(self) -> None:
        accepted = self.inputs.capture()
        for directory in (".moru", "ignored"):
            (self.project / directory).mkdir()
            (self.project / directory / "state.json").write_text("runtime\n")
        self.inputs.assert_restored(self.inputs.capture(), accepted)

    def test_rejects_unsafe_nonliteral_and_non_normalized_paths(self) -> None:
        for path in ("", ".", "..", "../outside", "/absolute", "a/../owned.txt",
                     "./owned.txt", "a//b", "a/", ".git/config", "x/.moru/state",
                     "*.py", "test?.py", "test[0].py", "a\\b", "nul\0file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                LoopInputs(self.project, [path], ["verify.py"])

    def test_rejects_empty_oversized_duplicate_and_overlapping_scopes(self) -> None:
        for owned, verifiers in (([], ["verify.py"]), (["owned.txt"], []),
                                 (["owned.txt"] * 2, ["verify.py"]),
                                 ([f"file-{number}" for number in range(65)], ["verify.py"]),
                                 (["owned.txt"], ["owned.txt"])):
            with self.subTest(owned=owned), self.assertRaises(ValueError):
                LoopInputs(self.project, owned, verifiers)

    def test_rejects_directory_missing_verifier_and_symlink_inputs(self) -> None:
        (self.project / "directory").mkdir()
        (self.project / "link").symlink_to("owned.txt")
        (self.project / "parent").symlink_to(self.project, target_is_directory=True)
        for owned, verifier in (("directory", "verify.py"), ("link", "verify.py"),
                                ("parent/owned.txt", "verify.py"),
                                ("parent/missing", "verify.py"),
                                ("owned.txt", "missing.py"), ("owned.txt", "link")):
            with self.subTest(owned=owned, verifier=verifier), self.assertRaises(ValueError):
                LoopInputs(self.project, [owned], [verifier])

    def test_symlink_introduced_after_enrollment_is_refused(self) -> None:
        target = self.project / "owned.txt"
        target.unlink()
        target.symlink_to("outside.txt")
        with self.assertRaises(ValueError):
            self.inputs.capture()

    def test_unowned_symlink_target_is_hashed_without_following_it(self) -> None:
        target = self.project / "local-link"
        target.symlink_to("/nonexistent-target")
        accepted = self.inputs.capture()
        target.unlink()
        target.symlink_to("/other-target")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.inputs.assert_scope(self.inputs.capture(), accepted)

    def test_rejects_oversized_file_count_bytes_and_git_output(self) -> None:
        for constant, value in (("_MAX_FILES", 1), ("_MAX_FILE_BYTES", 1),
                                ("_MAX_BYTES", 1), ("_MAX_GIT_BYTES", 1)):
            with self.subTest(constant=constant), patch(f"agent_loop_inputs.{constant}", value):
                with self.assertRaises(ValueError):
                    self.inputs.capture()

    def test_capture_refuses_inconsistent_consecutive_scans(self) -> None:
        first = self.inputs.capture()
        second = {**first, "outside": "changed"}
        with patch.object(self.inputs, "_capture", side_effect=[first, second]):
            with self.assertRaisesRegex(ValueError, "changed during capture"):
                self.inputs.capture()

    def test_scope_must_retain_same_owned_keys_and_snapshot_fields(self) -> None:
        accepted = self.inputs.capture()
        for changed in ({**accepted, "owned": {}}, {**accepted, "extra": True}, {}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.inputs.assert_scope(changed, accepted)

    def test_subdirectory_is_not_a_project_root(self) -> None:
        (self.project / "subdir").mkdir()
        with self.assertRaisesRegex(ValueError, "root"):
            LoopInputs(self.project / "subdir", ["owned"], ["verify.py"])


if __name__ == "__main__":
    unittest.main()
