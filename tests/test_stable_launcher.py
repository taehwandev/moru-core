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

from support.stable_launcher import (
    ensure_stable_launcher,
    moru_launcher_path,
    moru_root_pointer_path,
    preferred_launcher_path,
    stable_launcher_path,
    stable_root_pointer_path,
)


class StableLauncherTests(unittest.TestCase):
    def test_ready_global_state_prefers_moru_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_home:
            with patch.dict(os.environ, {"HOME": temporary_home}):
                # A new install has no legacy launcher to keep using.
                self.assertEqual(moru_launcher_path(), preferred_launcher_path())
                (Path(temporary_home) / ".tao").mkdir()
                self.assertEqual(stable_launcher_path(), preferred_launcher_path())
                state = Path(temporary_home) / ".moru"
                state.mkdir()
                (state / "state-ready").write_text("ready\n")
                self.assertEqual(moru_launcher_path(), preferred_launcher_path())

    def test_new_and_legacy_launchers_share_a_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_home:
            with patch.dict(os.environ, {"HOME": temporary_home}):
                first = ensure_stable_launcher(ROOT, dry_run=False)
                old_launcher = stable_launcher_path()
                new_launcher = moru_launcher_path()
                old_pointer = stable_root_pointer_path()
                new_pointer = moru_root_pointer_path()
                self.assertEqual({"installed"}, {row["status"] for row in first})
                self.assertEqual(f"{ROOT.resolve()}\n", old_pointer.read_text())
                self.assertEqual(old_pointer.read_text(), new_pointer.read_text())
                self.assertTrue(os.access(old_launcher, os.X_OK))
                self.assertTrue(os.access(new_launcher, os.X_OK))
                self.assertIn('os.environ.get("TAO_" + name[len("MORU_"):])', old_launcher.read_text())
                self.assertIn('STATE_DIR_NAME = ".moru"', new_launcher.read_text())
                self.assertIn('os.environ.setdefault("MORU_HOME", str(root))', new_launcher.read_text())
                self.assertEqual({"ok"}, {
                    row["status"] for row in ensure_stable_launcher(ROOT, dry_run=True)
                })

                environment = dict(os.environ)
                environment.pop("MORU_HOME", None)
                environment.pop("TAO_HOME", None)
                result = subprocess.run(
                    [str(new_launcher), "workflow", "validate"],
                    cwd=temporary_home, env=environment, capture_output=True,
                    text=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("OK:", result.stdout)

    def test_launcher_resolves_the_dynamic_home_root_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_home:
            with patch.dict(os.environ, {"HOME": temporary_home}):
                ensure_stable_launcher(ROOT, dry_run=False)
                launcher = stable_launcher_path()
                pointer = stable_root_pointer_path()
                expected_root = Path(temporary_home) / ".tao"

                self.assertEqual(expected_root / "bin" / "tao-hook", launcher)
                self.assertEqual(expected_root / "tao-root", pointer)

                pointer.write_text("/missing/tao-agent-os\n", encoding="utf-8")
                environment = dict(os.environ)
                environment["MORU_HOOK_SOFT_FAIL"] = "1"
                result = subprocess.run(
                    [str(launcher), "workflow", "validate"],
                    cwd=temporary_home,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )

        self.assertEqual(0, result.returncode)
        self.assertIn("Moru Core hook skipped", result.stderr)
        self.assertNotIn("NameError", result.stderr)


class SharedRootIsNotDowngradedTests(unittest.TestCase):
    """The pointer must not be aimed at a checkout that is about to vanish.

    Every runtime on the machine reads `~/.tao/tao-root`, so pointing it at a
    task worktree leaves the bridge dangling the moment that task is cleaned
    up -- and the repair then needs the tooling the pointer no longer finds.
    It happens by accident, because running the installer from a worktree is
    how you test it and the side effect is machine-wide and silent. It happened
    three times while this gate was being built, and twice the repair had to be
    done by hand.

    Refusing to install from a worktree outright was the first attempt and was
    wrong: developing Moru in a worktree against a throwaway home is ordinary,
    and the block broke it. The loss is narrower -- replacing a durable root
    that still exists with a disposable one -- so only that is refused.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.home = base / "home"
        (self.home / ".tao").mkdir(parents=True)
        self.durable = base / "tao-agent-os"
        (self.durable / ".tao").mkdir(parents=True)
        self.worktree = self.durable / ".tao" / "worktrees" / "abc123def4567890"
        self.worktree.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _install(self, root: Path) -> str:
        with patch("support.stable_launcher.Path.home", return_value=self.home):
            results = ensure_stable_launcher(root, dry_run=False)
        return str(results[0]["status"])

    def _point_at(self, target: Path) -> None:
        (self.home / ".tao" / "tao-root").write_text(f"{target}\n", encoding="utf-8")

    def test_a_durable_root_is_not_replaced_by_a_worktree(self) -> None:
        self._point_at(self.durable)

        self.assertEqual("blocked", self._install(self.worktree))
        # And the pointer is left as it was, not half-written.
        self.assertEqual(
            f"{self.durable}\n",
            (self.home / ".tao" / "tao-root").read_text(encoding="utf-8"),
        )

    def test_moru_pointer_is_not_replaced_by_a_worktree(self) -> None:
        new_pointer = self.home / ".moru" / "moru-root"
        new_pointer.parent.mkdir(parents=True)
        new_pointer.write_text(f"{self.durable}\n", encoding="utf-8")

        self.assertEqual("blocked", self._install(self.worktree))
        self.assertEqual(f"{self.durable}\n", new_pointer.read_text())

    def test_a_first_install_from_a_worktree_still_works(self) -> None:
        # Nothing to lose: developing Moru in a worktree against a throwaway
        # home is what the earlier, broader guard broke.
        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_repeating_the_same_worktree_target_is_not_a_downgrade(self) -> None:
        self._point_at(self.worktree)
        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_one_worktree_may_replace_another(self) -> None:
        # The pointer is already disposable; this loses nothing new.
        other = self.durable / ".tao" / "worktrees" / "0123456789abcdef"
        other.mkdir(parents=True)
        self._point_at(other)

        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_a_pointer_naming_a_vanished_checkout_is_replaceable(self) -> None:
        """A dangling pointer is the damage, not something worth preserving."""

        self._point_at(self.durable / ".tao" / "worktrees" / "deletedaaaaaaaaa")

        self.assertNotEqual("blocked", self._install(self.worktree))

    def test_repointing_back_at_the_main_checkout_is_always_allowed(self) -> None:
        # This is the repair path; refusing it would recreate the deadlock.
        self._point_at(self.worktree)

        self.assertNotEqual("blocked", self._install(self.durable))
        # Resolved, because the installer writes a resolved path and the
        # temporary directory sits behind a symlink on macOS.
        self.assertEqual(
            self.durable.resolve(),
            Path((self.home / ".tao" / "tao-root").read_text(encoding="utf-8").strip()),
        )


class LauncherRunsTheScriptInProcessTests(unittest.TestCase):
    """The launcher is on the hot path, so it must not pay for a second Python.

    A PreToolUse gate runs on every Bash, Edit and Write call, and spawning an
    interpreter to reach the gate script cost 24 ms of the 72 ms that call
    took. What the child gave for free -- the scripts directory on `sys.path`,
    `sys.argv`, an exit code, and a crash the soft-fail switch could absorb --
    is what these tests pin, because losing any of them turns a saved 24 ms
    into a hook that breaks the tool call it was gating.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.home = base / "home"
        (self.home / ".tao").mkdir(parents=True)
        self.root = base / "tao-agent-os"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("markers only\n", encoding="utf-8")
        (self.root / "index.md").write_text("markers only\n", encoding="utf-8")
        self.report = base / "report.json"
        with patch("support.stable_launcher.Path.home", return_value=self.home):
            ensure_stable_launcher(self.root, dry_run=False)
            self.launcher = stable_launcher_path()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_script(self, body: str) -> None:
        (self.root / "scripts" / "workflow.py").write_text(body, encoding="utf-8")

    def _run(self, *arguments: str, soft_fail: bool = False):
        environment = dict(os.environ)
        environment["HOME"] = str(self.home)
        environment["MORU_HOME"] = str(self.root)
        environment["MORU_REPORT"] = str(self.report)
        environment["MORU_HOOK_SOFT_FAIL"] = "1" if soft_fail else "0"
        return subprocess.run(
            [sys.executable, str(self.launcher), "workflow", *arguments],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_script_runs_in_the_launcher_process(self) -> None:
        self._write_script(
            "import json, os, sys\n"
            "json.dump(\n"
            "    {'ppid': os.getppid(), 'argv': sys.argv, 'path0': sys.path[0]},\n"
            "    open(os.environ['MORU_REPORT'], 'w'),\n"
            ")\n"
        )

        result = self._run("validate", "--strict")
        report = json.loads(self.report.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        # A spawned child would report the launcher as its parent. Reporting
        # this test process instead is what proves there was no second Python.
        self.assertEqual(os.getpid(), report["ppid"])
        # Resolved, because the launcher resolves the root it was pointed at
        # and the temporary directory sits behind a symlink on macOS.
        scripts = self.root.resolve() / "scripts"
        self.assertEqual(
            [str(scripts / "workflow.py"), "validate", "--strict"], report["argv"]
        )
        # Every script under scripts/ imports its siblings by bare name, which
        # only works while their directory leads sys.path.
        self.assertEqual(str(scripts), report["path0"])

    def test_a_scripts_exit_code_still_reaches_the_caller(self) -> None:
        self._write_script("import sys\nsys.exit(3)\n")

        self.assertEqual(3, self._run().returncode)

    def test_soft_fail_still_absorbs_a_failing_script(self) -> None:
        self._write_script("import sys\nsys.exit(3)\n")

        self.assertEqual(0, self._run(soft_fail=True).returncode)

    def test_a_crashing_script_reports_the_traceback_and_does_not_escape(self) -> None:
        """In-process, an unhandled error would otherwise be the launcher's."""

        self._write_script("raise RuntimeError('gate is broken')\n")

        result = self._run()

        self.assertEqual(1, result.returncode)
        self.assertIn("RuntimeError: gate is broken", result.stderr)

    def test_soft_fail_absorbs_a_crash_so_a_broken_hook_cannot_brick_a_tool_call(self) -> None:
        self._write_script("raise RuntimeError('gate is broken')\n")

        result = self._run(soft_fail=True)

        self.assertEqual(0, result.returncode)
        self.assertIn("RuntimeError: gate is broken", result.stderr)


if __name__ == "__main__":
    unittest.main()
