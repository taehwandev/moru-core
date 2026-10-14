from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_directory_fingerprint import directory_signature
from support import legacy_names  # noqa: E402


class DirectorySignatureTests(unittest.TestCase):
    def test_runtime_state_does_not_change_non_git_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "source.txt"
            source.write_text("first\n", encoding="utf-8")
            original = directory_signature(project)

            for state_name in (".moru", legacy_names.STATE_DIR):
                state = project / state_name / "runs"
                state.mkdir(parents=True)
                (state / "private.json").write_text("{}", encoding="utf-8")
                self.assertEqual(original, directory_signature(project))

            source.write_text("second\n", encoding="utf-8")
            self.assertNotEqual(original, directory_signature(project))


if __name__ == "__main__":
    unittest.main()
