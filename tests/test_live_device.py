"""live_device.py tells an agent whether Android/iOS Live runs and whether its save reached the app.

The costly mistakes are calling a failed save done, missing that Live is on
(and rebuilding the app under it), and reading a stale result from before the
save. Each rule is tested through the CLI entry point on a hand-written log.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import live_device  # noqa: E402


class LiveDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()

    def log(self, platform: str, device: str, time: str, event: dict) -> None:
        path = live_device.events_log(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps({"time": time, "platform": platform, "device": device, "event": event}) + "\n")

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = live_device.main([args[0], "--project", str(self.project), *args[1:]])
        return code, output.getvalue().strip()

    def start_both(self) -> None:
        self.log("android", "emulator-5554", "2026-10-16T01:00:00Z", {"event": "ready", "package": "dev.moru.market", "pid": 1})
        self.log("ios", "SIM-1", "2026-10-16T01:00:02Z", {"event": "ready", "package": "dev.moru.market", "pid": 2})

    def test_status_is_off_without_a_log_or_after_every_device_stopped(self) -> None:
        self.assertEqual(self.run_cli("status"), (live_device.MISSING_EXIT, "Live is off"))
        self.start_both()
        self.log("android", "emulator-5554", "2026-10-16T01:05:00Z", {"event": "stopped", "reason": "asked"})
        code, output = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(output, "ios SIM-1: Live on for dev.moru.market, last ready 2026-10-16T01:00:02Z")
        self.log("ios", "SIM-1", "2026-10-16T01:06:00Z", {"event": "stopped", "reason": "stopped"})
        self.assertEqual(self.run_cli("status")[0], live_device.MISSING_EXIT)

    def test_check_is_ok_only_when_every_live_device_applied_the_saved_files(self) -> None:
        self.start_both()
        self.log("android", "emulator-5554", "2026-10-16T01:01:00Z", {"event": "applied", "files": ["app/src/main/java/Banner.kt"], "ms": 1564})
        code, output = self.run_cli("check", "--files", "Banner.kt", "MoruMarket/Banner.swift")
        self.assertEqual(code, live_device.MISSING_EXIT, "iOS has not answered yet")
        self.assertIn("ios SIM-1: no result yet", output)
        self.log("ios", "SIM-1", "2026-10-16T01:01:01Z", {"event": "applied", "files": ["MoruMarket/Banner.swift"], "ms": 1253})
        code, output = self.run_cli("check", "--files", "Banner.kt", "MoruMarket/Banner.swift")
        self.assertEqual(code, 0)
        self.assertIn("android emulator-5554: applied 2026-10-16T01:01:00Z app/src/main/java/Banner.kt in 1.6s", output)

    def test_a_compile_error_or_a_waiting_rebuild_is_a_problem_but_an_ios_relaunch_is_not(self) -> None:
        self.start_both()
        self.log("ios", "SIM-1", "2026-10-16T01:02:00Z", {"event": "failed", "files": ["Card.swift"], "reason": "compile",
                                                          "detail": "Card.swift:11:30: error: no member 'nam'\nmore"})
        self.log("android", "emulator-5554", "2026-10-16T01:02:00Z", {"event": "needs_rebuild", "files": ["res/values/strings.xml"], "reason": "resources"})
        code, output = self.run_cli("check")
        self.assertEqual(code, live_device.PROBLEM_EXIT)
        self.assertIn("detail: Card.swift:11:30: error: no member 'nam'", output)
        self.assertIn("waits for Rebuild in Moru", output)
        self.log("ios", "SIM-1", "2026-10-16T01:03:00Z", {"event": "needs_rebuild", "files": ["Card.swift"], "reason": "storage"})
        self.log("ios", "SIM-1", "2026-10-16T01:03:05Z", {"event": "ready", "package": "dev.moru.market", "pid": 3})
        code, output = self.run_cli("check", "--files", "Card.swift")
        self.assertEqual(code, live_device.MISSING_EXIT, "Android never saw Card.swift")
        self.assertIn("rebuilt and relaunched", output)

    def test_since_ignores_results_from_before_the_save_and_applying_is_pending(self) -> None:
        self.start_both()
        for device, platform in (("emulator-5554", "android"), ("SIM-1", "ios")):
            self.log(platform, device, "2026-10-16T01:01:00Z", {"event": "applied", "files": ["Price.kt", "Price.swift"]})
        self.assertEqual(self.run_cli("check", "--since", "2026-10-16T01:02:00Z")[0], live_device.MISSING_EXIT)
        self.log("ios", "SIM-1", "2026-10-16T01:02:01Z", {"event": "applying", "files": ["Price.swift"]})
        code, output = self.run_cli("check", "--files", "Price.swift", "--json")
        self.assertEqual(code, live_device.MISSING_EXIT)
        self.assertEqual(json.loads(output)["devices"]["ios SIM-1"]["state"], "pending")

    def test_malformed_lines_are_skipped(self) -> None:
        self.start_both()
        with live_device.events_log(self.project).open("a") as handle:
            handle.write("not json\n{\"event\": 3}\n")
        self.assertEqual(self.run_cli("status")[0], 0)


if __name__ == "__main__":
    unittest.main()
