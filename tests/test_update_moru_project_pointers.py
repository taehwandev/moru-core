from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_moru_project_pointers import update_home_configs, update_project, updated_text  # noqa: E402


class MoruProjectPointersTests(unittest.TestCase):
    def test_pre_rename_placeholders_markers_and_settings_become_moru(self) -> None:
        source = (
            "<!-- BEGIN MANAGED TAO AGENT OS ROUTING -->\n"
            "<TAO_LAUNCHER> start --rules <TAO_ROOT> # Tao Agent OS\n"
            "export X=${TAO_HOME}/a $TAO_HOME/b\n"
            "TAO_HOOK_SOFT_FAIL=1 hook\n"
            '"Read(/.tao/worktrees/**)", "Bash(cd .tao/worktrees/*)"\n'
            "<!-- END MANAGED TAO AGENT OS ROUTING -->\n"
        )
        self.assertEqual(
            "<!-- BEGIN MANAGED MORU CORE ROUTING -->\n"
            "<MORU_LAUNCHER> start --rules <MORU_ROOT> # Moru Core\n"
            "export X=${MORU_HOME}/a $MORU_HOME/b\n"
            "MORU_HOOK_SOFT_FAIL=1 hook\n"
            '"Read(/.moru/worktrees/**)", "Bash(cd .moru/worktrees/*)"\n'
            "<!-- END MANAGED MORU CORE ROUTING -->\n",
            updated_text(source),
        )

    def test_updates_current_paths(self) -> None:
        home = str(Path.home())
        source = (
            'MORU_ROOT="${MORU_HOME:-$HOME/git/tao-agent-os}"\n'
            f'launcher={home}/.tao/bin/tao-hook\n'
            'pin=.agents/tao-agent-os\n'
        )
        result = updated_text(source)
        self.assertIn("${MORU_HOME:-$HOME/git/moru-core}", result)
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
            gemini = home / ".gemini" / "GEMINI.md"
            gemini.parent.mkdir()
            gemini.write_text("~/git/tao-agent-os\n", encoding="utf-8")
            (home / "history.txt").write_text("~/git/tao-agent-os")
            self.assertEqual([config, gemini], update_home_configs(home, apply=True))
            self.assertEqual(b'root = "$HOME/git/moru-core"\r\n', config.read_bytes())
            self.assertEqual("~/git/moru-core\n", gemini.read_text(encoding="utf-8"))
            self.assertEqual("~/git/tao-agent-os", (home / "history.txt").read_text())


if __name__ == "__main__":
    unittest.main()
