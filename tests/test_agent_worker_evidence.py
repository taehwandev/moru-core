"""Moru worker reservations must stay in the selected local state tree."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_worker_evidence import (  # noqa: E402
    claim_worker_reservation,
    is_isolated_worker_evidence,
    reserve_isolated_worker_evidence,
    worker_reservation_matches,
)


class WorkerEvidenceTests(unittest.TestCase):
    def test_migrated_project_reserves_under_moru(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            state = project / ".moru"
            state.mkdir()
            (state / "state-ready").touch()
            (project / ".tao").symlink_to(state, target_is_directory=True)
            parent = state / "runs" / "parent" / "preflight.json"

            selected, _, token = reserve_isolated_worker_evidence(project, parent)

            self.assertEqual(state / "workers", selected.parent.parent)
            self.assertTrue((selected.parent / ".moru-reservation").is_file())
            self.assertFalse((selected.parent / ".tao-reservation").exists())
            self.assertTrue(worker_reservation_matches(selected.parent, token))
            self.assertTrue(is_isolated_worker_evidence(project, selected))

    def test_migrated_legacy_marker_can_still_be_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker_dir = Path(directory) / ".moru" / "workers" / "legacy"
            worker_dir.mkdir(parents=True)
            token = "a" * 32
            marker = worker_dir / ".tao-reservation"
            marker.write_text(token + "\n", encoding="ascii")

            self.assertTrue(worker_reservation_matches(worker_dir, token))
            self.assertTrue(claim_worker_reservation(worker_dir, token))
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
