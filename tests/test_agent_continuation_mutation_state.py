from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_mutation_state import MutationCheckpointState


class MutationLocalPathsTests(unittest.TestCase):
    def test_runtime_state_is_excluded_from_mutation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "source.py").write_text("value = 1\n", encoding="utf-8")
            for state_dir in (".tao", ".moru"):
                state = project / state_dir / "runs"
                state.mkdir(parents=True)
                (state / "private.json").write_text("{}", encoding="utf-8")

            self.assertEqual(
                {Path("source.py")},
                MutationCheckpointState._local_paths(project),
            )


if __name__ == "__main__":
    unittest.main()
