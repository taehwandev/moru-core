"""Differential subprocess checks for native smoke suite admission and ordering."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

from native_launcher_support import NATIVE, PROJECT, install
from native_pretool_support import environment


class NativeSmokeSuiteTests(unittest.TestCase):
    def test_scratch_suite_matches_python_and_stops_after_negative_gate_failure(self) -> None:
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            project = base / "scratch space"
            project.mkdir()
            (project / ".git").mkdir()
            (project / "README.md").write_text("Dummy project", encoding="utf-8")
            (project / ".vibeguard.json").write_text("{}", encoding="utf-8")
            home = base / "home"
            home.mkdir()
            install(home, PROJECT)
            entry = home / ".moru/bin/moru-hook"
            native = entry.with_name("moru-hook-native")
            shim = base / "python-shim"
            trace = base / "calls"
            shim.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\nfrom pathlib import Path\n"
                "stage = sys.argv[2]\n"
                f"with Path({str(trace)!r}).open('a') as file: file.write(stage + '\\n')\n"
                "if stage == 'start':\n"
                "    state = Path(sys.argv[sys.argv.index('--project') + 1]) / '.moru/runs/run'\n"
                "    state.mkdir(parents=True)\n    (state / 'preflight.json').touch()\n"
                "if stage == 'gate': sys.exit(0 if os.environ.get('SMOKE_TEST_WEAK_ACCEPTED') else 3)\n"
                "if stage == 'gate-batch' and not os.environ.get('SMOKE_TEST_MISSING_GATES'):\n"
                "    for record in json.loads(Path(sys.argv[-1]).read_text()): print(record['gate'])\n"
                "if stage == 'query': print('TRIAGE')\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)
            env = {**environment(base, PROJECT), "TMPDIR": str(base)}
            script = PROJECT / "scripts/run_smoke_checks.py"
            data = json.dumps(runpy.run_path(str(script))["_gate_records"]()).encode("utf-8")
            oracle = (
                "import runpy,sys; suite=runpy.run_path(sys.argv[1]); "
                "sys.executable=sys.argv[2]; project=sys.argv[3]\n"
                "try:\n"
                " for name in ('test_start_hook','test_gate_validation_failures',"
                "'test_gate_validation_success','test_finish_hook'): suite[name](project)\n"
                " suite['test_workflow_query']()\n"
                "except AssertionError as error:\n"
                " print(f'\\n❌ Smoke check failed: {error}'); sys.exit(1)"
            )
            native_args = [str(native), str(entry), "--smoke-hook-suite", str(shim), str(project)]
            for scenario, expected_steps in (
                ("success", ["start", "gate", "gate-batch", "finish", "query"]),
                ("weak", ["start", "gate"]),
                ("missing", ["start", "gate", "gate-batch"]),
            ):
                with self.subTest(scenario=scenario):
                    task_env = {**env, "SMOKE_TEST_WEAK_ACCEPTED": "1" if scenario == "weak" else "",
                                "SMOKE_TEST_MISSING_GATES": "1" if scenario == "missing" else ""}
                    expected = subprocess.run([sys.executable, "-c", oracle, str(script), str(shim), str(project)],
                                              env=task_env, capture_output=True, timeout=10)
                    steps = trace.read_text().splitlines()
                    self.assertEqual(steps, expected_steps)
                    trace.unlink()
                    shutil.rmtree(project / ".moru")
                    actual = subprocess.run(native_args, input=data, env=task_env, capture_output=True, timeout=10)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (expected.returncode, expected.stdout, expected.stderr))
                    self.assertEqual(trace.read_text().splitlines(), steps)
                    if scenario == "success":
                        self.assertEqual((project / ".moru/smoke-gates.json").read_bytes(), data)
                    trace.unlink()
                    shutil.rmtree(project / ".moru")

            denied = subprocess.run([*native_args[:-1], str(PROJECT)], input=data,
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual((denied.returncode, denied.stdout, denied.stderr), (125, b"", b""))
            self.assertFalse(trace.exists())
