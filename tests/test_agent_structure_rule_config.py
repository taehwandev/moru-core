from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_structure_rule_config import load_structure_rule_configs


class StructureRuleConfigTests(unittest.TestCase):
    def test_project_state_rules_are_read_from_moru(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"MORU_STRUCTURE_RULES": ""}
        ):
            project = Path(directory).resolve()
            rules = project / ".moru" / "structure-rules.json"
            rules.parent.mkdir()
            rules.write_text(json.dumps({"source": "moru"}), encoding="utf-8")

            configs, failures = load_structure_rule_configs(project)

            self.assertEqual([], failures)
            self.assertEqual([{"path": ".moru/structure-rules.json", "payload": {"source": "moru"}}], configs)

    def test_an_explicit_override_is_read_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            override = project / "override.json"
            override.write_text("{}", encoding="utf-8")
            with patch.dict("os.environ", {"MORU_STRUCTURE_RULES": str(override)}):
                configs, failures = load_structure_rule_configs(project)
            self.assertEqual([], failures)
            self.assertEqual([{"path": "override.json", "payload": {}}], configs)


if __name__ == "__main__":
    unittest.main()
