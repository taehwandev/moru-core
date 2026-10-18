"""Execution results, source drift and admission through the optional runner."""

import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _moru_test_support import ROOT, TemplateRepository
import agent_verification_hook as verify
from agent_gate_evidence import gate_evidence_path_for_preflight


def _build_fixture(project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".moru/\n__pycache__/\n")
    subprocess.run(["git", "-C", str(project), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)


_FIXTURE = TemplateRepository(_build_fixture)


def _startup_fixture(project):
    environment = project / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    packages = environment / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    marker, env_marker = project / ".moru" / "venv-startup", project / ".moru" / "env-startup"
    (packages / "proof.pth").write_text(
        f"import pathlib; pathlib.Path({str(marker)!r}).write_text('started')\n")
    (packages / "loop_review_dependency.py").write_text("VALUE = 'venv'\n")
    extra = project / ".moru" / "extra-python"
    extra.mkdir()
    (extra / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(env_marker)!r}).write_text('started')\n")
    (extra / "loop_review_env_dependency.py").write_text("VALUE = 'environment'\n")
    return marker, env_marker, extra


def tearDownModule():
    _FIXTURE.cleanup()


class VerificationHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        _FIXTURE.copy_to(self.project)
        (self.project / "tests").mkdir()
        self.path = self.project / ".moru" / "preflight.json"
        self.path.parent.mkdir()
        self.session = {"runtime": "codex", "session_id": "fixture"}
        self.preflight = {"project": str(self.project), "rules": str(self.project),
                          "runtime_session": self.session, "route": {"gates": ["tests"]}}
        self.path.write_text(json.dumps(self.preflight))
        self.args = SimpleNamespace(project=self.project, rules=self.project, evidence=self.path,
                                    test_directory="tests", test_pattern="test_*.py", verify_timeout=5)
        self.addCleanup(patch.stopall)
        patch.object(verify, "runtime_session", return_value=self.session).start()
        self.bound = patch.object(verify, "resolve_runtime_evidence", return_value=self.path).start()

    def run_hook(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return verify.verification_hook(self.args)

    def entries(self):
        return json.loads(gate_evidence_path_for_preflight(self.path).read_text())["entries"]

    def write_test(self, body="self.assertTrue(True)"):
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\nfrom pathlib import Path\nimport time\n"
            f"class Case(unittest.TestCase):\n    def test_case(self):\n        {body}\n")

    def test_pass_records_observed_count_and_failure_replaces_pass(self):
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.assertEqual("SUCCESS", self.entries()[-1]["status"])
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])
        self.write_test("self.fail('expected')")
        self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=1", self.entries()[-1]["fields"]["result"])

    def test_a_failure_records_the_checkpoint_repair_verify_needs(self):
        """The failure output names repair-verify, which refused every checkpoint."""

        from agent_repair_ledger import checkpoint_failure_signature, checkpoint_has_recorded_failure

        route = self.preflight["route"]
        self.write_test("self.fail('expected')")
        self.assertEqual(1, self.run_hook())
        self.assertTrue(checkpoint_has_recorded_failure(route=route, evidence_path=self.path, checkpoint="tests"))
        first = checkpoint_failure_signature(route=route, evidence_path=self.path, checkpoint="tests")
        self.assertEqual(1, self.run_hook())
        # The same failure keeps its signature, so a recurrence is recognisable.
        self.assertEqual(first, checkpoint_failure_signature(route=route, evidence_path=self.path, checkpoint="tests"))

    def test_zero_tests_does_not_pass(self):
        self.assertEqual(1, self.run_hook())
        self.assertIn("tests=0", self.entries()[-1]["fields"]["result"])

    def test_only_skips_or_expected_failures_do_not_pass(self):
        for decorator in ("unittest.skip('unavailable')", "unittest.expectedFailure"):
            with self.subTest(decorator=decorator):
                (self.project / "tests" / "test_case.py").write_text(
                    "import unittest\nclass Case(unittest.TestCase):\n"
                    f"    @{decorator}\n    def test_case(self):\n"
                    "        self.fail('goal not reached')\n")
                self.assertEqual(1, self.run_hook())
                self.assertEqual("FAIL", self.entries()[-1]["status"])
                self.assertIn("exit=0; tests=1", self.entries()[-1]["fields"]["result"])

    def test_real_pass_and_optional_skip_remain_valid(self):
        self.write_test("self.assertTrue(True)\n"
                        "        for item in range(3):\n"
                        "            with self.subTest(item=item):\n"
                        "                self.skipTest('optional subtest')")
        with (self.project / "tests" / "test_case.py").open("a") as output:
            output.write("    @unittest.skip('optional')\n    def test_optional(self):\n        pass\n")
        self.assertEqual(0, self.run_hook())
        self.assertIn("tests=2", self.entries()[-1]["fields"]["result"])

    def test_project_packages_take_priority_over_hook_packages(self):
        (self.project / "tests" / "__init__.py").write_text("")
        (self.project / "tests" / "helper.py").write_text("VALUE = 'project tests'\n")
        support = self.project / "support"
        support.mkdir()
        (support / "__init__.py").write_text("VALUE = 'project support'\n")
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\n"
            "from tests.helper import VALUE as TESTS_VALUE\n"
            "from support import VALUE as SUPPORT_VALUE\n"
            "class Case(unittest.TestCase):\n"
            "    def test_imports(self):\n"
            "        self.assertEqual('project tests', TESTS_VALUE)\n"
            "        self.assertEqual('project support', SUPPORT_VALUE)\n"
        )
        self.assertEqual(0, self.run_hook())
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])

    def test_a_module_only_moru_has_is_not_importable_by_project_tests(self):
        """A project lacking `agent_gate_reuse` must fail, not import Moru's copy."""
        (self.project / "tests" / "test_case.py").write_text(
            "import unittest\n"
            "class Case(unittest.TestCase):\n"
            "    def test_imports(self):\n"
            "        with self.assertRaises(ImportError):\n"
            "            import agent_gate_reuse\n"
            "        with self.assertRaises(ImportError):\n"
            "            import stable_launcher\n"
        )
        self.assertEqual(0, self.run_hook())
        self.assertIn("tests=1", self.entries()[-1]["fields"]["result"])

    def test_project_venv_python_is_selected(self):
        python = self.project / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.assertEqual(str(python), verify.unittest_command(self.args)[0])
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.assertIn(str(python), self.entries()[-1]["fields"]["check"])

    def test_zero_exit_without_receipt_fails_closed(self):
        with patch.object(verify, "unittest_command", return_value=[sys.executable, "-c", "pass"]):
            self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=0; tests=0", self.entries()[-1]["fields"]["result"])

    def test_success_receipt_with_nonzero_exit_fails_closed(self):
        script = (
            "import json,sys; "
            "open(sys.argv[1], 'w').write(json.dumps({'tests_run': 1, 'successful': True})); "
            "sys.exit(1)"
        )
        with patch.object(verify, "unittest_command", return_value=[sys.executable, "-c", script]):
            self.assertEqual(1, self.run_hook())
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertIn("exit=1; tests=1", self.entries()[-1]["fields"]["result"])

    def test_forged_terminal_test_count_does_not_pass(self):
        (self.project / "tests" / "test_case.py").write_text(
            "import atexit\n"
            "atexit.register(lambda: print('Ran 1 test in 0.001s'))\n",
            encoding="utf-8",
        )
        self.assertEqual(1, self.run_hook())
        self.assertIn("tests=0", self.entries()[-1]["fields"]["result"])

    def test_passing_test_that_changes_source_does_not_pass_gate(self):
        self.write_test("Path('changed.py').write_text('changed')")
        self.assertEqual(1, self.run_hook())
        self.assertIn("inputs_unchanged=False", self.entries()[-1]["fields"]["result"])

    def test_timeout_and_interruption_clear_old_success(self):
        self.write_test()
        self.assertEqual(0, self.run_hook())
        self.write_test("time.sleep(2)")
        self.args.verify_timeout = 1
        self.assertEqual(1, self.run_hook())
        self.assertIn("exit=124", self.entries()[-1]["fields"]["result"])
        with patch.object(verify, "execute_unittest", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_hook()
        self.assertEqual("FAIL", self.entries()[-1]["status"])
        self.assertEqual("incomplete", self.entries()[-1]["fields"]["result"])

    def test_foreign_closed_run_or_missing_gate_never_executes(self):
        with patch.object(verify, "execute_unittest") as execute:
            self.bound.return_value = None
            self.assertEqual(1, self.run_hook())
            self.bound.return_value = self.project / "other.json"
            self.assertEqual(1, self.run_hook())
            self.bound.return_value = self.path
            self.preflight["route"]["gates"] = []
            self.path.write_text(json.dumps(self.preflight))
            self.assertEqual(1, self.run_hook())
            execute.assert_not_called()

    def test_directory_escape_or_invalid_pattern_never_executes(self):
        with patch.object(verify, "execute_unittest") as execute:
            self.args.test_directory = ".."
            self.assertEqual(1, self.run_hook())
            self.args.test_directory = "tests"
            self.args.test_pattern = "../test_case.py"
            self.assertEqual(1, self.run_hook())
            execute.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_guarded_admission_precedes_import_and_denial_prevents_project_effect(self):
        effect = self.project / ".moru" / "effect"
        (self.project / "tests" / "test_case.py").write_text(
            "from pathlib import Path\nimport unittest\n"
            "Path('.moru/effect').write_text('imported')\n"
            "class Case(unittest.TestCase):\n    def test_case(self):\n        pass\n")
        admitted = []

        def admit(pid):
            admitted.append(pid)
            self.assertEqual(pid, os.getpgid(pid))
            time.sleep(0.05)
            self.assertFalse(effect.exists())

        with contextlib.redirect_stdout(io.StringIO()):
            result = verify.execute_unittest(verify.unittest_command(self.args), self.project, 5,
                                             process_admission=admit)
        self.assertEqual((0, 1, True), result)
        self.assertTrue(effect.exists())
        effect.unlink()

        def deny(pid):
            admit(pid)
            raise PermissionError("admission denied")

        with self.assertRaisesRegex(PermissionError, "admission denied"):
            verify.execute_unittest(verify.unittest_command(self.args), self.project, 5,
                                     process_admission=deny)
        self.assertFalse(effect.exists())
        with self.assertRaises(ChildProcessError):
            os.waitpid(admitted[-1], os.WNOHANG)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_guarded_callback_time_consumes_deadline_without_releasing_project(self):
        self.write_test("Path('.moru/effect').write_text('bad')")
        with contextlib.redirect_stdout(io.StringIO()):
            result = verify.execute_unittest(verify.unittest_command(self.args), self.project, 0.05,
                                             process_admission=lambda pid: time.sleep(0.1))
        self.assertEqual((124, 0, False), result)
        self.assertFalse((self.project / ".moru" / "effect").exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_denied_admission_prevents_venv_and_pythonpath_startup(self):
        marker, env_marker, extra = _startup_fixture(self.project)
        self.write_test()

        def deny(pid):
            time.sleep(0.1)
            raise PermissionError("admission denied")

        with patch.dict(os.environ, PYTHONPATH=str(extra)):
            with self.assertRaisesRegex(PermissionError, "admission denied"):
                verify.execute_unittest(verify.unittest_command(self.args), self.project, 5,
                                         process_admission=deny)
        self.assertFalse(marker.exists())
        self.assertFalse(env_marker.exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_admission_preserves_normal_venv_and_pythonpath_behavior(self):
        marker, env_marker, extra = _startup_fixture(self.project)
        self.write_test("self.assertEqual('venv', __import__('loop_review_dependency').VALUE)\n"
                        "        self.assertEqual('environment', __import__('loop_review_env_dependency').VALUE)\n"
                        "        self.assertTrue(Path('.moru/venv-startup').exists())\n"
                        "        self.assertTrue(Path('.moru/env-startup').exists())")

        def admit(pid):
            time.sleep(0.1)
            self.assertFalse(marker.exists())
            self.assertFalse(env_marker.exists())

        with patch.dict(os.environ, PYTHONPATH=str(extra)), contextlib.redirect_stdout(io.StringIO()):
            result = verify.execute_unittest(verify.unittest_command(self.args), self.project, 5,
                                             process_admission=admit)
        self.assertEqual((0, 1, True), result)
        self.assertTrue(marker.exists())
        self.assertTrue(env_marker.exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_guarded_runner_eof_never_imports_project(self):
        self.write_test("Path('.moru/effect').write_text('bad')")
        process = subprocess.Popen(
            [*verify.unittest_command(self.args), str(self.project / ".moru" / "receipt")],
            cwd=self.project, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env={**os.environ, "MORU_UNITTEST_ADMISSION": "1"})
        process.stdin.close()
        self.assertEqual(125, process.wait(timeout=5))
        self.assertFalse((self.project / ".moru" / "effect").exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_guarded_keyboard_interrupt_kills_and_reaps_spawned_group(self):
        self.write_test("__import__('os').kill(__import__('os').getppid(), "
                        "__import__('signal').SIGINT); time.sleep(30)")
        admitted = []
        with self.assertRaises(KeyboardInterrupt):
            verify.execute_unittest(verify.unittest_command(self.args), self.project, 5,
                                     process_admission=admitted.append)
        with self.assertRaises(ChildProcessError):
            os.waitpid(admitted[0], os.WNOHANG)
        with self.assertRaises(ProcessLookupError):
            os.killpg(admitted[0], 0)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_admitted_child_group_remains_observable_after_executor_sigkill(self):
        self.write_test("Path('.moru/effect').write_text('running'); time.sleep(30)")
        script = (
            "import sys\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from agent_verification_hook import execute_unittest, unittest_command\n"
            "project = Path(sys.argv[2])\n"
            "args = SimpleNamespace(project=project, test_directory='tests', "
            "test_pattern='test_case.py', verify_timeout=60)\n"
            "execute_unittest(unittest_command(args), project, 60, process_admission="
            "lambda pid: (project / '.moru/group').write_text(str(pid)))\n")
        root = subprocess.Popen([sys.executable, "-B", "-c", script, str(ROOT / "scripts"),
                                 str(self.project)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        group = None
        try:
            deadline = time.monotonic() + 5
            while not (self.project / ".moru" / "effect").exists() and time.monotonic() < deadline:
                self.assertIsNone(root.poll(), "executor exited before starting project tests")
                time.sleep(0.01)
            self.assertTrue((self.project / ".moru" / "effect").exists())
            group = int((self.project / ".moru" / "group").read_text())
            root.kill()
            self.assertEqual(-signal.SIGKILL, root.wait(timeout=5))
            os.killpg(group, 0)
        finally:
            if root.poll() is None:
                root.kill()
                root.wait()
            path = self.project / ".moru" / "group"
            group = group or (int(path.read_text()) if path.exists() else None)
            if group is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)

    def test_guarded_non_posix_execution_is_refused_before_spawning(self):
        command = verify.unittest_command(self.args)
        with patch.object(verify.os, "name", "nt"), patch.object(verify.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "requires POSIX"):
                verify.execute_unittest(command, self.project, 5, process_admission=lambda pid: None)
            popen.assert_not_called()

    def test_ledger_ownership_rejection_prevents_execution(self):
        with patch.object(verify, "record_hook_gate", side_effect=PermissionError("not owner")):
            with patch.object(verify, "execute_unittest") as execute:
                self.assertEqual(1, self.run_hook())
                execute.assert_not_called()

    def test_generated_launcher_dispatches_verify(self):
        from support.stable_launcher import ensure_stable_launcher, stable_launcher_path
        with patch("support.stable_launcher.Path.home", return_value=self.project):
            ensure_stable_launcher(ROOT, dry_run=False)
            launcher = stable_launcher_path()
        result = subprocess.run([str(launcher), "verify", "--help"],
                                env={**os.environ, "MORU_HOME": str(ROOT)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--test-pattern", result.stdout)

    def test_cli_dispatch_reaches_runner(self):
        spec = importlib.util.spec_from_file_location("verify_cli", ROOT / "scripts/agent-hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        args = hook.build_parser().parse_args(["verify", "--project", str(self.project),
                                              "--test-pattern", "test_case.py"])
        with patch.object(verify, "verification_hook", return_value=0) as runner:
            with patch.object(hook, "checkpoint_after_hook", side_effect=lambda args, code, *a: code):
                self.assertEqual(0, hook._checkpointed_hook(args))
            runner.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
