"""Armed Live: Moru arms a device without building, and an agent's worktree starts, uses and hands back Live.

The costly mistakes are building when nobody asked (the old switch), two
worktrees fighting over one device, an agent waiting on a device another
worktree holds, and rebuilding a device this worktree already runs. Each is
tested through ``live_device.main`` with Moru played by the test.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import live_device  # noqa: E402
import live_device_arm  # noqa: E402


class LiveDeviceArmTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.project = root / "work-a"
        self.other = root / "work-b"
        self.project.mkdir()
        self.other.mkdir()
        self.data = root / "moru"
        patcher = mock.patch.dict(os.environ, {"MORU_LIVE_DEVICE_DIR": str(self.data / "live-device")})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Both folders count as one repository, as worktrees of one project do.
        key = mock.patch.object(live_device_arm, "repo_key", return_value="/repo/.git")
        key.start()
        self.addCleanup(key.stop)
        self.box = self.data / "live-device"

    def arm(self, owner: Path | None = None, state: str = "armed", task: Path | None = None) -> None:
        self.box.mkdir(parents=True, exist_ok=True)
        device = {"task": str(task or self.project), "repo": "/repo/.git", "platform": "android", "device": "emulator-5554",
                  "owner": str(owner) if owner else None, "state": state}
        (self.box / "armed.json").write_text(json.dumps({"devices": [device]}))

    def requests(self) -> list[dict]:
        return [json.loads(path.read_text()) for path in sorted((self.box / "requests").glob("*.json"))] \
            if (self.box / "requests").is_dir() else []

    def ready(self, time: str = "2099-01-01T00:00:00Z") -> None:
        log = live_device.events_log(self.project)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as handle:
            handle.write(json.dumps({"time": time, "platform": "android", "device": "emulator-5554",
                                     "event": {"event": "ready", "package": "dev.moru.market", "pid": 7}}) + "\n")

    def run_cli(self, *args: str, project: Path | None = None) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = live_device.main([args[0], "--project", str(project or self.project), *args[1:]])
        return code, output.getvalue().strip()

    def test_without_arming_start_says_to_build_as_usual(self) -> None:
        code, output = self.run_cli("start")
        self.assertEqual(code, live_device.MISSING_EXIT)
        self.assertIn("not armed", output)
        self.assertEqual(self.requests(), [])

    def test_an_armed_device_waits_for_start_then_runs_from_the_asking_worktree(self) -> None:
        self.arm()
        self.assertEqual(self.run_cli("status")[0], live_device.ARMED_EXIT)

        def moru(_seconds: float) -> None:
            # Moru takes the request: the asking worktree owns the device and its plugin gets ready.
            if self.requests() and json.loads((self.box / "armed.json").read_text())["devices"][0]["owner"] is None:
                self.assertEqual(self.requests()[0]["action"], "start")
                self.assertEqual(self.requests()[0]["project"], str(self.project))
                self.arm(owner=self.project, state="ready")
                self.ready()

        with mock.patch.object(live_device_arm.time, "sleep", side_effect=moru):
            code, output = self.run_cli("start", "--link", "moru://cart")
        self.assertEqual(code, 0, output)
        self.assertEqual(output, "android emulator-5554: ready for dev.moru.market")
        self.assertEqual(self.requests()[0]["link"], "moru://cart")
        self.assertEqual(self.run_cli("status")[0], 0)

    def test_another_worktree_is_told_busy_at_once_and_asks_nothing(self) -> None:
        # The device runs from an agent's worktree, not from the Task folder, and that agent is working.
        self.arm(owner=self.project, state="ready", task=Path("/work/task"))
        working = mock.patch.object(live_device_arm, "unsettled_run_states", return_value=["running"])
        working.start()
        self.addCleanup(working.stop)
        code, output = self.run_cli("start", project=self.other)
        self.assertEqual(code, live_device.BUSY_EXIT)
        self.assertIn(f"busy, run from {self.project}", output)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.run_cli("status", project=self.other)[0], live_device.BUSY_EXIT)
        self.assertEqual(self.run_cli("open", "--link", "moru://x", project=self.other)[0], live_device.MISSING_EXIT)

    def test_the_owning_worktree_starts_again_without_a_rebuild_and_can_open_and_stop(self) -> None:
        self.arm(owner=self.project, state="ready")
        self.ready("2026-10-16T01:00:00Z")
        code, output = self.run_cli("start")
        self.assertEqual((code, output), (0, "android emulator-5554: ready for dev.moru.market"))
        self.assertEqual(self.requests(), [])

        self.assertEqual(self.run_cli("open", "--link", "moru://product/7")[0], 0)
        self.assertEqual(self.run_cli("stop")[0], 0)
        self.assertEqual([(r["action"], r["link"]) for r in self.requests()].count(("open", "moru://product/7")), 1)
        self.assertIn(("stop", None), [(r["action"], r["link"]) for r in self.requests()])

    def test_live_the_task_folder_runs_moves_to_a_new_worktree_and_check_never_calls_it_off(self) -> None:
        # Someone reviews on the Task folder (self.other); an agent then works in its worktree (self.project).
        self.arm(owner=self.other, state="ready", task=self.other)
        code, output = self.run_cli("status")
        self.assertEqual(code, live_device.ARMED_EXIT)
        self.assertIn("run live_device.py start to move it to this worktree", output)
        code, output = self.run_cli("check", "--files", "app/src/main/java/A.kt")
        self.assertEqual(code, live_device.ARMED_EXIT)
        self.assertNotIn("Live is off", output)

        def moru(_seconds: float) -> None:
            if self.requests() and json.loads((self.box / "armed.json").read_text())["devices"][0]["owner"] == str(self.other):
                self.arm(owner=self.project, state="ready", task=self.other)
                self.ready()

        with mock.patch.object(live_device_arm.time, "sleep", side_effect=moru):
            code, output = self.run_cli("start")
        self.assertEqual((code, output), (0, "android emulator-5554: ready for dev.moru.market"))
        self.assertEqual(self.requests()[0]["action"], "start")

    def test_moru_not_answering_is_reported_instead_of_waiting_forever(self) -> None:
        self.arm()
        with mock.patch.object(live_device_arm.time, "sleep"), \
                mock.patch.object(live_device_arm.time, "monotonic", side_effect=[0.0, 0.0, 100.0, 100.0]):
            code, output = self.run_cli("start")
        self.assertEqual(code, live_device.MISSING_EXIT)
        self.assertIn("Devices tool must be open", output)


if __name__ == "__main__":
    unittest.main()
