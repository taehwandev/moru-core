"""Real Git fixture construction cannot spawn maintenance while copies are read."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _moru_test_support import TemplateRepository


class TemplateRepositoryTests(unittest.TestCase):
    def test_build_and_nested_copies_disable_maintenance_without_leaking_config(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trace = base / "trace.jsonl"
            seen = []

            def git(root, *args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

            def build(root):
                for relative in ("project", "rules"):
                    repo = root / relative
                    repo.mkdir()
                    git(repo, "init", "-q")
                    seen.append((git(repo, "config", "maintenance.auto"),
                                 git(repo, "config", "gc.auto"),
                                 git(repo, "config", "fixture.inherited")))
                    git(repo, "config", "user.name", "Fixture")
                    git(repo, "config", "user.email", "fixture@example.invalid")
                    (repo / "source.txt").write_text("source\n")
                    git(repo, "add", ".")
                    git(repo, "commit", "-qm", "fixture")

            inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
            inherited.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                             GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="fixture.inherited",
                             GIT_CONFIG_VALUE_0="kept", GIT_CONFIG_KEY_1="maintenance.auto",
                             GIT_CONFIG_VALUE_1="true", GIT_CONFIG_KEY_2="gc.auto",
                             GIT_CONFIG_VALUE_2="1", GIT_TRACE2_EVENT=str(trace))
            template = TemplateRepository(build, repositories=("project", "rules"))
            self.addCleanup(template.cleanup)
            with patch.dict(os.environ, inherited, clear=True):
                before = dict(os.environ)
                source = template.template()
                self.assertEqual(before, dict(os.environ))
                self.assertEqual([("false", "0", "kept")] * 2, seen)
                # Remove command-scope overrides: copied local config must also
                # keep later fixture commits from restarting maintenance.
                with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "0"}):
                    for i in range(3):
                        destination = template.copy_to(base / f"copy-{i}")
                        for relative in ("project", "rules"):
                            repo = destination / relative
                            self.assertEqual("false", git(repo, "config", "--local", "maintenance.auto"))
                            self.assertEqual("0", git(repo, "config", "--local", "gc.auto"))
                            self.assertEqual(git(source / relative, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD"))
                            self.assertEqual("", git(repo, "status", "--porcelain"))
                            git(repo, "commit", "--allow-empty", "-qm", "copied")
                records = [json.loads(line) for line in trace.read_text().splitlines()]
                children = [row.get("argv", []) for row in records if row.get("event") == "child_start"]
                self.assertFalse([args for args in children if "maintenance" in args or "gc" in args])


if __name__ == "__main__":
    unittest.main()
