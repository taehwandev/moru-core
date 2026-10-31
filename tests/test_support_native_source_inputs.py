"""Source contracts inspect dependencies without executing candidate code."""
from pathlib import Path
import tempfile
import unittest

from support.native_source_inputs import pretool_contract, source_inputs


class NativeSourceInputsTests(unittest.TestCase):
    def fixture(self, root):
        package = root / "native/checkout-identity"
        (package / "src").mkdir(parents=True)
        for relative in ("Cargo.toml", "Cargo.lock", "build.rs", "src/main.rs"):
            (package / relative).write_text("")
        (package / "pretool_contract.py").write_text("raise RuntimeError('must not execute candidate generator')\n")
        scripts = root / "scripts"
        (scripts / "support").mkdir(parents=True)
        for name in ("claude_pretool_gate.py", "codex_pretool_gate.py", "codex_exec_workdir.py",
                     "support/native_source_inputs.py"):
            (scripts / name).write_text("")
        return scripts

    def test_candidate_source_and_generator_are_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = self.fixture(root)
            (scripts / "claude_pretool_gate.py").write_text("import candidate_helper\n")
            helper = scripts / "candidate_helper.py"
            helper.write_text("raise RuntimeError('must not execute candidate helper')\n")
            self.assertIn(helper, source_inputs(root))

    def test_all_sources_and_new_shadow_modules_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = self.fixture(root)
            (scripts / "claude_pretool_gate.py").write_text("from support import guard\nimport json\n")
            (scripts / "support/guard.py").write_text("from . import leaf\ndef later():\n    import deferred\n")
            (scripts / "support/leaf.py").write_text("value = 1\n")
            (scripts / "deferred.py").write_text("raise RuntimeError('not eager')\n")
            sources, directories = pretool_contract(root)
            self.assertIn("scripts/support/leaf.py", sources)
            self.assertIn("scripts/deferred.py", sources)
            self.assertIn("scripts/support", directories)
            self.assertNotIn("scripts/json.py", sources)
            (scripts / "json.py").write_text("value = 2\n")
            sources, directories = pretool_contract(root)
            self.assertIn("scripts/json.py", sources)
