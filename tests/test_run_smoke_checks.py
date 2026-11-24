"""Differential subprocess checks for native smoke suite admission and ordering."""
from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from native_launcher_support import NATIVE, PROJECT, install
from native_pretool_support import environment
from support.native_source_inputs import source_inputs


GATE_FIXTURE = Path("native/checkout-identity/smoke-gate-records.json")


class NativeSmokeSuiteTests(unittest.TestCase):
    def test_stable_smoke_alias_dispatch_and_fallback(self) -> None:
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            home = base / "home"
            home.mkdir()
            install(home, PROJECT)
            entry = home / ".moru/bin/moru-hook"
            bindir = base / "bin"
            bindir.mkdir()
            trace = base / "calls"
            native_trace = base / "native-calls"
            native = entry.with_name("moru-hook-native")
            binary = native.with_name("smoke-native-fixture")
            native.rename(binary)
            native.write_text(
                "#!/bin/sh\n"
                'case "${2-}" in\n'
                f"    smoke-checks|--smoke-hook-suite) printf '%s\\n' native >> {shlex.quote(str(native_trace))} ;;\n"
                "esac\n"
                f'exec {shlex.quote(str(binary))} "$@"\n',
                encoding="utf-8",
            )
            native.chmod(0o755)
            python = bindir / "python3"
            python.write_text(
                f"#!{sys.executable}\n"
                "import os, sys\nfrom pathlib import Path\n"
                "name = Path(sys.argv[1]).name\n"
                "if name in ('moru-hook', 'agent-hook.py', 'workflow.py'):\n"
                f"    with Path({str(trace)!r}).open('a') as file: file.write(name + '\\n')\n"
                "if name == 'agent-hook.py' and os.environ.get('SMOKE_TEST_START_125'): sys.exit(125)\n"
                "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            env = environment(base, PROJECT)
            env.update(TMPDIR=str(base), PATH=f"{bindir}:{env['PATH']}")
            python_steps = ["agent-hook.py"] * 4 + ["workflow.py"]
            for overrides, code, steps in (
                ({}, 0, python_steps),
                ({"MORU_LAUNCHER_BACKEND": "python"}, 0, ["moru-hook"]),
                ({"PYTHONPATH": str(base / "absent")}, 0, ["moru-hook"]),
                ({"SMOKE_TEST_START_125": "1"}, 1, ["agent-hook.py"]),
            ):
                with self.subTest(overrides=overrides):
                    done = subprocess.run([str(entry), "smoke-checks"], env={**env, **overrides},
                                          cwd=base, stdin=subprocess.DEVNULL, capture_output=True, timeout=35)
                    self.assertEqual(done.returncode, code, (done.stdout, done.stderr))
                    self.assertEqual(trace.read_text().splitlines(), steps)
                    trace.unlink()
                    expected_native = [] if overrides.get("MORU_LAUNCHER_BACKEND") == "python" else ["native"]
                    seen_native = native_trace.read_text().splitlines() if native_trace.exists() else []
                    self.assertEqual(seen_native, expected_native)
                    native_trace.unlink(missing_ok=True)
                    self.assertEqual(done.stdout.count(b"Starting E2E Hook Smoke Checks"), 1)
                    if code == 0:
                        self.assertIn(b"All E2E smoke checks passed", done.stdout)
                    self.assertEqual(list(base.glob("tmp*")), [])
            for args, code, stdout, stderr in (
                (["--help"], 0, b"usage: moru-hook smoke-checks\n", b""),
                (["--unknown"], 2, b"", b"usage: moru-hook smoke-checks\n"),
            ):
                for backend in ("auto", "python"):
                    done = subprocess.run([str(entry), "smoke-checks", *args],
                                          env={**env, "MORU_LAUNCHER_BACKEND": backend},
                                          cwd=base, capture_output=True, timeout=10)
                    self.assertEqual((done.returncode, done.stdout, done.stderr), (code, stdout, stderr))

    def test_cli_owns_and_cleans_git_fixture(self) -> None:
        if not NATIVE.is_file() or sys.platform == "win32":
            self.skipTest("native Unix test artifact unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            for name in ("home", "scratch"):
                (base / name).mkdir()
            install(base / "home", PROJECT)
            entry = base / "home/.moru/bin/moru-hook"
            shim = base / "python-shim"
            shim.write_text(
                f"#!{sys.executable}\n"
                "import json, os, subprocess, sys\nfrom pathlib import Path\n"
                "stage = sys.argv[2]\n"
                "if stage == 'start':\n"
                "    project = Path(sys.argv[sys.argv.index('--project') + 1])\n"
                "    assert project.parent == Path(os.environ['TMPDIR'])\n"
                "    assert project.stat().st_mode & 0o777 == 0o700\n"
                "    assert subprocess.check_output(['git', '-C', str(project), 'show', 'HEAD:README.md']) == b'Dummy project'\n"
                "    assert json.loads((project / '.vibeguard.json').read_text())\n"
                "    if os.environ.get('SMOKE_TEST_START_125'): sys.exit(125)\n"
                "    state = project / '.moru/runs/run'\n"
                "    state.mkdir(parents=True)\n    (state / 'preflight.json').touch()\n"
                "if stage == 'gate': sys.exit(0 if os.environ.get('SMOKE_TEST_WEAK_ACCEPTED') else 3)\n"
                "if stage == 'gate-batch':\n"
                "    for record in json.loads(Path(sys.argv[-1]).read_text()): print(record['gate'])\n"
                "if stage == 'query': print('TRIAGE')\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)
            scratch = base / "scratch"
            env = {**environment(base, PROJECT), "TMPDIR": str(scratch)}
            script = PROJECT / "scripts/run_smoke_checks.py"
            args = [str(entry.with_name("moru-hook-native")), str(entry), "--smoke-hook-suite", str(shim)]
            cli = (
                "import runpy,sys,tempfile; suite=runpy.run_path(sys.argv[1]); "
                "sys.executable=sys.argv[2]; tempfile.TemporaryDirectory=lambda: sys.exit(87); "
                "sys.exit(suite['main']())"
            )
            broken_config = base / "broken.gitconfig"
            broken_config.write_text("[", encoding="utf-8")
            for expected, output, absent, overrides in (
                (0, b"All E2E smoke checks passed", None, {}),
                (1, b"Gate should have failed", b"--- Test 3", {"SMOKE_TEST_WEAK_ACCEPTED": "1"}),
                (1, b"git init exited", b"--- Test 1", {"GIT_CONFIG_GLOBAL": str(broken_config)}),
                (1, b"Start hook failed", b"--- Test 2", {"SMOKE_TEST_START_125": "1"}),
                (125, b"", None, {"GIT_DIR": str(PROJECT / ".git")}),
            ):
                with self.subTest(status=expected, overrides=overrides):
                    command = args if expected == 125 else [sys.executable, "-c", cli, str(script), str(shim)]
                    done = subprocess.run(command, stdin=subprocess.DEVNULL, env={**env, **overrides},
                                          capture_output=True, timeout=15)
                    self.assertEqual(done.returncode, expected, (done.stdout, done.stderr))
                    self.assertEqual(list(scratch.glob("tmp*")), [])
                    self.assertIn(output, done.stdout)
                    if absent:
                        self.assertNotIn(absent, done.stdout)
                    if expected == 125:
                        self.assertEqual((done.stdout, done.stderr), (b"", b""))
                    else:
                        self.assertEqual(done.stdout.count(b"Starting E2E Hook Smoke Checks"), 1)

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
            data = (PROJECT / GATE_FIXTURE).read_bytes()
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
                    actual = subprocess.run(native_args, stdin=subprocess.DEVNULL, env=task_env,
                                            capture_output=True, timeout=10)
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (expected.returncode, expected.stdout, expected.stderr))
                    self.assertEqual(trace.read_text().splitlines(), steps)
                    if scenario == "success":
                        self.assertEqual((project / ".moru/smoke-gates.json").read_bytes(), data)
                    trace.unlink()
                    shutil.rmtree(project / ".moru")

            denied = subprocess.run([*native_args[:-1], str(PROJECT)], stdin=subprocess.DEVNULL,
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual((denied.returncode, denied.stdout, denied.stderr), (125, b"", b""))
            self.assertFalse(trace.exists())

    def test_gate_fixture_is_receipted_and_source_drift_declines(self) -> None:
        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        self.assertIn(PROJECT / GATE_FIXTURE, source_inputs(PROJECT))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            home = base / "home"
            home.mkdir()
            install(home, PROJECT)
            entry = home / ".moru/bin/moru-hook"
            root = base / "source"
            root.mkdir()
            (root / "scripts").symlink_to(PROJECT / "scripts", target_is_directory=True)
            for filename in ("AGENTS.md", "index.md", ".vibeguard.json"):
                shutil.copyfile(PROJECT / filename, root / filename)
            fixture = root / GATE_FIXTURE
            fixture.parent.mkdir(parents=True)
            content = (PROJECT / GATE_FIXTURE).read_bytes()
            (home / ".moru/moru-root").write_text(str(root), encoding="utf-8")
            env = {**environment(base, root), "TMPDIR": str(base)}
            shim = base / "start-failure"
            shim.write_text("#!/bin/sh\nexit 37\n", encoding="utf-8")
            shim.chmod(0o755)
            args = [str(entry.with_name("moru-hook-native")), str(entry), "--smoke-hook-suite", str(shim)]
            for data, status in ((content, 1), (content.replace(b"quick", b"other", 1), 125)):
                fixture.write_bytes(data)
                done = subprocess.run(args, stdin=subprocess.DEVNULL, env=env, cwd=base,
                                      capture_output=True, timeout=25)
                self.assertEqual(done.returncode, status, (done.stdout, done.stderr))
                if status == 125:
                    self.assertEqual((done.stdout, done.stderr), (b"", b""))
                else:
                    self.assertIn(b"Start hook failed", done.stdout)
                self.assertEqual(list(base.glob("tmp*")), [])
