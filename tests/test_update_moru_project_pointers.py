from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.update_moru_project_pointers import update_home_configs, update_project, updated_text


class MoruProjectPointersTests(unittest.TestCase):
    def test_updates_current_paths_without_changing_compatibility_variable(self) -> None:
        home = str(Path.home())
        source = (
            'TAO_ROOT="${TAO_HOME:-$HOME/git/tao-agent-os}"\n'
            f'launcher={home}/.tao/bin/tao-hook\n'
            'pin=.agents/tao-agent-os\n'
        )
        result = updated_text(source)
        self.assertIn("${TAO_HOME:-$HOME/git/moru-core}", result)
        self.assertIn(f"{home}/.moru/bin/moru-hook", result)
        self.assertIn(".agents/moru-core", result)

    def test_scopes_edits_to_current_integration_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            instruction = project / "AGENTS.md"
            instruction.write_text("~/git/tao-agent-os\n", encoding="utf-8")
            historical = project / "history.md"
            historical.write_text("~/git/tao-agent-os\n", encoding="utf-8")
            self.assertEqual([instruction], update_project(project, apply=False))
            self.assertEqual("~/git/tao-agent-os\n", instruction.read_text())
            update_project(project, apply=True)
            self.assertEqual("~/git/moru-core\n", instruction.read_text())
            self.assertEqual("~/git/tao-agent-os\n", historical.read_text())

    def test_updates_only_known_user_config_and_preserves_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_bytes(b'root = "$HOME/git/tao-agent-os"\r\n')
            (home / "history.txt").write_text("~/git/tao-agent-os")
            self.assertEqual([config], update_home_configs(home, apply=True))
            self.assertEqual(b'root = "$HOME/git/moru-core"\r\n', config.read_bytes())
            self.assertEqual("~/git/tao-agent-os", (home / "history.txt").read_text())


if __name__ == "__main__":
    unittest.main()
