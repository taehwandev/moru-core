"""Repository-key extraction preserves failure handling and call-scoped reuse."""
import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import agent_repository_key as subject
from support.git_read_scope import git_read_scope


class AgentRepositoryKeyTests(unittest.TestCase):
    def test_legacy_memory_import_is_the_same_public_lookup(self):
        from agent_project_memory import repository_key
        self.assertIs(subject.repository_key, repository_key)

    def test_failure_and_timeout_keep_resolved_path_fallback(self):
        project = Path(".")
        expected = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:24]
        for failure in (OSError("unavailable"), subprocess.TimeoutExpired("git", 2)):
            with self.subTest(failure=type(failure).__name__), patch.object(subject.subprocess, "run", side_effect=failure):
                self.assertEqual(expected, subject.repository_key(project))
        with patch.object(subject.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "ignored")):
            self.assertEqual(expected, subject.repository_key(project))

    def test_identity_is_shared_only_inside_existing_git_read_scope(self):
        with patch.object(subject.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "/synthetic/common\n")) as run:
            with git_read_scope():
                first = subject.repository_key(Path("."))
                self.assertEqual(first, subject.repository_key(Path(".")))
                self.assertEqual(1, run.call_count)
            self.assertEqual(first, subject.repository_key(Path(".")))
            self.assertEqual(2, run.call_count)
