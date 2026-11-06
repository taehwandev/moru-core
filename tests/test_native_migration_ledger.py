"""Full Goal accounting must not silently omit entries or supporting sources."""
import json
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeMigrationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads((ROOT / "docs/runtime-performance/migration-ledger.json").read_text())

    def test_every_inventory_entry_has_one_stable_goal_owner(self):
        expected = {}
        for line in (ROOT / self.ledger["inventory"]).read_text().splitlines():
            cells = [part.strip() for part in line.strip().strip("|").split("|")]
            if len(cells) == 5 and cells[0].isdigit():
                expected[int(cells[0])] = cells[1].strip("`")
        units = self.ledger["units"]
        self.assertEqual(56, len(expected))
        self.assertEqual(expected, {row["inventory_id"]: row["id"] for row in units})
        self.assertEqual(len(units), len({row["id"] for row in units}))
        self.assertEqual(31, sum(row["kind"] == "primary" for row in units))
        self.assertEqual(25, sum(row["kind"] == "ancillary" for row in units))
        self.assertEqual(sorted(expected), sorted(n for wave in self.ledger["waves"].values() for n in wave))

    def test_all_current_python_responsibilities_are_accounted_for_once(self):
        current = {p.relative_to(ROOT).as_posix() for folder in ("scripts", "native")
                   for p in (ROOT / folder).rglob("*.py")
                   if "__pycache__" not in p.relative_to(ROOT).parts
                   and not p.is_relative_to(ROOT / "native/checkout-identity/target")}
        groups = [self.ledger["unmigrated_python_sources"], self.ledger["reference_only_python_sources"],
                  self.ledger["external_python_sources"]]
        self.assertEqual(current, set().union(*map(set, groups)))
        self.assertEqual(len(current), sum(len(group) for group in groups))
        for path in self.ledger["external_python_sources"]:
            self.assertTrue(path.startswith("scripts/third_party/"), path)
        for path, evidence in self.ledger["reference_only_python_sources"].items():
            self.assertTrue(evidence.get("native_owner"), path)
            self.assertTrue(evidence.get("verification"), path)
        for path, evidence in self.ledger["retired_python_sources"].items():
            self.assertNotIn(path, current)
            self.assertTrue(evidence.get("caller_proof"), path)

    def test_completion_requires_native_behavior_and_actual_delivery_evidence(self):
        statuses = {"planned", "partial_native", "native_revalidation", "native_local_verified", "native_verified", "external_review", "blocked"}
        for row in self.ledger["units"]:
            self.assertIn(row["status"], statuses)
            if row["status"] in {"native_verified", "native_local_verified"}:
                for field in ("native_owner", "behavior", "negative_authority", "portable", "installed", "source_revision"):
                    self.assertTrue(row["verification"].get(field), (row["id"], field))
                self.assertTrue((ROOT / row["verification"]["native_owner"]).is_file())
                for path, digest in row["verification"]["source_hashes"].items():
                    self.assertFalse(Path(path).is_absolute() or ".." in Path(path).parts)
                    self.assertTrue((ROOT / path).resolve().is_relative_to(ROOT.resolve()))
                    self.assertEqual(digest, hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), path)
                platforms = row["verification"]["platforms"]
                self.assertEqual(set(self.ledger["supported_platforms"]), set(platforms))
                if row["status"] == "native_verified":
                    self.assertTrue(all(value == "PASS" for value in platforms.values()))
                else:
                    self.assertIn("PASS", platforms.values())
            else:
                self.assertTrue(row["remaining"], row["id"])
            if row["status"] == "blocked":
                self.assertTrue(row.get("blocker"), row["id"])
        if self.ledger["goal_status"] == "complete":
            self.assertTrue(all(row["status"] == "native_verified" for row in self.ledger["units"]))
            self.assertEqual([], self.ledger["unmigrated_python_sources"])
            self.assertEqual([], self.ledger["external_python_sources"])


if __name__ == "__main__":
    unittest.main()
