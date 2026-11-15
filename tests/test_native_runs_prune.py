"""Actual generated retention reports: original bytes, no Python, no deletion."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from native_pretool_support import environment, prepare, result

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "88901b63f0ceecc36fa15d2f48024a98b6e4780f"


class NativeRunsPruneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="native-runs-prune-")
        cls.addClassCleanup(temporary.cleanup)
        cls.base = Path(temporary.name).resolve()
        cls.entry, cls.launch_project = prepare(cls.base)
        python_path = cls.base / "python-path"
        python_path.mkdir()
        (python_path / "python3").symlink_to(sys.executable)
        empty = cls.base / "empty-path"
        empty.mkdir()
        cls.env = {**environment(cls.base), "PATH": str(python_path)}
        cls.no_python = {**cls.env, "PATH": str(empty)}
        cls.oracle = cls.base / "runs-prune.py"
        original = subprocess.run(
            ["git", "show", BASELINE + ":scripts/runs-prune.py"],
            cwd=ROOT, capture_output=True, check=True, timeout=8,
        ).stdout
        cls.oracle.write_bytes(original)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.base, prefix="project 한글 ")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.runs = self.project / ".moru/runs"

    def run_cli(self, *args, original=False, env=None, data=b""):
        env = {**(env or self.env)}
        if original:
            env.update(PYTHONPATH=str(ROOT / "scripts"), MORU_LAUNCHER_BACKEND="python")
            command = [sys.executable, "-B", str(self.oracle), *args]
        else:
            command = [str(self.entry), "runs-prune", *args]
        return subprocess.run(command, input=data, capture_output=True,
                              env=env, cwd=self.project, timeout=10)

    def same(self, *args, native=True):
        expected = self.run_cli(*args, original=True)
        actual = self.run_cli(*args, env=self.no_python if native else self.env)
        self.assertEqual(result(expected), result(actual))
        self.assertEqual(0, actual.returncode)
        return actual

    def make_run(self, number, phase="done", age=100):
        folder = self.runs / f"{number:032x}"
        folder.mkdir(parents=True)
        if phase is not None:
            (folder / "continuation.json").write_text(json.dumps({"phase": phase}))
        (folder / "evidence").write_text("synthetic 한글")
        moment = time.time() - age
        os.utime(folder, (moment, moment))
        return folder

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def registry(self, states):
        (self.project / ".moru/run-registry.json").write_text(json.dumps({
            "schema_version": 1,
            "runs": [{"run_id": f"{number:032x}", "state": state}
                     for number, state in states.items()],
        }))

    def test_default_missing_directory_has_exact_native_report(self):
        self.same()

    def test_empty_directory_has_exact_native_report(self):
        self.runs.mkdir(parents=True)
        self.same("--project", str(self.project))

    def test_finished_selection_bytes_and_unicode_path_match_without_writes(self):
        for number in range(4):
            self.make_run(number, age=200 - number)
        before = self.snapshot()
        actual = self.same("--project", str(self.project), "--keep", "1")
        self.assertIn(b"removable: 3\n", actual.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.project.rglob("*.lock*")))

    def test_more_than_five_unfinished_runs_preserve_order_and_phase_text(self):
        for number, phase in enumerate(("acting", "blocked", None, "paused", "reviewing", "scoped", "waiting")):
            self.make_run(number, phase)
        actual = self.same("--keep=0")
        self.assertIn(b"... and 2 more\n", actual.stdout)
        self.assertIn(b"phase=unreadable\n", actual.stdout)

    def test_human_names_and_files_are_counted_without_removal(self):
        self.make_run(0)
        (self.runs / "notes 한글").mkdir()
        (self.runs / "notes 한글/data").write_text("owned fixture")
        (self.runs / "readme").write_text("also counted")
        before = self.snapshot()
        self.same("--keep", "0")
        self.assertEqual(before, self.snapshot())

    def test_live_and_settled_registry_states_match_original(self):
        for number in range(4):
            self.make_run(number, "acting", age=10000)
        self.registry({0: "running", 1: "completed", 2: "cancelled", 3: "paused"})
        self.same("--keep=0", "--abandoned-after-seconds=1")

    def test_orphan_and_abandoned_windows_use_canonical_policy(self):
        self.make_run(0, "acting", age=10000)
        self.make_run(1, "acting", age=10000)
        self.registry({0: "failed"})
        actual = self.same("--keep=0", "--abandoned-after-seconds=1", "--orphan-after-seconds=1")
        self.assertIn(b"abandoned: 1  orphaned: 1\n", actual.stdout)

    def test_repeated_equal_split_and_negative_options_preserve_argparse_values(self):
        self.make_run(0, "acting", age=10000)
        self.same("--keep=5", "--keep", "-1", "--abandoned-after-seconds", "+0",
                  "--orphan-after-seconds=-1")

    def test_unreadable_registry_declines_without_native_output(self):
        self.make_run(0)
        (self.project / ".moru/run-registry.json").write_text("{")
        self.same("--keep=0", native=False)
        actual = self.run_cli("--keep=0", env=self.no_python)
        self.assertEqual((127, b""), (actual.returncode, actual.stdout))

    def test_relative_paths_and_argparse_unsupported_forms_keep_python_behavior(self):
        self.make_run(0)
        for args in (("--project", "."), ("--kee", "0"), ("--keep", " 1 "), ("--keep", "١")):
            with self.subTest(args=args):
                self.same(*args, native=False)

    def test_help_and_invalid_arguments_preserve_exact_python_diagnostics(self):
        for args in (("--help",), ("--unknown",), ("--keep",), ("--keep", "bad")):
            with self.subTest(args=args):
                self.assertEqual(result(self.run_cli(*args, original=True)), result(self.run_cli(*args)))

    def test_apply_needs_python_even_with_soft_fail_and_never_deletes_natively(self):
        self.make_run(0)
        before = self.snapshot()
        actual = self.run_cli("--keep=0", "--apply",
                              env={**self.no_python, "MORU_HOOK_SOFT_FAIL": "1"})
        self.assertEqual((127, b""), (actual.returncode, actual.stdout))
        self.assertEqual(before, self.snapshot())

    def test_apply_fallback_preserves_whole_argv_stdin_cwd_and_exit(self):
        spy_path = self.project / "spy-path"
        spy_path.mkdir()
        spy = spy_path / "python3"
        spy.write_text(f"#!{sys.executable}\nimport json,os,sys\n"
                       "print(json.dumps({'argv':sys.argv[1:],'stdin':sys.stdin.read(),"
                       "'cwd':os.getcwd(),'marker':os.environ.get('REPORT_MARKER')}))\n"
                       "sys.exit(23)\n")
        spy.chmod(0o700)
        args = ("--project", str(self.project), "--keep=0", "--apply")
        actual = self.run_cli(*args, env={**self.env, "PATH": str(spy_path), "REPORT_MARKER": "kept"},
                              data=b"untouched stdin\n")
        self.assertEqual((23, b""), (actual.returncode, actual.stderr))
        self.assertEqual({"argv": [str(self.entry), "runs-prune", *args],
                          "stdin": "untouched stdin\n", "cwd": str(self.project), "marker": "kept"},
                         json.loads(actual.stdout))


class RetentionPolicyMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "retention_contract", ROOT / "native/checkout-identity/pretool_contract.py")
        cls.contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.contract)

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="retention-policy-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in ("agent_run_evidence.py", "agent_run_states.py", "support/global_state.py"):
            target = root / "scripts" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / "scripts" / name).read_bytes())
        return root

    def emit(self, root):
        output = root / "metadata.json"
        self.contract.emit_retention_policy(root, output)
        return json.loads(output.read_text())

    def test_metadata_matches_canonical_source_data(self):
        import agent_run_evidence as evidence
        from agent_run_states import RUN_STATES
        from support.global_state import STATE_DIR_NAME
        policy = self.emit(self.fixture())
        self.assertEqual({"schema_version": 1, "state_dir": STATE_DIR_NAME, "runs_dir": "runs",
                          "run_id_length": evidence.RUN_ID_LENGTH,
                          "registry_schema_version": evidence.REGISTRY_SCHEMA_VERSION,
                          "keep": evidence.DEFAULT_KEEP,
                          "abandoned_after_seconds": evidence.DEFAULT_ABANDONED_AFTER_SECONDS,
                          "orphan_after_seconds": evidence.DEFAULT_ORPHAN_AFTER_SECONDS,
                          "holding_states": sorted(evidence.CLAIM_HOLDING_STATES),
                          "settled_states": sorted(evidence.SETTLED_STATES),
                          "finished_phases": sorted(evidence.FINISHED_PHASES),
                          "run_states": sorted(RUN_STATES)}, policy)

    def test_policy_code_is_never_executed(self):
        root = self.fixture()
        marker = root / "executed"
        for path in root.glob("scripts/**/*.py"):
            path.write_text(path.read_text() + '\nraise RuntimeError("never execute policy")\n'
                            + f'open({str(marker)!r}, "w").write("bad")\n')
        self.assertEqual(10, self.emit(root)["keep"])
        self.assertFalse(marker.exists())

    def test_changed_path_data_is_derived_and_unknown_path_shape_declines(self):
        root = self.fixture()
        source = root / "scripts/agent_run_evidence.py"
        source.write_text(source.read_text().replace(' / "runs"', ' / "evidence"'))
        self.assertEqual("evidence", self.emit(root)["runs_dir"])
        source.write_text(source.read_text().replace(' / "evidence"', '.resolve() / "evidence"'))
        self.assertIsNone(self.emit(root)["runs_dir"])
        source = root / "scripts/support/global_state.py"
        source.write_text(source.read_text().replace("return project / STATE_DIR_NAME",
                                                    "return project.resolve() / STATE_DIR_NAME"))
        self.assertIsNone(self.emit(root)["state_dir"])

    def test_unknown_calls_and_shadowed_frozenset_are_unsupported_data(self):
        root = self.fixture()
        source = root / "scripts/agent_run_evidence.py"
        source.write_text(source.read_text().replace("DEFAULT_KEEP = 10", "DEFAULT_KEEP = side_effect()"))
        policy = self.emit(root)
        self.assertIsNone(policy["keep"])
        self.assertEqual(32, policy["run_id_length"])
        source = root / "scripts/agent_run_states.py"
        source.write_text(source.read_text() + '\ndef frozenset(value): raise RuntimeError("shadow")\n')
        self.assertIsNone(self.emit(root)["run_states"])

    def test_signed_integer_dependencies_are_data(self):
        root = self.fixture()
        source = root / "scripts/agent_run_evidence.py"
        source.write_text(source.read_text().replace("DEFAULT_KEEP = 10",
                                                    "BASE_KEEP = +3\nDEFAULT_KEEP = -(BASE_KEEP - 1)"))
        self.assertEqual(-2, self.emit(root)["keep"])

    def test_rebound_policy_constants_are_unsupported_instead_of_stale(self):
        root = self.fixture()
        source = root / "scripts/agent_run_evidence.py"
        original = source.read_text()
        for mutation in ("DEFAULT_KEEP += 1", "if True:\n    DEFAULT_KEEP = 7",
                         "DEFAULT_KEEP: int = 7", "def DEFAULT_KEEP(): return 7"):
            with self.subTest(mutation=mutation):
                source.write_text(original + "\n" + mutation + "\n")
                self.assertIsNone(self.emit(root)["keep"])

    def test_loaded_set_mutations_cannot_leave_stale_policy_metadata(self):
        root = self.fixture()
        source = root / "scripts/agent_run_evidence.py"
        original = source.read_text()
        for mutation in ("FINISHED_PHASES.add('archived')",
                         "ignored = FINISHED_PHASES.add('archived')",
                         "alias = FINISHED_PHASES\nalias.add('archived')",
                         "if True:\n    FINISHED_PHASES.add('archived')",
                         "mutate(FINISHED_PHASES)"):
            with self.subTest(mutation=mutation):
                source.write_text(original + "\n" + mutation + "\n")
                self.assertIsNone(self.emit(root)["finished_phases"])

    def test_missing_source_is_unsupported_without_build_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.emit(Path(directory))
        self.assertEqual(1, policy.pop("schema_version"))
        self.assertTrue(all(value is None for value in policy.values()))


if __name__ == "__main__":
    unittest.main()
