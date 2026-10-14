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
    def test_reservations_live_under_the_moru_workers_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            parent = project / ".moru" / "runs" / "parent" / "preflight.json"

            selected, _, token = reserve_isolated_worker_evidence(project, parent)

            self.assertEqual(project / ".moru" / "workers", selected.parent.parent)
            self.assertTrue((selected.parent / ".moru-reservation").is_file())
            self.assertTrue(worker_reservation_matches(selected.parent, token))
            self.assertTrue(is_isolated_worker_evidence(project, selected))
            self.assertTrue(claim_worker_reservation(selected.parent, token))
            self.assertFalse((selected.parent / ".moru-reservation").exists())


if __name__ == "__main__":
    unittest.main()
