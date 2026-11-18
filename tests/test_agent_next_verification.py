"""Tests for agent_next_verification.py (directory-relative selectors, batching, quoting, omissions)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_next_verification as next_ver  # noqa: E402


class AgentNextVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve() / "project"
        self.project.mkdir()
        (self.project / "tests").mkdir()

    def test_directory_relative_and_nested_selectors_are_unqualified(self) -> None:
        pkg = self.project / "tests" / "pkg"
        pkg.mkdir()
        (pkg / "test_nested.py").write_text("import unittest\n", encoding="utf-8")
        (self.project / "scripts").mkdir()
        (self.project / "scripts" / "alpha_mod.py").write_text("x = 1\n", encoding="utf-8")
        (self.project / "tests" / "test_alpha_mod.py").write_text("import unittest\n", encoding="utf-8")

        res = next_ver.discover_verification_targets(
            self.project,
            ["scripts/alpha_mod.py", "tests/pkg/test_nested.py"],
        )
        self.assertEqual(["pkg.test_nested", "test_alpha_mod"], res["test_selectors"])
        self.assertEqual(["tests.pkg.test_nested", "tests.test_alpha_mod"], res["matched_test_modules"])
        self.assertEqual(["pkg.test_nested", "test_alpha_mod"], res["next_verify_batch"])
        self.assertEqual([], res["remaining_test_selectors"])
        self.assertEqual([], res["omissions"])

    def test_more_than_ten_tests_are_not_silently_sliced(self) -> None:
        paths = []
        for idx in range(14):
            rel = f"tests/test_item_{idx:02d}.py"
            (self.project / rel).write_text("import unittest\n", encoding="utf-8")
            paths.append(rel)
        res = next_ver.discover_verification_targets(self.project, paths)
        self.assertEqual(14, len(res["test_selectors"]))
        self.assertEqual(14, len(res["next_verify_batch"]))
        self.assertEqual([], res["remaining_test_selectors"])
        unittest_cmd = next(c for c in res["suggested_commands"] if "unittest" in c)
        for idx in range(14):
            self.assertIn(f"tests.test_item_{idx:02d}", unittest_cmd)

    def test_over_64_selectors_emit_bounded_batch_and_remaining_selection(self) -> None:
        paths = []
        for idx in range(70):
            rel = f"tests/test_b_{idx:02d}.py"
            (self.project / rel).write_text("import unittest\n", encoding="utf-8")
            paths.append(rel)
        res = next_ver.discover_verification_targets(self.project, paths)
        self.assertEqual(70, len(res["test_selectors"]))
        self.assertEqual(64, len(res["next_verify_batch"]))
        self.assertEqual(6, len(res["remaining_test_selectors"]))
        self.assertEqual([f"test_b_{idx:02d}" for idx in range(64, 70)], res["remaining_test_selectors"])
        self.assertTrue(
            any(o["kind"] == "batch_limit" and o["count"] == 6 for o in res["omissions"])
        )

    def test_unsupported_identifiers_symlinks_missing_and_unmatched_are_exposed(self) -> None:
        (self.project / "tests" / "test_-dash.py").write_text("x = 1\n", encoding="utf-8")
        outside = self.project.parent / "outside.py"
        outside.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
        (self.project / "tests" / "test_escape.py").symlink_to(outside)
        (self.project / "scripts").mkdir()
        (self.project / "scripts" / "orphan.py").write_text("x = 1\n", encoding="utf-8")

        res = next_ver.discover_verification_targets(
            self.project,
            [
                "tests/test_-dash.py",
                "tests/test_escape.py",
                "tests/test_deleted.py",
                "scripts/orphan.py",
            ],
        )
        self.assertEqual([], res["test_selectors"])
        reasons = {(o["kind"], o["path"], o["reason"]) for o in res["omissions"]}
        self.assertEqual(
            {
                ("unsupported_test_file", "tests/test_-dash.py", "invalid_selector_identifier"),
                ("unsupported_test_file", "tests/test_escape.py", "escapes_test_directory"),
                ("unsupported_test_file", "tests/test_deleted.py", "missing_or_deleted"),
                ("unmatched_python_file", "scripts/orphan.py", "no_matching_test_file"),
            },
            reasons,
        )

    def test_shell_quoting_protects_special_paths_and_never_executes(self) -> None:
        marker = self.project / "EXECUTED"
        special = f"a;touch {marker.name}.py"
        (self.project / special).write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
        (self.project / "-dash.py").write_text("x = 1\n")
        res = next_ver.discover_verification_targets(self.project, [special, "-dash.py"])
        self.assertFalse(marker.exists())
        py_cmd = next(c for c in res["suggested_commands"] if "py_compile" in c)
        self.assertIn("./-dash.py", py_cmd)
        self.assertIn(f"'{special}'", py_cmd)

    def test_non_python_fallback_preserved(self) -> None:
        (self.project / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
        res = next_ver.discover_verification_targets(self.project, ["src/lib.rs"])
        self.assertEqual(["cargo test"], res["suggested_commands"])


if __name__ == "__main__":
    unittest.main()
