from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_project_discovery import build_entry_manifest, discover_projects, find_project_root
from agent_project_types import format_entry_text
from agent_project_search import default_registry_path


class AgentProjectDiscoveryTests(unittest.TestCase):
    def test_default_registry_uses_moru_state_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MORU_STATE_HOME": directory, "TAO_PROJECT_REGISTRY": ""}):
                self.assertEqual(Path(directory) / "projects.json", default_registry_path())

    def test_find_project_root_uses_nearest_agent_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            nested = project / "src" / "feature"
            nested.mkdir(parents=True)
            (project / "AGENTS.md").write_text("# instructions\n", encoding="utf-8")

            self.assertEqual(project.resolve(), find_project_root(nested))

    def test_cwd_project_is_selected_with_instruction_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "app"
            (project / ".agents").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
            (project / ".agents" / "README.md").write_text("# shared\n", encoding="utf-8")
            cwd = project / "src"
            cwd.mkdir()

            result = discover_projects("fix this app", cwd, search_roots=[], max_depth=0, include_default_search_roots=False)

            self.assertEqual("selected", result.status)
            self.assertEqual(project.resolve(), result.selected.path)
            self.assertIn("AGENTS.md", result.selected.instruction_files)
            self.assertIn(".agents/README.md", result.selected.instruction_files)

    def test_explicit_request_path_beats_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            current = base / "current"
            target = base / "target"
            current.mkdir()
            target.mkdir()
            (current / "AGENTS.md").write_text("# current\n", encoding="utf-8")
            (current / ".git").mkdir()
            (target / "CLAUDE.md").write_text("# target\n", encoding="utf-8")

            result = discover_projects(
                f"apply this to {target}",
                current,
                search_roots=[],
                max_depth=0,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", result.status)
            self.assertEqual(target.resolve(), result.selected.path)
            self.assertIn("explicit path in request", result.selected.reasons)

    def test_registry_alias_beats_current_git_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            current = base / "current"
            target = base / "target"
            current.mkdir()
            target.mkdir()
            (current / "AGENTS.md").write_text("# current\n", encoding="utf-8")
            (current / ".git").mkdir()
            (target / "AGENTS.md").write_text("# target\n", encoding="utf-8")
            registry = base / "projects.json"
            registry.write_text(
                json.dumps({"projects": [{"root": str(target), "aliases": ["target-app"]}]}),
                encoding="utf-8",
            )

            result = discover_projects(
                "work on target-app",
                current,
                registry_path=registry,
                search_roots=[],
                max_depth=0,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", result.status)
            self.assertEqual(target.resolve(), result.selected.path)

    def test_registry_alias_selects_project_from_home_like_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            project = base / "nunu-os-main"
            project.mkdir()
            (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
            registry = base / "projects.json"
            registry.write_text(
                json.dumps({"projects": [{"root": str(project), "aliases": ["nunu"]}]}),
                encoding="utf-8",
            )

            result = discover_projects(
                "work on nunu",
                base,
                registry_path=registry,
                search_roots=[],
                max_depth=0,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", result.status)
            self.assertEqual(project.resolve(), result.selected.path)
            self.assertIn("nunu", result.selected.aliases)

    def test_explicit_project_slug_does_not_select_conflicting_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            current = base / "Spill"
            current.mkdir()
            (current / "AGENTS.md").write_text("# spill app\n", encoding="utf-8")
            (current / ".git").mkdir()
            registry = base / "projects.json"
            registry.write_text(json.dumps({"projects": []}), encoding="utf-8")

            result = discover_projects(
                "spill-web 작업해줘",
                current,
                registry_path=registry,
                search_roots=[],
                max_depth=0,
                include_default_search_roots=False,
            )

            self.assertEqual("not_found", result.status)

    def test_registry_exact_slug_beats_conflicting_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            current = base / "Spill"
            target = base / "Spill-web"
            current.mkdir()
            target.mkdir()
            (current / "AGENTS.md").write_text("# spill app\n", encoding="utf-8")
            (current / ".git").mkdir()
            (target / "AGENTS.md").write_text("# spill web\n", encoding="utf-8")
            (target / ".git").mkdir()
            registry = base / "projects.json"
            registry.write_text(
                json.dumps({"projects": [{"root": str(target), "aliases": ["spill-web", "spill web"]}]}),
                encoding="utf-8",
            )

            result = discover_projects(
                "spill-web 작업해줘",
                current,
                registry_path=registry,
                search_roots=[],
                max_depth=0,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", result.status)
            self.assertEqual(target.resolve(), result.selected.path)

    def test_search_root_slug_match_ignores_prefix_and_generic_web(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            spill = base / "Spill"
            spill_web = base / "Spill-web"
            generic_web = base / "DTP" / "web"
            for project in (spill, spill_web, generic_web):
                project.mkdir(parents=True)
                (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
                (project / ".git").mkdir()
            outside = base / "outside"
            outside.mkdir()
            registry = base / "projects.json"
            registry.write_text(json.dumps({"projects": []}), encoding="utf-8")

            result = discover_projects(
                "spill-web 작업해줘",
                outside,
                registry_path=registry,
                search_roots=[base],
                max_depth=2,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", result.status)
            self.assertEqual(spill_web.resolve(), result.selected.path)

    def test_search_roots_report_ambiguous_when_projects_tie(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            one = base / "one"
            two = base / "two"
            one.mkdir()
            two.mkdir()
            (one / "AGENTS.md").write_text("# one\n", encoding="utf-8")
            (two / "AGENTS.md").write_text("# two\n", encoding="utf-8")
            outside = base / "outside"
            outside.mkdir()

            result = discover_projects(
                "update the app",
                outside,
                search_roots=[base],
                max_depth=1,
                include_default_search_roots=False,
            )

            self.assertEqual("ambiguous", result.status)
            self.assertEqual([one.resolve(), two.resolve()], [candidate.path for candidate in result.candidates[:2]])

    def test_directory_scanning_requires_explicit_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            project = base / "app"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (project / "AGENTS.md").write_text("# app\n", encoding="utf-8")

            result = discover_projects("update app", outside, max_depth=1)

            self.assertEqual("not_found", result.status)

    def test_entry_manifest_tells_runtime_to_read_project_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "app"
            project.mkdir()
            (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")

            manifest = build_entry_manifest(
                "update app",
                project,
                runtime="codex",
                command="feature",
                include_default_search_roots=False,
            )

            self.assertEqual("selected", manifest["status"])
            self.assertEqual("codex", manifest["runtime"])
            self.assertIn("workflow.py", manifest["workflow_command"])
            self.assertIn("AGENTS.md", manifest["selected_project"]["instruction_files"])
            self.assertIn("Open the selected project's runtime instruction files before project work.", manifest["next_steps"])

    def test_entry_manifest_includes_codex_runtime_launch_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "app"
            project.mkdir()
            (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")

            manifest = build_entry_manifest(
                "update app",
                project,
                runtime="codex",
                command="feature",
                include_default_search_roots=False,
            )

            runtime_launch = manifest["runtime_launch"]
            self.assertEqual(str(project.resolve()), runtime_launch["primary_workspace"])
            self.assertEqual(str(ROOT), runtime_launch["tao_root"])
            commands = [item["command"] for item in runtime_launch["commands"]]
            self.assertTrue(any(command.startswith("codex -C ") for command in commands))
            self.assertTrue(any("--add-dir" in command and str(ROOT) in command for command in commands))
            self.assertIn("runtime_launch:", format_entry_text(manifest))

    def test_workspace_group_alias_reports_primary_candidates_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            app = base / "keyflow-app"
            web = base / "keyflow-web"
            outside = base / "outside"
            for project in (app, web):
                project.mkdir()
                (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
            outside.mkdir()
            registry = base / "projects.json"
            registry.write_text(
                json.dumps(
                    {
                        "workspace_groups": [
                            {
                                "name": "keyflow",
                                "aliases": ["keyflow"],
                                "members": [
                                    {"role": "app", "root": str(app), "aliases": ["desktop", "app"]},
                                    {"role": "web", "root": str(web), "aliases": ["web"]},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_entry_manifest(
                "keyflow 작업해줘",
                outside,
                runtime="codex",
                registry_path=registry,
                include_default_search_roots=False,
            )

            self.assertEqual("ambiguous", manifest["status"])
            self.assertEqual("needs_target_decision", manifest["workspace_scope"]["scope_mode"])
            self.assertEqual("keyflow", manifest["workspace_scope"]["workspace_group"])
            self.assertEqual([str(app.resolve()), str(web.resolve())], manifest["workspace_scope"]["primary_candidates"])
            self.assertIn("workspace_scope:", format_entry_text(manifest))

    def test_workspace_group_member_alias_selects_primary_with_checkpoint_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            app = base / "keyflow-app"
            web = base / "keyflow-web"
            outside = base / "outside"
            for project in (app, web):
                project.mkdir()
                (project / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
            outside.mkdir()
            registry = base / "projects.json"
            registry.write_text(
                json.dumps(
                    {
                        "workspace_groups": [
                            {
                                "name": "keyflow",
                                "aliases": ["keyflow"],
                                "members": [
                                    {"role": "app", "root": str(app), "aliases": ["desktop", "app"]},
                                    {"role": "web", "root": str(web), "aliases": ["web"]},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_entry_manifest(
                "keyflow web 수정",
                outside,
                runtime="codex",
                registry_path=registry,
                include_default_search_roots=False,
            )

            self.assertEqual("selected", manifest["status"])
            self.assertEqual(str(web.resolve()), manifest["selected_project"]["path"])
            self.assertEqual("primary_selected_checkpoint_before_expansion", manifest["workspace_scope"]["scope_mode"])
            self.assertEqual("web", manifest["workspace_scope"]["primary_role"])
            self.assertTrue(manifest["workspace_scope"]["scope_checkpoint"]["required_before_secondary_write"])


if __name__ == "__main__":
    unittest.main()
