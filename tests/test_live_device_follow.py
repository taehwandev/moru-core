"""Live follows an agent's worktree when its mobile UI run starts, and only then.

The costly mistakes are an agent that does no app work taking the device,
taking it from an agent that is working with it, and not taking it from the
Task folder or a finished worktree, which made the user move it by hand. Each
is tested against a real git repository with a linked worktree; Moru is the
test's armed.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import live_device_arm  # noqa: E402
import live_device_follow  # noqa: E402


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class LiveDeviceFollowTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.main = root / "shop"
        self.main.mkdir()
        git("init", "-q", cwd=self.main)
        (self.main / "README.md").write_text("shop")
        git("add", "-A", cwd=self.main)
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init", cwd=self.main)
        self.worktree = root / "shop-cart"
        git("worktree", "add", "-q", "-b", "cart", str(self.worktree), cwd=self.main)
        self.box = root / "live-device"
        patcher = mock.patch.dict(os.environ, {"MORU_LIVE_DEVICE_DIR": str(self.box)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def arm(self, owner: Path | None) -> None:
        self.box.mkdir(parents=True, exist_ok=True)
        device = {"task": str(self.main), "repo": live_device_arm.repo_key(self.main), "platform": "android",
                  "device": "emulator-5554", "owner": str(owner) if owner else None, "state": "ready"}
        (self.box / "armed.json").write_text(json.dumps({"devices": [device]}))

    def requests(self) -> list[dict]:
        folder = self.box / "requests"
        return [json.loads(p.read_text()) for p in folder.glob("*.json")] if folder.is_dir() else []

    def test_a_mobile_ui_run_in_a_worktree_moves_live_from_the_task_folder(self) -> None:
        self.arm(owner=self.main)
        lines = live_device_follow.on_start(self.worktree, ["kmp"], [])
        self.assertEqual(len(lines), 1)
        self.assertIn("moving android emulator-5554 to this worktree", lines[0])
        request = self.requests()[0]
        self.assertEqual((request["action"], request["project"], request["takeover"]), ("start", str(self.worktree), []))

    def test_other_work_the_main_checkout_and_live_off_never_take_the_device(self) -> None:
        self.arm(owner=self.main)
        self.assertEqual(live_device_follow.on_start(self.worktree, ["python"], ["documentation"]), [])
        self.assertEqual(live_device_follow.on_start(self.main, ["android"], []), [])
        (self.box / "armed.json").unlink()
        self.assertEqual(live_device_follow.on_start(self.worktree, ["ios"], []), [])
        self.assertEqual(self.requests(), [])

    def test_a_ui_concern_counts_without_a_platform(self) -> None:
        self.arm(owner=None)
        self.assertEqual(len(live_device_follow.on_start(self.worktree, [], ["compose"])), 1)

    def test_a_working_agent_keeps_live_and_a_finished_or_removed_worktree_hands_it_over(self) -> None:
        other = self.worktree.parent / "shop-search"
        git("worktree", "add", "-q", "-b", "search", str(other), cwd=self.main)
        self.arm(owner=other)
        with mock.patch.object(live_device_arm, "unsettled_run_states", return_value=["running"]):
            self.assertEqual(live_device_follow.on_start(self.worktree, ["android"], []), [])
        with mock.patch.object(live_device_arm, "unsettled_run_states", return_value=["failed"]):
            self.assertEqual(len(live_device_follow.on_start(self.worktree, ["android"], [])), 1)
        self.assertEqual(self.requests()[0]["takeover"], ["emulator-5554"])

        git("worktree", "remove", "--force", str(other), cwd=self.main)
        device = json.loads((self.box / "armed.json").read_text())["devices"][0]
        self.assertTrue(live_device_arm.idle_owner(device))

    def test_the_worktree_check_tells_a_linked_worktree_from_the_main_checkout(self) -> None:
        self.assertTrue(live_device_follow.linked_worktree(self.worktree))
        self.assertFalse(live_device_follow.linked_worktree(self.main))
        self.assertFalse(live_device_follow.linked_worktree(self.box.parent))


if __name__ == "__main__":
    unittest.main()
