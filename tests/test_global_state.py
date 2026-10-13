from __future__ import annotations

import os
import subprocess
import sys
import types
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support import global_state


def _env_without_test_markers() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {global_state.STATE_HOME_ENV, global_state.MORU_STATE_HOME_ENV, global_state.UNDER_TEST_ENV}
    }


class UserStoreWriteGuardTest(unittest.TestCase):
    def test_a_test_case_is_refused_whatever_started_the_runner(self) -> None:
        # A test file run as a script, `python -c` or agent_unittest_result.py
        # leaves a plain __main__ with no unittest spec.
        plain_main = types.ModuleType("__main__")
        with (
            patch.dict(os.environ, _env_without_test_markers(), clear=True),
            patch.dict(sys.modules, {"__main__": plain_main}),
        ):
            self.assertIn("test run", global_state.user_store_write_error())

    def test_a_state_home_still_permits_the_write(self) -> None:
        with patch.dict(os.environ, {global_state.STATE_HOME_ENV: "/tmp/tao-test-state"}):
            self.assertEqual("", global_state.user_store_write_error())

    def test_a_process_outside_any_test_may_write(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from support.global_state import user_store_write_error as e; print(repr(e()))",
                str(ROOT / "scripts"),
            ],
            capture_output=True,
            text=True,
            env=_env_without_test_markers(),
            check=True,
        )
        self.assertEqual("''", result.stdout.strip())


class MoruStateSelectionTest(unittest.TestCase):
    def test_unrelated_moru_directory_in_home_does_not_mark_home_as_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".moru" / "workspace").mkdir(parents=True)
            with patch.object(Path, "home", return_value=home):
                self.assertTrue(global_state.is_global_state_dir(home / ".moru"))
                self.assertFalse(global_state.marks_tao_project(home))

    def test_project_switches_only_after_explicit_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(project / ".tao", global_state.project_state_dir_target(project))
            (project / ".tao").mkdir()
            self.assertEqual(project / ".tao", global_state.project_state_dir_target(project))
            (project / ".moru").mkdir()
            self.assertEqual(project / ".tao", global_state.project_state_dir_target(project))
            (project / ".moru" / global_state.MORU_STATE_READY_MARKER).touch()
            self.assertEqual(project / ".moru", global_state.project_state_dir_target(project))

    def test_global_state_waits_for_migration_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with (patch.object(Path, "home", return_value=home),
                  patch.dict(os.environ, _env_without_test_markers(), clear=True)):
                (home / ".moru").mkdir()
                self.assertEqual(home / ".tao", global_state.global_state_dir())
                (home / ".moru" / global_state.MORU_STATE_READY_MARKER).touch()
                self.assertEqual(home / ".moru", global_state.global_state_dir())

    def test_explicit_moru_override_precedes_legacy_override(self) -> None:
        with patch.dict(os.environ, {
            global_state.STATE_HOME_ENV: "/tmp/old-state",
            global_state.MORU_STATE_HOME_ENV: "/tmp/new-state",
        }):
            self.assertEqual(Path("/tmp/new-state"), global_state.global_state_dir())
            self.assertEqual("", global_state.user_store_write_error())


if __name__ == "__main__":
    unittest.main()
