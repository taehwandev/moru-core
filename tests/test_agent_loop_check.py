"""Real bounded unittest processes for frozen loop goal and regression checks."""

import contextlib
import io
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _moru_test_support import TemplateRepository
from agent_loop_check import LoopCheck
from agent_loop_inputs import LoopInputs


def _build_fixture(project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".moru/\n__pycache__/\n")
    (project / "candidate.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)


_FIXTURE = TemplateRepository(_build_fixture)


def tearDownModule():
    _FIXTURE.cleanup()


class LoopCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        _FIXTURE.copy_to(self.project)
        (self.project / "tests").mkdir()
        (self.project / ".moru").mkdir()
        self.artifacts = self.project / ".moru" / "checks"
        self.config = {"directory": "tests", "regression_pattern": "test_regression.py",
                       "goal_pattern": "test_goal.py", "metric": None}
        self.write_test("test_regression.py")
        self.write_test("test_goal.py")

    def write_test(self, name, body="self.assertTrue(True)"):
        (self.project / "tests" / name).write_text(
            "import json, os, time, unittest\nfrom pathlib import Path\n"
            "class Case(unittest.TestCase):\n    def test_case(self):\n"
            + "\n".join("        " + line for line in body.splitlines()) + "\n")

    def run_check(self, timeout=5, verifiers=None, process_admission=None):
        inputs = LoopInputs(self.project, ["candidate.py"], verifiers or
                            ["tests/test_goal.py", "tests/test_regression.py"])
        with contextlib.redirect_stdout(io.StringIO()):
            return LoopCheck(self.project, self.config, self.artifacts,
                             process_admission=process_admission).run(inputs, timeout)

    def test_real_success_has_exact_fields_and_stable_inputs(self):
        result = self.run_check()
        self.assertEqual({"before", "after", "regression", "goal", "value", "stable"}, set(result))
        self.assertEqual({"exit": 0, "tests": 1, "passed": True}, result["goal"])
        self.assertEqual(result["goal"], result["regression"])
        self.assertTrue(result["stable"])
        self.assertEqual(result["before"], result["after"])
        self.assertIsNone(result["value"])

    def test_validate_rejects_missing_or_nonfrozen_files_before_enrollment(self):
        inputs = LoopInputs(self.project, ["candidate.py"],
                            ["tests/test_goal.py", "tests/test_regression.py"])
        checker = LoopCheck(self.project, self.config, self.artifacts)
        checker.validate(inputs)
        checker.config["goal_pattern"] = "missing_*.py"
        with self.assertRaisesRegex(ValueError, "require frozen Python test files"):
            checker.validate(inputs)
        checker.config["goal_pattern"] = "test_*.py"
        self.write_test("test_shadow.py")
        with self.assertRaisesRegex(ValueError, "not a frozen verifier"):
            checker.validate(inputs)

    def test_admission_callback_precedes_each_real_check(self):
        effect = self.project / ".moru" / "effect"
        self.write_test("test_goal.py", "Path('.moru/effect').write_text('ran')")
        admitted = []

        def admit(pid):
            self.assertFalse(effect.exists())
            admitted.append(pid)

        result = self.run_check(process_admission=admit)
        self.assertTrue(result["goal"]["passed"])
        self.assertEqual(2, len(set(admitted)))
        self.assertTrue(effect.exists())

    def test_real_regression_and_goal_failures_are_distinct(self):
        for failed in ("regression", "goal"):
            with self.subTest(failed=failed):
                self.write_test("test_regression.py", "self.assertTrue(True)")
                self.write_test("test_goal.py", "self.assertTrue(True)")
                self.write_test(f"test_{failed}.py", "self.fail('expected')")
                result = self.run_check()
                self.assertEqual({"exit": 1, "tests": 1, "passed": False}, result[failed])
                self.assertTrue(result["goal" if failed == "regression" else "regression"]["passed"])

    def test_regression_runs_first_and_equal_selections_execute_once(self):
        self.write_test("test_regression.py", "Path('.moru/first').write_text('regression')")
        self.write_test("test_goal.py", "self.assertEqual('regression', Path('.moru/first').read_text())")
        self.assertTrue(self.run_check()["goal"]["passed"])
        self.config["goal_pattern"] = "test_regression.py"
        self.write_test("test_regression.py", "path = Path('.moru/count')\n"
                        "path.write_text(str(int(path.read_text()) + 1) if path.exists() else '1')")
        result = self.run_check()
        self.assertEqual("1", (self.project / ".moru" / "count").read_text())
        self.assertEqual(result["goal"], result["regression"])

    def test_missing_selection_and_zero_test_module_never_pass(self):
        self.config["goal_pattern"] = "missing_*.py"
        self.assertEqual({"exit": 0, "tests": 0, "passed": False}, self.run_check()["goal"])
        self.config["goal_pattern"] = "test_goal.py"
        (self.project / "tests" / "test_goal.py").write_text("# no tests\n")
        self.assertFalse(self.run_check()["goal"]["passed"])

    def test_only_skips_or_expected_failures_do_not_prove_goal(self):
        for decorator in ("unittest.skip('unavailable')", "unittest.expectedFailure"):
            with self.subTest(decorator=decorator):
                (self.project / "tests" / "test_goal.py").write_text(
                    "import unittest\nclass Case(unittest.TestCase):\n"
                    f"    @{decorator}\n    def test_goal(self):\n"
                    "        self.fail('goal not reached')\n")
                result = self.run_check()
                self.assertEqual({"exit": 0, "tests": 1, "passed": False}, result["goal"])
                self.assertTrue(result["regression"]["passed"])

    def test_a_real_pass_with_optional_skips_remains_valid(self):
        self.write_test("test_goal.py", "for item in range(3):\n"
                        "    with self.subTest(item=item):\n"
                        "        self.skipTest('optional subtest')\n"
                        "self.assertTrue(True)")
        with (self.project / "tests" / "test_goal.py").open("a") as output:
            output.write("    @unittest.skip('optional')\n    def test_optional(self):\n        pass\n")
        self.assertEqual({"exit": 0, "tests": 2, "passed": True}, self.run_check()["goal"])

    def test_current_measurement_is_observed_even_when_goal_fails(self):
        self.config["metric"] = {}
        self.write_test("test_goal.py", "Path(os.environ['MORU_LOOP_MEASUREMENT_PATH']).write_text"
                        "(json.dumps({'value': 2.5}))\nself.fail('target not reached')")
        result = self.run_check()
        self.assertEqual(2.5, result["value"])
        self.assertFalse(result["goal"]["passed"])
        self.assertTrue(result["stable"])

    def test_old_measurement_and_regression_output_cannot_satisfy_goal(self):
        self.config["metric"] = {}
        self.write_test("test_goal.py", "marker = Path('.moru/wrote')\n"
                        "if not marker.exists():\n"
                        "    Path(os.environ['MORU_LOOP_MEASUREMENT_PATH']).write_text('{\"value\": 3}')\n"
                        "    marker.write_text('once')")
        self.assertEqual(3, self.run_check()["value"])
        with self.assertRaisesRegex(ValueError, "current loop measurement"):
            self.run_check()
        self.write_test("test_regression.py", "Path(os.environ['MORU_LOOP_MEASUREMENT_PATH'])"
                        ".write_text('{\"value\": 4}')")
        with self.assertRaisesRegex(ValueError, "current loop measurement"):
            self.run_check()
        self.assertEqual(3, len(list(self.artifacts.iterdir())))

    def test_invalid_measurements_fail_closed(self):
        self.config["metric"] = {}
        values = ['{', '{"value":true}', '{"value":NaN}', '{"value":Infinity}',
                  '{"value":"1"}', '{"value":null}', '[1]', '{"other":1}',
                  '{"value":1,"extra":2}', '{"value":1,"value":2}', ' ' * 4097]
        for raw in values:
            with self.subTest(raw=raw[:40]):
                self.write_test("test_goal.py", "Path(os.environ['MORU_LOOP_MEASUREMENT_PATH'])"
                                f".write_text({raw!r})")
                with self.assertRaisesRegex(ValueError, "current loop measurement"):
                    self.run_check()

    def test_measurement_symlink_directory_and_fifo_are_refused_without_blocking(self):
        self.config["metric"] = {}
        for creation in ("path.symlink_to(Path('candidate.py').resolve())", "path.mkdir()",
                         "os.mkfifo(path)"):
            with self.subTest(creation=creation):
                self.write_test("test_goal.py", "path = Path(os.environ['MORU_LOOP_MEASUREMENT_PATH'])\n"
                                + creation)
                started = time.monotonic()
                with self.assertRaisesRegex(ValueError, "current loop measurement"):
                    self.run_check()
                self.assertLess(time.monotonic() - started, 2)

    def test_artifacts_directory_escape_or_symlink_never_receives_writes(self):
        self.config["metric"] = {}
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name)
        (self.project / ".moru" / "linked").symlink_to(target, target_is_directory=True)
        for artifact in (target / "checks", self.project / ".moru" / "linked" / "checks",
                         self.project / ".moru" / ".." / "escaped"):
            with self.subTest(artifact=artifact):
                self.artifacts = artifact
                with self.assertRaisesRegex(ValueError, "artifact directory"):
                    self.run_check()
                self.assertEqual([], list(target.iterdir()))

    def test_replaced_measurement_parent_cannot_redirect_our_read_or_unlink(self):
        self.config["metric"] = {}
        target = self.project / ".moru" / "target"
        target.mkdir()
        (target / "measurement.json").write_text('{"value": 99}')
        self.write_test("test_regression.py", "path = Path(os.environ['MORU_LOOP_MEASUREMENT_PATH'])\n"
                        "path.parent.rename(path.parent.with_name(path.parent.name + '-moved'))\n"
                        "path.parent.symlink_to(Path('.moru/target').resolve(), target_is_directory=True)")
        with self.assertRaisesRegex(ValueError, "current loop measurement"):
            self.run_check()
        self.assertEqual('{"value": 99}', (target / "measurement.json").read_text())

    def test_shared_timeout_does_not_restart_for_goal(self):
        self.write_test("test_regression.py", "time.sleep(0.35)")
        self.write_test("test_goal.py", "time.sleep(1)")
        started = time.monotonic()
        result = self.run_check(timeout=0.7)
        self.assertTrue(result["regression"]["passed"])
        self.assertEqual(124, result["goal"]["exit"])
        self.assertFalse(result["goal"]["passed"])
        self.assertLess(time.monotonic() - started, 1.3)

    def test_timeout_before_goal_does_not_execute_it(self):
        self.write_test("test_regression.py", "time.sleep(1)")
        self.write_test("test_goal.py", "Path('.moru/should-not-run').write_text('bad')")
        result = self.run_check(timeout=0.1)
        self.assertEqual(124, result["regression"]["exit"])
        self.assertEqual(124, result["goal"]["exit"])
        self.assertFalse((self.project / ".moru" / "should-not-run").exists())

    def test_passing_tests_that_mutate_inputs_are_unstable(self):
        for path in ("candidate.py", "outside.txt", "tests/test_regression.py"):
            with self.subTest(path=path):
                self.write_test("test_regression.py")
                self.write_test("test_goal.py", f"Path({path!r}).write_text('changed')")
                result = self.run_check()
                self.assertTrue(result["goal"]["passed"])
                self.assertFalse(result["stable"])

    def test_nonfrozen_test_in_either_selection_prevents_any_execution(self):
        self.write_test("test_regression.py", "Path('.moru/ran').write_text('bad')")
        for pattern in ("goal_pattern", "regression_pattern"):
            with self.subTest(pattern=pattern):
                self.config[pattern] = "test_*.py"
                self.write_test("test_shadow.py")
                with self.assertRaisesRegex(ValueError, "not a frozen verifier"):
                    self.run_check()
                self.assertFalse((self.project / ".moru" / "ran").exists())
                self.config[pattern] = f"test_{pattern.removesuffix('_pattern')}.py"

    def test_new_test_added_by_regression_is_refused_before_goal(self):
        self.config["goal_pattern"] = "test_goal*.py"
        self.write_test("test_regression.py", "Path('tests/test_goal_shadow.py').write_text('')")
        self.write_test("test_goal.py", "Path('.moru/ran').write_text('bad')")
        with self.assertRaisesRegex(ValueError, "not a frozen verifier"):
            self.run_check()
        self.assertFalse((self.project / ".moru" / "ran").exists())

    def test_symlink_package_cannot_hide_nonfrozen_tests(self):
        hidden = self.project / "hidden"
        hidden.mkdir()
        (hidden / "__init__.py").write_text("")
        (hidden / "test_goal.py").write_text("raise AssertionError('must not import')\n")
        (self.project / "tests" / "linked").symlink_to(hidden, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink directory"):
            self.run_check()

    def test_regression_replacing_test_directory_cannot_redirect_goal(self):
        hidden = self.project / ".moru" / "hidden"
        hidden.mkdir()
        (hidden / "test_goal.py").write_text("raise AssertionError('must not import')\n")
        self.write_test("test_regression.py", "Path('tests').rename('original-tests')\n"
                        "Path('tests').symlink_to(Path('.moru/hidden').resolve(), target_is_directory=True)")
        with self.assertRaisesRegex(ValueError, "symlink directory"):
            self.run_check()

    def test_empty_selection_does_not_import_package_load_tests(self):
        package = self.project / "tests" / "package"
        package.mkdir()
        (package / "__init__.py").write_text("raise AssertionError('must not import')\n")
        self.config["regression_pattern"] = "missing_*.py"
        self.config["goal_pattern"] = "missing_*.py"
        result = self.run_check()
        self.assertEqual({"exit": 0, "tests": 0, "passed": False}, result["goal"])

    def test_interruption_propagates_without_claiming_result(self):
        with patch("agent_loop_check.execute_unittest", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_check()


if __name__ == "__main__":
    unittest.main()
