from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_preflight_runtime import _claude_spill_warnings, _missing_allow_entries


class MissingAllowEntriesTests(unittest.TestCase):
    def test_reports_only_entries_absent_from_allow(self) -> None:
        config = {"permissions": {"allow": ["Bash(git status)", "Bash(git log *)"]}}
        entries = ["Bash(git status)", "Bash(pytest)", "Bash(git log *)"]

        self.assertEqual(["Bash(pytest)"], _missing_allow_entries(config, entries))

    def test_missing_or_malformed_permissions_reports_all_entries(self) -> None:
        entries = ["Bash(pytest)"]

        self.assertEqual(entries, _missing_allow_entries({}, entries))
        self.assertEqual(
            entries, _missing_allow_entries({"permissions": "not-a-dict"}, entries)
        )
        self.assertEqual(
            entries,
            _missing_allow_entries({"permissions": {"allow": "not-a-list"}}, entries),
        )

    def test_malformed_allow_elements_are_ignored_without_crashing(self) -> None:
        config = {
            "permissions": {
                "allow": [
                    "Bash(git status)",
                    {"unexpected": "object"},
                    ["unexpected-list"],
                    None,
                    42,
                ]
            }
        }

        self.assertEqual(
            ["Bash(pytest)"],
            _missing_allow_entries(config, ["Bash(git status)", "Bash(pytest)"]),
        )

    def test_large_allow_list_does_not_regress_to_quadratic_scan(self) -> None:
        # Regression: checking each of N required entries with `entry not in
        # allow` against a plain list is O(N * len(allow)). A real AGY config
        # observed in the field had grown to 17,547 allow entries (2.2MB);
        # at that size the naive per-entry list scan alone measured ~0.16s
        # for a single call, and this runs on every `start` hook. Hashing
        # `allow` into a set once must keep this near-instant regardless of
        # how large the config has grown.
        allow = [f"Bash(tool-{index})" for index in range(20_000)]
        config = {"permissions": {"allow": allow}}
        entries = [f"Bash(tool-{index})" for index in range(0, 20_000, 2)] + [
            "Bash(missing-one)",
            "Bash(missing-two)",
        ]

        start = time.perf_counter()
        missing = _missing_allow_entries(config, entries)
        elapsed = time.perf_counter() - start

        self.assertEqual(["Bash(missing-one)", "Bash(missing-two)"], missing)
        self.assertLess(elapsed, 0.05, f"expected a near-instant set lookup, took {elapsed:.3f}s")


class ClaudeSpillHookTests(unittest.TestCase):
    def test_current_advisory_hook_is_recognized(self) -> None:
        config = {
            "env": {"SPILL_AI_TOOL": "claude"},
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "command": (
                                    "SPILL_AI_TOOL=claude moru-hook workflow route "
                                    "triage --advisory"
                                )
                            }
                        ]
                    }
                ]
            },
        }

        self.assertEqual([], _claude_spill_warnings(config, ROOT))

    def test_retired_classified_hook_is_reported_for_migration(self) -> None:
        config = {
            "env": {"SPILL_AI_TOOL": "claude"},
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "command": (
                                    "SPILL_AI_TOOL=claude moru-hook workflow route triage "
                                    "--request-classified --classification-evidence safe"
                                )
                            }
                        ]
                    }
                ]
            },
        }

        warnings = _claude_spill_warnings(config, ROOT)

        self.assertTrue(any("--advisory" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
