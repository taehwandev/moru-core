"""Test the generated stable entrypoint with real compiled native execution."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from checkout_identity_support import PROJECT, PYTHON, CheckoutFixtures, invoke, request, rows
from native_launcher_support import NATIVE, copied_build_root, fixture_root, install, run_launcher
from support.native_launcher_install import artifact_plan
from support.stable_launcher import _launcher_script_text
from support.stable_launcher import stable_launcher_path
import claude_worktree_gate as gate


class NativeStableLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NATIVE.is_file():
            raise AssertionError("build the actual native runtime before testing")
        cls.shared = tempfile.TemporaryDirectory(prefix="native-ingress-git-")
        cls.git = CheckoutFixtures(cls.shared.name)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="native-ingress-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.home = self.base / "home space 한글"
        self.launcher = self.home / ".moru/bin/moru-hook"
        install(self.home)
        self.assertTrue(self.launcher.read_text().startswith("#!/bin/sh\n"))
        self.assertTrue((self.launcher.parent / "moru-hook-native").is_file())

    def run_cli(self, *args, **kwargs):
        return run_launcher(self.launcher, self.home, *args, **kwargs)

    def test_checkout_fast_path_and_python_rollback_match(self):
        for root in (self.git.main, self.git.linked, self.git.detached):
            with self.subTest(root=root.name):
                payload = request(root)
                expected = rows(invoke(PYTHON, payload))
                self.assertEqual(expected, rows(self.run_cli("checkout-identity", data=payload)))
                self.assertEqual(expected, rows(self.run_cli("checkout-identity", data=payload, backend="python")))
                self.assertEqual(expected, rows(self.run_cli("checkout-identity", data=payload, metadata="python")))

    def test_native_fast_path_has_no_python_or_toolchain_on_path(self):
        empty = self.base / "empty-path"
        empty.mkdir()
        expected = rows(invoke(PYTHON, request(self.git.main)))
        self.assertEqual(expected, rows(self.run_cli("checkout-identity", data=request(self.git.main), path=empty)))

    def test_legacy_stdio_argv_cwd_env_and_process_parent_are_preserved(self):
        root = fixture_root(self.base / "fixture root", "import json,os,sys\n"
                            "print(json.dumps({'ppid':os.getppid(),'argv':sys.argv,'stdin':sys.stdin.read(),"
                            "'cwd':os.getcwd(),'sentinel':os.environ['INGRESS_SENTINEL']}))\n")
        for backend in ("auto", "rust"):
            result = self.run_cli("workflow", "argument with space", "--flag", data=b"retained stdin\n",
                                  cwd=self.base, backend=backend, MORU_HOME=str(root), INGRESS_SENTINEL="retained")
            report = rows(result)[0]
            self.assertEqual(os.getpid(), report["ppid"])
            self.assertEqual([str(root.resolve() / "scripts/workflow.py"), "argument with space", "--flag"], report["argv"])
            self.assertEqual("retained stdin\n", report["stdin"])
            self.assertEqual(str(self.base.resolve()), report["cwd"])
            self.assertEqual("retained", report["sentinel"])

    def test_legacy_failures_crashes_and_soft_fail_are_preserved(self):
        root = fixture_root(self.base / "fixture", "raise SystemExit(7)\n")
        self.assertEqual(7, self.run_cli("workflow", MORU_HOME=str(root)).returncode)
        self.assertEqual(0, self.run_cli("workflow", MORU_HOME=str(root), soft="1").returncode)
        self.assertEqual(7, self.run_cli("workflow", backend="rust", MORU_HOME=str(root)).returncode)
        self.assertEqual(0, self.run_cli("workflow", backend="rust", MORU_HOME=str(root), soft="1").returncode)
        (root / "scripts/workflow.py").write_text("raise RuntimeError('fixture failure')\n")
        crashed = self.run_cli("workflow", MORU_HOME=str(root))
        self.assertEqual(1, crashed.returncode)
        self.assertIn(b"RuntimeError: fixture failure", crashed.stderr)
        self.assertEqual(0, self.run_cli("workflow", MORU_HOME=str(root), soft="1").returncode)

    def test_legacy_signal_is_not_converted_to_a_successful_exit(self):
        root = fixture_root(self.base / "fixture", "import os,signal\nos.kill(os.getpid(),signal.SIGTERM)\n")
        self.assertEqual(-signal.SIGTERM, self.run_cli("workflow", backend="rust", MORU_HOME=str(root)).returncode)

    def test_help_unknown_alias_and_empty_args_match_python_reference(self):
        for arguments in (("--help",), ("help",), ("missing-alias",), ()):
            with self.subTest(arguments=arguments):
                python = self.run_cli(*arguments, backend="python")
                for backend in ("auto", "rust"):
                    rust = self.run_cli(*arguments, backend=backend)
                    self.assertEqual((python.returncode, python.stdout, python.stderr),
                                     (rust.returncode, rust.stdout, rust.stderr))

    def test_native_usage_backend_validation_and_soft_fail(self):
        self.assertEqual(0, self.run_cli("checkout-identity", "--help").returncode)
        self.assertEqual(2, self.run_cli("checkout-identity", "--bad").returncode)
        self.assertEqual(0, self.run_cli("checkout-identity", "--bad", soft="1").returncode)
        for backend in ("auto", "python", "rust"):
            self.assertEqual(2, self.run_cli("checkout-identity", backend=backend, metadata="invalid").returncode)
        self.assertEqual(2, self.run_cli("--help", backend="invalid").returncode)

    def test_checkout_help_matches_both_python_rollback_paths(self):
        native = self.run_cli("checkout-identity", "--help")
        for options in ({"backend": "python"}, {"metadata": "python"}):
            python = self.run_cli("checkout-identity", "--help", **options)
            self.assertEqual((native.returncode, native.stdout, native.stderr),
                             (python.returncode, python.stdout, python.stderr))

    def test_missing_native_falls_back_and_forced_native_reports_absence(self):
        (self.launcher.parent / "moru-hook-native").unlink()
        expected = rows(invoke(PYTHON, request(self.git.main)))
        self.assertEqual(expected, rows(self.run_cli("checkout-identity", data=request(self.git.main))))
        self.assertEqual(127, self.run_cli("checkout-identity", backend="rust").returncode)

    def test_failed_native_execution_is_not_replayed_in_python(self):
        native = self.launcher.parent / "moru-hook-native"
        native.write_text("#!/bin/sh\nread consumed\nexit 23\n")
        native.chmod(0o755)
        result = self.run_cli("checkout-identity", data=request(self.git.main))
        self.assertEqual(23, result.returncode)
        self.assertEqual(b"", result.stdout)

    def test_explicit_python_can_execute_the_polyglot_launcher(self):
        result = subprocess.run([sys.executable, str(self.launcher), "--help"],
                                capture_output=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(b"checkout-identity", result.stdout)

    def test_path_lookup_import_does_not_load_installer_or_template(self):
        code = ("import sys; from support.stable_launcher import stable_launcher_path; "
                "assert 'support.native_launcher_install' not in sys.modules; "
                "assert 'support.launcher_python' not in sys.modules")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=PROJECT,
                                env=dict(os.environ, PYTHONPATH=str(PROJECT / "scripts")),
                                capture_output=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_native_input_io_failure_preserves_hook_soft_fail(self):
        for soft, expected in (("0", 1), ("1", 0)):
            descriptor = os.open(self.home, os.O_RDONLY)
            try:
                env = dict(os.environ, HOME=str(self.home), MORU_HOOK_SOFT_FAIL=soft,
                           MORU_LAUNCHER_BACKEND="rust", MORU_CHECKOUT_IDENTITY_BACKEND="rust")
                result = subprocess.run([str(self.launcher), "checkout-identity"], stdin=descriptor,
                                        capture_output=True, env=env, timeout=5)
                self.assertEqual(expected, result.returncode, result.stderr)
            finally:
                os.close(descriptor)

    def test_setup_is_idempotent_and_dry_run_does_not_create_a_home(self):
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertTrue(all(r["status"] == "ok" for r in install(self.home)))
        after = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        dry_home = self.base / "dry home"
        self.assertTrue(all(r["status"] == "missing" for r in install(dry_home, dry_run=True)))
        self.assertFalse(dry_home.exists())

    def test_stale_sources_and_tampered_artifacts_do_not_enable_native(self):
        root = copied_build_root(self.base / "build fixture")
        self.assertIsNotNone(artifact_plan(root, self.base / "target"))
        source = root / "native/checkout-identity/src/launcher_main.rs"
        original = source.read_text()
        source.write_text(original + "\n// stale build\n")
        self.assertIsNone(artifact_plan(root, self.base / "target"))
        home = self.base / "stale home"
        install(home, root)
        self.assertTrue((home / ".moru/bin/moru-hook").read_text().startswith("#!/usr/bin/env python3"))
        source.write_text(original)
        (root / ".moru/native/bin/moru-native-launcher").write_bytes(b"tampered")
        self.assertIsNone(artifact_plan(root, self.base / "target"))

    def test_corrupted_installed_native_is_reported_and_repaired(self):
        native = self.launcher.parent / "moru-hook-native"
        native.write_bytes(b"broken")
        self.assertEqual("missing", install(self.home, dry_run=True)[0]["status"])
        self.assertEqual("installed", install(self.home)[0]["status"])
        self.assertEqual(hashlib.sha256(NATIVE.read_bytes()).digest(), hashlib.sha256(native.read_bytes()).digest())

    def test_inventory_covers_each_unique_entry_owner_once(self):
        tree = ast.parse(_launcher_script_text())
        aliases = next(ast.literal_eval(n.value) for n in tree.body
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SCRIPT_ALIASES" for t in n.targets))
        expected = {"scripts/" + p for p in aliases.values()} | {"scripts/support/stable_launcher.py"}
        document = (PROJECT / "docs/native-runtime-migration.md").read_text()
        covered = [line.split("|")[2].strip().strip("`") for line in document.splitlines()
                   if line.startswith("| ") and line.split("|")[1].strip().isdigit()
                   and int(line.split("|")[1].strip()) <= 30]
        self.assertEqual(30, len(covered))
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(expected, set(covered))

    def test_inventory_covers_all_direct_python_entrypoints(self):
        tree = ast.parse(_launcher_script_text())
        aliases = next(ast.literal_eval(n.value) for n in tree.body
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SCRIPT_ALIASES" for t in n.targets))
        owners = {"scripts/" + path for path in aliases.values()}
        paths = subprocess.check_output(["git", "ls-files", "--", "scripts"], cwd=PROJECT, text=True).splitlines()
        for path in paths:
            if not path.endswith(".py"):
                continue
            module = ast.parse((PROJECT / path).read_text())
            for node in module.body:
                if (isinstance(node, ast.If)
                        and any(isinstance(n, ast.Name) and n.id == "__name__" for n in ast.walk(node.test))
                        and any(isinstance(n, ast.Constant) and n.value == "__main__" for n in ast.walk(node.test))):
                    owners.add(path)
        owners.add("scripts/support/stable_launcher.py")
        document = (PROJECT / "docs/native-runtime-migration.md").read_text()
        covered = [line.split("|")[2].strip().strip("`") for line in document.splitlines()
                   if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
        self.assertEqual(53, len(covered))
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(owners, set(covered))

    def test_trusted_native_lookup_is_recognized_as_read_only(self):
        for suffix in ("checkout-identity", "checkout-identity --help"):
            command = f"{stable_launcher_path()} {suffix}"
            cwd, tokens, simple = gate.bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
            self.assertEqual("read_only", gate.bash_command_kind(tokens, simple, cwd))

    def test_native_lookup_recognition_does_not_allow_impostors_or_writes(self):
        for command in ("/tmp/moru-hook checkout-identity", f"{stable_launcher_path()} checkout-identity --bad"):
            cwd, tokens, simple = gate.bash_invocation({"tool_input": {"command": command}}, Path("/tmp"))
            self.assertNotEqual("read_only", gate.bash_command_kind(tokens, simple, cwd))
        redirected = f"{stable_launcher_path()} checkout-identity > /tmp/not-created"
        self.assertIn(Path("/tmp/not-created"), gate.raw_path_arguments(redirected))


if __name__ == "__main__":
    unittest.main()
