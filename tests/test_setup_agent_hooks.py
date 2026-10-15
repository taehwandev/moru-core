from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support.permission_entries import (
    claude_legacy_permission_entries,
    codex_legacy_prefix_rule_entries,
    codex_prefix_rule_entries,
)
from support.setup_config_files import (
    _status_marker,
    merge_codex_prefix_rules,
    merge_permissions_allow,
)
from support.codex_setup import CODEX_PRETOOL_MATCHER, merge_codex_pre_tool_gate
from support import setup_agent_hooks_impl
from support.setup_agent_hooks_impl import (
    configure_external_project,
    configure_target_projects,
    ensure_local_claude_excluded,
)
from support.stable_launcher import ensure_stable_launcher, stable_launcher_path, stable_root_pointer_path


class SetupAgentHooksTests(unittest.TestCase):
    def test_codex_only_target_setup_adds_worktree_root_without_touching_claude(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            (home / ".codex").mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text('default_permissions = ":workspace"\n')
            project.mkdir()
            args = setup_agent_hooks_impl.argparse.Namespace(
                target=str(project),
                github_projects=False,
            )

            with patch("support.setup_agent_hooks_impl.Path.home", return_value=home):
                results = configure_target_projects(
                    args,
                    selected_runtimes={"codex"},
                    dry_run=False,
                    launcher_configured=True,
                    spill_available=False,
                )

            config = (home / ".codex" / "config.toml").read_text()

        self.assertIn(
            f'"{(project / ".moru" / "worktrees").resolve()}" = true',
            config,
        )
        self.assertFalse((project / ".claude" / "settings.json").exists())
        self.assertEqual(["codex"], [result["tool"] for result in results])

    def test_default_setup_configures_all_detected_agent_runtimes(self) -> None:
        with (
            patch.object(sys, "argv", ["setup-agent-hooks.py", "--check"]),
            patch.object(setup_agent_hooks_impl, "_has_codex", return_value=True),
            patch.object(setup_agent_hooks_impl, "_has_claude", return_value=True),
            patch.object(setup_agent_hooks_impl, "_has_agy", return_value=True),
            patch.object(setup_agent_hooks_impl, "ensure_stable_launcher", return_value=[]),
            patch.object(
                setup_agent_hooks_impl,
                "configure_maintenance_scheduler",
                return_value=[],
            ) as configure_maintenance,
            patch.object(setup_agent_hooks_impl, "configure_codex", return_value=[]) as configure_codex,
            patch.object(setup_agent_hooks_impl, "configure_claude", return_value=[]) as configure_claude,
            patch.object(setup_agent_hooks_impl, "configure_agy", return_value=[]) as configure_agy,
            patch.object(setup_agent_hooks_impl, "configure_target_projects", return_value=[]),
        ):
            setup_agent_hooks_impl.main()

        configure_codex.assert_called_once()
        configure_claude.assert_called_once()
        configure_agy.assert_called_once()
        configure_maintenance.assert_called_once_with(ROOT, True)


    def test_target_setup_never_discovers_or_requires_graphify(self) -> None:
        def installed_binary(name):
            self.assertNotEqual("graphify", name)
            return None

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(sys, "argv", ["setup-agent-hooks.py", "--check", "--target", directory]),
            patch.object(setup_agent_hooks_impl, "_has_codex", return_value=False),
            patch.object(setup_agent_hooks_impl, "_has_claude", return_value=False),
            patch.object(setup_agent_hooks_impl, "_has_agy", return_value=False),
            patch.object(setup_agent_hooks_impl, "ensure_stable_launcher", return_value=[]),
            patch.object(setup_agent_hooks_impl.shutil, "which", side_effect=installed_binary),
            patch.object(setup_agent_hooks_impl.subprocess, "run") as subprocess_run,
        ):
            setup_agent_hooks_impl.main()
            subprocess_run.assert_not_called()
            self.assertEqual([], list(Path(directory).iterdir()))

        help_text = setup_agent_hooks_impl._argument_parser().format_help()
        self.assertNotIn("--graphify", help_text)
        self.assertNotIn("--skip-graphify", help_text)

    def test_agy_only_setup_installs_stable_launcher(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["setup-agent-hooks.py", "--runtime", "agy"],
            ),
            patch.object(setup_agent_hooks_impl, "_has_agy", return_value=True),
            patch.object(
                setup_agent_hooks_impl,
                "ensure_stable_launcher",
                return_value=[],
            ) as ensure_launcher,
            patch.object(setup_agent_hooks_impl, "configure_agy", return_value=[]),
            patch.object(
                setup_agent_hooks_impl,
                "configure_maintenance_scheduler",
                return_value=[],
            ),
            patch.object(setup_agent_hooks_impl, "configure_target_projects", return_value=[]),
        ):
            setup_agent_hooks_impl.main()

        ensure_launcher.assert_called_once_with(ROOT, False)


    def test_gemini_binary_selects_existing_agy_adapter(self) -> None:
        from support.setup_agent_hooks_impl import _has_agy

        with tempfile.TemporaryDirectory() as temp_home:
            def which(command: str) -> str | None:
                return "/tmp/gemini" if command == "gemini" else None

            with (
                patch("support.setup_agent_hooks_impl.Path.home", return_value=Path(temp_home)),
                patch("support.setup_agent_hooks_impl.shutil.which", side_effect=which),
            ):
                self.assertTrue(_has_agy())

    def test_stable_launcher_records_current_root_under_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                results = ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                pointer = stable_root_pointer_path()

                self.assertTrue(launcher.exists())
                self.assertTrue(os.access(launcher, os.X_OK))
                self.assertEqual(f"{ROOT.resolve()}\n", pointer.read_text())
                self.assertIn("scripts/workflow.py", launcher.read_text())
                self.assertIn('ROOT_POINTER_NAME = "moru-root"', launcher.read_text())
                self.assertIn('"execution-capsule": "agent_execution_capsule.py"', launcher.read_text())
                self.assertIn('"agent-os-status": "agent-os-status.py"', launcher.read_text())
                self.assertIn('"agent-os-watchdog": "agent-os-watchdog.py"', launcher.read_text())
                self.assertIn('"agent-os-maintenance": "agent-os-maintenance.py"', launcher.read_text())
                self.assertIn('"agent-mailbox": "agent-mailbox.py"', launcher.read_text())
                self.assertIn('"workflow-dispatch": "workflow_dispatch.py"', launcher.read_text())
                self.assertIn('"handoff"', launcher.read_text())
                self.assertTrue(all(result["status"] == "installed" for result in results))

                check = ensure_stable_launcher(ROOT, dry_run=True)

        self.assertTrue(all(result["status"] == "ok" for result in check))

    def test_codex_setup_is_idempotent_in_a_clean_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            home = Path(temp_home)
            with patch.dict(os.environ, {"HOME": temp_home}):
                first = ensure_stable_launcher(ROOT, dry_run=False)
                first += setup_agent_hooks_impl.configure_codex(False, root=ROOT)
                first_snapshot = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }

                second = ensure_stable_launcher(ROOT, dry_run=False)
                second += setup_agent_hooks_impl.configure_codex(False, root=ROOT)
                second_snapshot = {
                    path.relative_to(home): path.read_bytes()
                    for path in home.rglob("*")
                    if path.is_file()
                }

        # `ok` may carry its reason after the word, which is how a row that has
        # nothing to install explains itself; the report marks a status by the
        # same prefix rather than by an exact match.
        self.assertTrue(
            all(result["status"].startswith(("installed", "ok")) for result in first),
            [result["status"] for result in first],
        )
        self.assertTrue(
            all(result["status"].startswith("ok") for result in second),
            [result["status"] for result in second],
        )
        self.assertEqual(first_snapshot, second_snapshot)

    def test_codex_pretool_setup_preserves_neighboring_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            target = Path(temp_home) / "hooks.json"
            target.write_text(json.dumps({
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "custom-tool inspect"}],
                        }
                    ]
                }
            }))
            command = "MORU_HOOK_SOFT_FAIL=1 launcher codex-pretool-gate"

            first = merge_codex_pre_tool_gate(target, command, dry_run=False)
            second = merge_codex_pre_tool_gate(target, command, dry_run=False)
            groups = json.loads(target.read_text())["hooks"]["PreToolUse"]

        self.assertEqual("installed", first)
        self.assertEqual("ok", second)
        self.assertTrue(any(group.get("matcher") == "Bash" for group in groups))
        managed = [
            group
            for group in groups
            if group.get("matcher") == CODEX_PRETOOL_MATCHER
        ]
        self.assertEqual(1, len(managed))
        self.assertEqual(command, managed[0]["hooks"][0]["command"])

    def test_every_runtime_reports_where_its_status_line_stands(self) -> None:
        # Codex uses built-in items rather than a command, but setup still owns
        # enabling and reporting its remaining-quota items.
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                results = setup_agent_hooks_impl.configure_codex(True, root=ROOT)

        rows = [result for result in results if result["hook"] == "statusLine"]
        self.assertEqual(1, len(rows), [result["hook"] for result in results])
        self.assertEqual("WOULD UPDATE", _status_marker(rows[0]["status"]))

    def test_stable_launcher_soft_fails_when_root_pointer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                stable_root_pointer_path().write_text("/missing/moru-core\n")
                launcher = stable_launcher_path()
                env = os.environ.copy()
                env["MORU_HOOK_SOFT_FAIL"] = "1"

                result = subprocess.run(
                    [str(launcher), "workflow", "validate"],
                    cwd=temp_home,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("Moru Core hook skipped", result.stderr)

    def test_stable_launcher_blocks_by_default_when_alias_is_unsupported(self) -> None:
        # Without the opt-in flag, a misconfigured or misspelled hook alias
        # must not silently exit 0 - required hooks are gated on exit code,
        # so a quiet success here would let callers skip the entire gate
        # system without noticing.
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                env = os.environ.copy()
                env.pop("MORU_HOOK_SOFT_FAIL", None)

                result = subprocess.run(
                    [str(launcher), "totally-bogus-alias"],
                    cwd=temp_home,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unsupported Moru Core script alias", result.stderr)

    def test_stable_launcher_supports_agent_hook_subcommand_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "start", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Moru Core script alias: start", result.stderr)
        self.assertIn("--request-classified", result.stdout)

    def test_stable_launcher_supports_agent_mailbox_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "agent-mailbox", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("send", result.stdout)
        self.assertIn("receive", result.stdout)
        self.assertNotIn("unsupported Moru Core script alias", result.stderr)

    def test_installed_launcher_can_capture_and_recall_project_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            project = Path(temp_home) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
            # Test runs must name their state home; the stores refuse the default.
            environment = {**os.environ, "HOME": temp_home,
                           "MORU_STATE_HOME": str(Path(temp_home) / ".moru")}

            def invoke(*args: str, body: str = "") -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(launcher), "project-memory", "--project", str(project), *args],
                    input=body, env=environment, text=True, capture_output=True, check=False,
                )

            candidate = invoke("capture", "--source", "design note",
                               "--review-on", "9999-12-31", body="Check the local contract.")
            self.assertEqual(0, candidate.returncode, candidate.stderr)
            record = json.loads(candidate.stdout)
            recalled = invoke("recall")
            self.assertEqual(0, recalled.returncode, recalled.stderr)
            self.assertEqual(record["id"], json.loads(recalled.stdout)[0]["id"])

    def test_installed_launcher_can_list_and_close_work_cards(self) -> None:
        from agent_work_cards import open_card

        with tempfile.TemporaryDirectory() as temp_home:
            project = Path(temp_home) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            environment = dict(os.environ)
            environment["HOME"] = temp_home
            # Test runs must name their state home; the stores refuse the default.
            environment["MORU_STATE_HOME"] = str(Path(temp_home) / ".moru")
            with patch.dict(os.environ, environment, clear=True):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                open_card(project, "a" * 32, summary="unfinished slice", command="task")

            def invoke(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(launcher), "work-cards", "--project", str(project), *args],
                    env=environment, text=True, capture_output=True, check=False,
                )

            listed = invoke("list")
            self.assertEqual(0, listed.returncode, listed.stderr)
            self.assertEqual(["unfinished slice"], [card["summary"] for card in json.loads(listed.stdout)])
            closed = invoke("close", "a" * 32)
            self.assertEqual(0, closed.returncode, closed.stderr)
            self.assertEqual([], json.loads(invoke("list").stdout))

    def test_full_setup_keeps_agent_mailbox_alias_in_an_isolated_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            environment = {**os.environ, "HOME": temp_home}
            setup = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "setup-agent-hooks.py"), "--runtime", "codex"],
                cwd=str(ROOT),
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            launcher = Path(temp_home) / ".moru" / "bin" / "moru-hook"
            help_result = subprocess.run(
                [str(launcher), "agent-mailbox", "--help"],
                cwd=str(ROOT),
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            codex_config = (Path(temp_home) / ".codex" / "config.toml").read_text(
                encoding="utf-8"
            )

        self.assertEqual(0, setup.returncode, setup.stderr)
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertIn("receive", help_result.stdout)
        self.assertIn('"five-hour-limit"', codex_config)
        self.assertIn('"weekly-limit"', codex_config)

    def test_stable_launcher_supports_gate_batch_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "gate-batch", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Moru Core script alias: gate-batch", result.stderr)
        self.assertIn("--gate-record", result.stdout)

    def test_stable_launcher_supports_fingerprint_alias(self) -> None:
        """The envelope bootstrap helper must resolve through the launcher."""

        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "fingerprint", "--request", "do the thing"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("request fingerprint: ", result.stdout)
        self.assertIn("envelope skeleton", result.stdout)

    def test_stable_launcher_supports_cancel_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "cancel", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Moru Core script alias: cancel", result.stderr)
        self.assertIn("--replacement-evidence", result.stdout)

    def test_stable_launcher_supports_resume_alias(self) -> None:
        """A resume the installed launcher rejects is a resume no session has."""

        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "resume", "--help"],
                    cwd=str(ROOT),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn("unsupported Moru Core script alias: resume", result.stderr)
        self.assertIn("--last", result.stdout)

    def test_stable_launcher_supports_codex_stop_gate_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "codex-stop-gate"],
                    cwd=str(ROOT),
                    input="{}",
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn(
            "unsupported Moru Core script alias: codex-stop-gate",
            result.stderr,
        )

    def test_stable_launcher_supports_codex_pretool_gate_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {"HOME": temp_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()

                result = subprocess.run(
                    [str(launcher), "codex-pretool-gate"],
                    cwd=str(ROOT),
                    input="{}",
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertNotIn(
            "unsupported Moru Core script alias: codex-pretool-gate",
            result.stderr,
        )

    def test_stable_launcher_supports_optional_skill_feedback_alias(self) -> None:
        expected = {
            "skill-feedback": "--skill-feedback-outcome",
            "skill-curate": "--skill-feedback-outcome",
            "skill-review": "--skill-review-outcome",
            "skill-maintenance": "--skill-maintenance-outcome",
        }
        for alias, option in expected.items():
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as temp_home:
                with patch.dict(os.environ, {"HOME": temp_home}):
                    ensure_stable_launcher(ROOT, dry_run=False)
                    launcher = stable_launcher_path()

                    result = subprocess.run(
                        [str(launcher), alias, "--help"],
                        cwd=str(ROOT),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )

            self.assertEqual(0, result.returncode)
            self.assertNotIn(f"unsupported Moru Core script alias: {alias}", result.stderr)
            self.assertIn(option, result.stdout)

    def test_external_project_claude_settings_are_excluded_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")

            status = ensure_local_claude_excluded(project, dry_run=False)

            self.assertEqual("installed", status)
            self.assertIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_dry_run_reports_missing_without_writing_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")

            status = ensure_local_claude_excluded(project, dry_run=True)

            self.assertEqual("missing", status)
            self.assertNotIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_tracked_claude_settings_are_not_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text("{}\n")
            self._git(project, "add", ".claude/settings.json")

            status = ensure_local_claude_excluded(project, dry_run=False)

            self.assertEqual("ok", status)
            self.assertNotIn(".claude/", (project / ".git" / "info" / "exclude").read_text())

    def test_tracked_claude_settings_remain_machine_portable_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            self._git(project, "init")
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({
                "permissions": {"allow": ["Bash(user-owned-command *)"]}
            }) + "\n")
            self._git(project, "add", ".claude/settings.json")

            first = configure_external_project(
                project,
                ROOT / "scripts",
                dry_run=False,
                spill_available=False,
            )
            first_text = settings.read_text()
            second = configure_external_project(
                project,
                ROOT / "scripts",
                dry_run=False,
                spill_available=False,
            )

            self.assertTrue(all(result["status"] in {"installed", "ok"} for result in first))
            self.assertTrue(all(result["status"] == "ok" for result in second))
            self.assertEqual(first_text, settings.read_text())
            self.assertIn("Bash(user-owned-command *)", first_text)
            self.assertNotIn(str(Path.home()), first_text)
            self.assertNotIn(str(stable_launcher_path()), first_text)

    def test_codex_merge_preserves_unmanaged_rules_added_after_managed_block(self) -> None:
        # Codex appends user approvals after the managed block. Both checking
        # and reinstalling must leave this already-valid file untouched.
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "default.rules"
            user_rule = 'prefix_rule(pattern=["user-approved-tool"], decision="allow")'
            entries = codex_prefix_rule_entries(ROOT / "scripts")
            merge_codex_prefix_rules(target, entries, dry_run=False)
            target.write_text(target.read_text() + user_rule + "\n")
            original = target.read_text()

            dry_run_status = merge_codex_prefix_rules(target, entries, dry_run=True)
            install_status = merge_codex_prefix_rules(target, entries, dry_run=False)
            settled = target.read_text()
            settled_status = merge_codex_prefix_rules(target, entries, dry_run=True)

            self.assertEqual("ok", dry_run_status)
            self.assertEqual("ok", install_status)
            self.assertEqual("ok", settled_status)
            self.assertEqual(settled, target.read_text())
            self.assertEqual(1, settled.count(user_rule))
            self.assertEqual(1, settled.count("# moru-hooks:begin"))
            self.assertEqual(original, settled)

    def test_runtime_setup_removes_superseded_brand_content_and_permissions(self) -> None:
        # Setup rebuilds the managed block from current entries only, so
        # obsolete-brand content inside the managed region never survives, and
        # explicit cleanup entries purge obsolete-brand permissions while
        # user-owned entries are preserved.
        obsolete_brand = "agent" + "play" + "book"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules = root / "default.rules"
            settings = root / "settings.json"
            stale_rule = (
                f'prefix_rule(pattern=["/{obsolete_brand}/hook"], decision="allow")'
            )
            rules.write_text(
                "\n".join(
                    [
                        "# moru-hooks:begin",
                        f"# Managed by {obsolete_brand}",
                        stale_rule,
                        "# moru-hooks:end",
                        stale_rule,
                        'prefix_rule(pattern=["custom-tool"], decision="allow")',
                        "",
                    ]
                )
            )
            stale_permission = f"Bash(/Users/example/.{obsolete_brand}/bin/hook *)"
            settings.write_text(json.dumps({
                "permissions": {
                    "allow": [
                        stale_permission,
                        "Bash(custom-tool *)",
                    ]
                }
            }) + "\n")

            merge_codex_prefix_rules(
                rules,
                ['prefix_rule(pattern=["moru-hook"], decision="allow")'],
                dry_run=False,
                cleanup_entries=[stale_rule],
            )
            merge_permissions_allow(
                settings,
                ["Bash(moru-hook *)"],
                dry_run=False,
                cleanup_entries=[stale_permission],
            )

            self.assertNotIn(obsolete_brand, rules.read_text().lower())
            self.assertIn("custom-tool", rules.read_text())
            self.assertIn('prefix_rule(pattern=["moru-hook"]', rules.read_text())
            permissions = json.loads(settings.read_text())["permissions"]["allow"]
            self.assertFalse(any(obsolete_brand in entry.lower() for entry in permissions))
            self.assertIn("Bash(custom-tool *)", permissions)
            self.assertIn("Bash(moru-hook *)", permissions)

    def _git(self, project: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(project), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
