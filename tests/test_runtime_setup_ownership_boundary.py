"""Moru setup must edit only what Moru installed, and prove it rather than infer it.

Two products can configure the same runtime. Claude reads one `settings.json`
and Codex one config file, so every installer writes into a space it shares
with tools it knows nothing about. The rule these tests hold is narrow: an
entry may be rewritten or removed only when its provenance is readable -- a Moru
alias inside the command, or a marker block Moru emitted -- never because it
resembles something Moru would have written.

Resemblance is the specific trap. Moru's label bridge and a companion metering
tool's own hook can both carry the same environment prefix, sit on the same
event, and use a similar timeout. A predicate matching any of those signals
alone would delete a working install of the other product.

Fixtures here stay deliberately generic. Pinning another product's real binary
names or install paths would make these tests a stale mirror of something this
repository does not own, and would break them whenever that product moves.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from support import claude_setup
from support.claude_setup import (
    _is_managed_claude_pre_tool_gate_command,
    _is_managed_claude_spill_bridge_command,
    _is_managed_claude_stop_gate_command,
    _merge_claude_stop_gate,
    _remove_claude_env,
    _set_claude_env,
)
from support.setup_config_files import merge_codex_prefix_rules

# Foreign hooks in the shapes that actually collide with Moru's predicates.
# FOREIGN_SHARED_PREFIX is the hard one: it carries the very environment prefix
# Moru also writes, so only the command after it distinguishes the two.
FOREIGN_SHARED_PREFIX = "SPILL_AI_TOOL=claude python3 '/opt/vendor-a/adapters/hook.py'"
FOREIGN_IMPORTER = "node /opt/vendor-a/adapters/importer.mjs --since-hours 6"
FOREIGN_STOP = "/opt/vendor-b/bin/tool hook --event Stop"
UNKNOWN_STOP = "/opt/vendor-c/bin/whatever --event Stop --flag"
MORU_STOP_GATE = "MORU_HOOK_SOFT_FAIL=1 '/Users/x/.moru/bin/moru-hook' claude-stop-gate"
MORU_LABEL_BRIDGE = "SPILL_AI_TOOL=claude moru-hook workflow route triage --advisory"


def _hook(command: str, timeout: int = 10) -> dict:
    return {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def _commands(settings: Path, event: str) -> list[str]:
    config = json.loads(settings.read_text(encoding="utf-8"))
    return [
        hook.get("command", "")
        for group in config.get("hooks", {}).get(event, [])
        for hook in group.get("hooks", [])
    ]


class OwnershipPredicateTests(unittest.TestCase):
    def test_no_predicate_claims_another_product(self) -> None:
        predicates = (
            _is_managed_claude_stop_gate_command,
            _is_managed_claude_pre_tool_gate_command,
            _is_managed_claude_spill_bridge_command,
        )
        for command in (FOREIGN_SHARED_PREFIX, FOREIGN_IMPORTER, FOREIGN_STOP, UNKNOWN_STOP):
            for predicate in predicates:
                with self.subTest(command=command[:40], predicate=predicate.__name__):
                    self.assertFalse(predicate(command))

    def test_the_label_bridge_needs_more_than_the_shared_env_prefix(self) -> None:
        # A companion tool's hook carries the same prefix. Ownership rests on the
        # Moru route command that follows it, not on the prefix.
        self.assertTrue(_is_managed_claude_spill_bridge_command(MORU_LABEL_BRIDGE))
        self.assertFalse(_is_managed_claude_spill_bridge_command(FOREIGN_SHARED_PREFIX))


class _SettingsFixture:
    """Shared fixture only. Kept off `TestCase` so subclasses do not re-run it."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        home = Path(self._temp.name)
        self.settings = home / "settings.json"
        self.state = home / "moru-state"
        patcher = patch.object(claude_setup, "global_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, config: dict) -> None:
        self.settings.write_text(json.dumps(config, indent=2), encoding="utf-8")


class ClaudeSettingsMergeTests(_SettingsFixture, unittest.TestCase):
    def test_installing_preserves_every_foreign_stop_hook(self) -> None:
        self._write({
            "hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5), _hook(FOREIGN_STOP, 5),
                               _hook(UNKNOWN_STOP)]},
            "model": "opus",
        })
        _merge_claude_stop_gate(self.settings, MORU_STOP_GATE, dry_run=False)
        after = _commands(self.settings, "Stop")
        for command in (FOREIGN_SHARED_PREFIX, FOREIGN_STOP, UNKNOWN_STOP):
            self.assertIn(command, after)
        self.assertIn(MORU_STOP_GATE, after)

    def test_unrelated_keys_and_user_settings_survive(self) -> None:
        self._write({
            "hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5)]},
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
            "statusLine": {"type": "command", "command": "mine"},
        })
        _merge_claude_stop_gate(self.settings, MORU_STOP_GATE, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("opus", config["model"])
        self.assertEqual(["Bash(ls:*)"], config["permissions"]["allow"])
        self.assertEqual("mine", config["statusLine"]["command"])

    def test_repeated_setup_does_not_duplicate(self) -> None:
        self._write({"hooks": {"Stop": [_hook(FOREIGN_SHARED_PREFIX, 5)]}})
        for _ in range(3):
            _merge_claude_stop_gate(self.settings, MORU_STOP_GATE, dry_run=False)
        after = _commands(self.settings, "Stop")
        self.assertEqual(1, after.count(MORU_STOP_GATE))
        self.assertEqual(1, after.count(FOREIGN_SHARED_PREFIX))

    def test_a_moru_hook_sharing_a_group_with_a_foreign_hook_is_removed_alone(self) -> None:
        # Removal is per hook object. Dropping the enclosing group would take a
        # neighbouring product's hook with it.
        self._write({"hooks": {"Stop": [{
            "matcher": "",
            "hooks": [
                {"type": "command", "command": MORU_STOP_GATE, "timeout": 10},
                {"type": "command", "command": FOREIGN_SHARED_PREFIX, "timeout": 5},
            ],
        }]}})
        _merge_claude_stop_gate(self.settings, MORU_STOP_GATE + " --updated", dry_run=False)
        after = _commands(self.settings, "Stop")
        self.assertIn(FOREIGN_SHARED_PREFIX, after)
        self.assertNotIn(MORU_STOP_GATE, after)

    def test_duplicate_current_moru_hooks_collapse_to_one_without_touching_foreign_hooks(self) -> None:
        from support.claude_setup import _PRETOOL_GATE_MATCHER, _merge_claude_pre_tool_gate
        from support.codex_setup import CODEX_PRETOOL_MATCHER, merge_codex_pre_tool_gate, merge_codex_stop_gate

        self._write({"hooks": {
            "Stop": [_hook(FOREIGN_STOP, 5), _hook(MORU_STOP_GATE), _hook(MORU_STOP_GATE)],
            "PreToolUse": [{
                "matcher": _PRETOOL_GATE_MATCHER,
                "hooks": [
                    {"type": "command", "command": "moru-hook claude-pretool-gate", "timeout": 10},
                    {"type": "command", "command": "moru-hook claude-pretool-gate", "timeout": 10},
                    {"type": "command", "command": FOREIGN_SHARED_PREFIX, "timeout": 5},
                ],
            }],
        }})
        self.assertEqual("would_update", _merge_claude_stop_gate(self.settings, MORU_STOP_GATE, dry_run=True))
        self.assertEqual("installed", _merge_claude_stop_gate(self.settings, MORU_STOP_GATE, dry_run=False))
        self.assertEqual([FOREIGN_STOP, MORU_STOP_GATE], _commands(self.settings, "Stop"))
        self.assertEqual("would_update", _merge_claude_pre_tool_gate(self.settings, "moru-hook claude-pretool-gate", dry_run=True))
        self.assertEqual("installed", _merge_claude_pre_tool_gate(self.settings, "moru-hook claude-pretool-gate", dry_run=False))
        self.assertEqual([FOREIGN_SHARED_PREFIX, "moru-hook claude-pretool-gate"], _commands(self.settings, "PreToolUse"))

        with tempfile.TemporaryDirectory() as directory:
            codex_hooks = Path(directory) / "hooks.json"
            codex_cmd = "MORU_HOOK_SOFT_FAIL=1 moru-hook codex-pretool-gate"
            codex_stop = "MORU_HOOK_SOFT_FAIL=1 moru-hook codex-stop-gate"
            codex_hooks.write_text(json.dumps({"hooks": {
                "PreToolUse": [
                    {"matcher": CODEX_PRETOOL_MATCHER, "hooks": [
                        {"type": "command", "command": codex_cmd, "timeout": 10},
                        {"type": "command", "command": codex_cmd, "timeout": 10},
                        {"type": "command", "command": FOREIGN_IMPORTER, "timeout": 5},
                    ]},
                ],
                "Stop": [
                    {"hooks": [
                        {"type": "command", "command": codex_stop, "timeout": 10},
                        {"type": "command", "command": codex_stop, "timeout": 10},
                        {"type": "command", "command": FOREIGN_STOP, "timeout": 5},
                    ]},
                ],
            }}), encoding="utf-8")
            self.assertEqual("would_update", merge_codex_pre_tool_gate(codex_hooks, codex_cmd, dry_run=True))
            self.assertEqual("installed", merge_codex_pre_tool_gate(codex_hooks, codex_cmd, dry_run=False))
            self.assertEqual("would_update", merge_codex_stop_gate(codex_hooks, codex_stop, dry_run=True))
            self.assertEqual("installed", merge_codex_stop_gate(codex_hooks, codex_stop, dry_run=False))
            self.assertEqual([FOREIGN_IMPORTER, codex_cmd], _commands(codex_hooks, "PreToolUse"))
            self.assertEqual([FOREIGN_STOP, codex_stop], _commands(codex_hooks, "Stop"))

    def test_foreign_companion_permissions_survive_while_deleted_moru_and_agy_wildcard_entries_are_pruned(self) -> None:
        from support.permission_entries import agy_legacy_permission_entries, agy_permission_entries
        from support.setup_config_files import merge_permissions_allow

        foreign_hook = "command(python3 /opt/vendor-a/adapters/companion-hook.py)"
        stale_deleted_test = "command(SPILL_AI_TOOL=antigravity python3 tests/test_workflow_routing.py:*)"
        stale_agy_wildcard = "command(vibeguard:*)"
        self._write({"permissions": {"allow": [foreign_hook, stale_deleted_test, stale_agy_wildcard]}})
        status = merge_permissions_allow(
            self.settings,
            agy_permission_entries(ROOT / "scripts", spill_available=True),
            dry_run=False,
            cleanup_entries=agy_legacy_permission_entries(ROOT / "scripts"),
        )
        allow = json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"]
        self.assertEqual("installed", status)
        self.assertIn(foreign_hook, allow)
        self.assertNotIn(stale_deleted_test, allow)
        self.assertNotIn(stale_agy_wildcard, allow)


class RuntimeEnvOwnershipTests(_SettingsFixture, unittest.TestCase):
    def test_env_written_by_another_product_is_not_removed(self) -> None:
        # The removal path fires when Moru cannot find the companion tool's
        # setup helper, which is weaker than that tool being gone -- a moved or
        # restructured install looks identical. With no record that Moru wrote
        # these keys, a matching value is a resemblance, not a receipt.
        self._write({"env": {"SPILL_AI_TOOL": "claude", "SPILL_TOKEN_USAGE_AI_TOOL": "claude"}})
        status = _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("ok", status)
        self.assertEqual("claude", config["env"]["SPILL_AI_TOOL"])

    def test_env_this_installer_wrote_is_removed(self) -> None:
        self._write({"env": {"EDITOR": "vim"}})
        _set_claude_env(self.settings, dry_run=False)
        _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("SPILL_AI_TOOL", config.get("env", {}))
        self.assertEqual("vim", config["env"]["EDITOR"])

    def test_a_key_that_already_existed_is_left_behind(self) -> None:
        # Moru refreshes the pair, but only the key it introduced is its own.
        self._write({"env": {"SPILL_AI_TOOL": "claude"}})
        _set_claude_env(self.settings, dry_run=False)
        _remove_claude_env(self.settings, dry_run=False)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual("claude", config["env"]["SPILL_AI_TOOL"])


class CodexMarkerBlockTests(unittest.TestCase):
    def test_foreign_config_outside_the_marker_block_survives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                'model = "gpt-5"\n'
                '[hooks]\n'
                f'stop = "{FOREIGN_IMPORTER}"\n',
                encoding="utf-8",
            )
            for _ in range(3):
                merge_codex_prefix_rules(config, ['"moru-hook"'], dry_run=False)
            text = config.read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5"', text)
            self.assertIn(FOREIGN_IMPORTER, text)
            self.assertEqual(1, text.count("# moru-hooks:begin"))
            self.assertEqual(1, text.count('"moru-hook"'))


if __name__ == "__main__":
    unittest.main()
