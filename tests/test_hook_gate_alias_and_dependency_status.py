from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_hook_runtime import git_status  # noqa: E402

HOOK = str(ROOT / "scripts" / "agent-hook.py")


class GateNameAliasTests(unittest.TestCase):
    def run_hook(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, HOOK, *args], capture_output=True, text=True, check=False)

    def test_gate_accepts_the_option_and_the_alias_agents_use(self):
        for flag in ("--gate-name", "--name"):
            with self.subTest(flag=flag):
                self.assertEqual(0, self.run_hook("gate", flag, "tests", "--help").returncode)

    def test_a_guessed_gate_option_is_refused_with_the_right_one_named(self):
        result = self.run_hook("gate", "--gate", "tests")
        self.assertEqual(2, result.returncode)
        self.assertIn("--gate-name <gate>", result.stderr)

    def test_finish_still_refuses_gate_evidence_through_gate(self):
        result = self.run_hook("finish", "--gate", "tests")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("finish no longer accepts --gate", result.stderr)


class DependencyFoldersAreNotChangesTests(unittest.TestCase):
    def test_node_modules_stay_out_of_the_changed_path_count_but_source_stays_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            for rel in ("src/a.js", "node_modules/x/y.js", "pkg/node_modules/z/w.js", "dist/b.js"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("x")
            _, lines = git_status(root)
        joined = "\n".join(lines)
        self.assertIn("src/a.js", joined)
        self.assertIn("dist/b.js", joined)
        self.assertNotIn("node_modules", joined)


if __name__ == "__main__":
    unittest.main()
