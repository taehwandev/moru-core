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
    def test_moru_state_takes_precedence_with_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"MORU_STRUCTURE_RULES": "", "TAO_STRUCTURE_RULES": ""}
        ):
            project = Path(directory).resolve()
            legacy = project / ".tao" / "structure-rules.json"
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({"source": "legacy"}), encoding="utf-8")
            moru = project / ".moru" / "structure-rules.json"
            moru.parent.mkdir()
            (moru.parent / "state-ready").touch()

            configs, failures = load_structure_rule_configs(project)
            self.assertEqual([], failures)
            self.assertEqual([{"path": ".tao/structure-rules.json", "payload": {"source": "legacy"}}], configs)

            moru.write_text(json.dumps({"source": "moru"}), encoding="utf-8")
            configs, failures = load_structure_rule_configs(project)
            self.assertEqual([], failures)
            self.assertEqual([{"path": ".moru/structure-rules.json", "payload": {"source": "moru"}}], configs)

    def test_moru_override_precedes_legacy_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            moru = project / "moru.json"
            legacy = project / "legacy.json"
            moru.write_text("{}", encoding="utf-8")
            legacy.write_text('{"legacy": true}', encoding="utf-8")
            with patch.dict("os.environ", {"MORU_STRUCTURE_RULES": str(moru), "TAO_STRUCTURE_RULES": str(legacy)}):
                configs, failures = load_structure_rule_configs(project)
            self.assertEqual([], failures)
            self.assertEqual([{"path": "moru.json", "payload": {}}], configs)


if __name__ == "__main__":
    unittest.main()
