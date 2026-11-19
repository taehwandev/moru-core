"""Actual-process admission, selection and startup isolation, using temp projects."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_verification_hook as verify
from native_launcher_support import copied_build_root
from support import native_unittest_admission as adapter
from test_agent_verification_hook import _startup_fixture

RUNNER = ROOT / "scripts/agent_unittest_result.py"
NATIVE = ROOT / ".moru/native/bin/moru-native-launcher"


@unittest.skipUnless(os.name == "posix", "requires POSIX admission")
class NativeUnittestAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-unittest-admission-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / "project space 한글"
        (self.project / "tests").mkdir(parents=True)
        (self.project / ".moru").mkdir()
        (self.base / "home").mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("MORU_", "PYTHON", "_PYTHON"))}
        env.update(HOME=str(self.base / "home"), MORU_STATE_HOME=str(self.base / "state"),
                   MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="1",
                   PYTHONDONTWRITEBYTECODE="1")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, env, clear=True).start()
        self.assertEqual(NATIVE, adapter.artifact_plan(ROOT, RUNNER)["source"],
                         "build an exact debug candidate before running this suite")

    def selected(self, script):
        return [sys.executable, "-c", script]

    def execute(self, command, admit=lambda pid: None, extra_env=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return verify.execute_unittest(command, self.project, 5,
                                           extra_env=extra_env, process_admission=admit)

    def assert_native(self, popen):
        argv = popen.call_args.args[0]
        self.assertEqual([str(NATIVE), str(RUNNER), "--unittest-admission"], argv[:3])

    def assert_admitted_identity(self, observed, admitted):
        self.assertEqual(admitted, observed["pid"])
        self.assertEqual(admitted, observed["pgid"])

    def stop(self, process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)

    def test_actual_selection_exec_preserves_admitted_pid_group_cwd_and_environment(self):
        observed = self.project / ".moru/observed.json"
        script = (
            "import json,os,sys; from pathlib import Path; "
            "Path('.moru/observed.json').write_text(json.dumps({"
            "'pid':os.getpid(),'pgid':os.getpgid(0),'cwd':os.getcwd(),"
            "'value':os.environ.get('ADMISSION_FIXTURE'),'latch':'MORU_UNITTEST_ADMISSION' in os.environ})); "
            "Path(sys.argv[1]).write_text(json.dumps({'tests_run':1,'successful':True}))"
        )
        admitted = []

        def admit(pid):
            admitted.append(pid)
            self.assertEqual(pid, os.getpgid(pid))
            self.assertFalse(observed.exists())

        with patch.object(verify.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            self.assertEqual((0, 1, True), self.execute(self.selected(script), admit,
                                                      {"ADMISSION_FIXTURE": "inherited"}))
            self.assert_native(popen)
            self.assertEqual(1, popen.call_count)
        result = json.loads(observed.read_text())
        self.assert_admitted_identity(result, admitted[0])
        self.assertEqual({"pid": admitted[0], "pgid": admitted[0], "cwd": str(self.project),
                          "value": "inherited", "latch": False}, result)

    def test_identity_observer_rejects_spawn_and_wait_negative_control(self):
        script = (
            "import json,os,sys; from pathlib import Path; "
            "Path('.moru/identity.json').write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgid(0)})); "
            "Path(sys.argv[1]).write_text(json.dumps({'tests_run':1,'successful':True}))"
        )
        spawn_and_wait = (
            "import os,subprocess,sys; "
            "assert sys.stdin.buffer.read(1)==b'\\x01'; "
            "os.environ.pop('MORU_UNITTEST_ADMISSION',None); "
            "raise SystemExit(subprocess.run(sys.argv[1:]).returncode)"
        )

        def mutant(command, runner, environment):
            return [sys.executable, "-I", "-S", "-c", spawn_and_wait, *command]

        admitted = []
        with patch.object(adapter, "admission_bootstrap", side_effect=mutant):
            self.assertEqual((0, 1, True), self.execute(self.selected(script), admitted.append))
        observed = json.loads((self.project / ".moru/identity.json").read_text())
        self.assertEqual(admitted[0], observed["pgid"], "mutant shares the group but spawns a new PID")
        with self.assertRaises(AssertionError):
            self.assert_admitted_identity(observed, admitted[0])

    def test_python_rollback_is_selected_before_spawn_from_effective_environment(self):
        script = "import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({'tests_run':1,'successful':True}))"
        with patch.object(adapter, "artifact_plan", side_effect=AssertionError("must not probe")):
            with patch.object(verify.subprocess, "Popen", wraps=subprocess.Popen) as popen:
                self.assertEqual((0, 1, True), self.execute(self.selected(script),
                                                          extra_env={"MORU_LAUNCHER_BACKEND": "python"}))
                self.assertEqual([sys.executable, "-I", "-S", str(RUNNER)], popen.call_args.args[0][:4])

    def test_selection_observer_rejects_forced_compatibility_negative_control(self):
        command = self.selected("import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({'tests_run':1,'successful':True}))")
        with patch.object(adapter, "artifact_plan", return_value=None):
            with patch.object(verify.subprocess, "Popen", wraps=subprocess.Popen) as popen:
                self.assertEqual((0, 1, True), self.execute(command))
                with self.assertRaises(AssertionError):
                    self.assert_native(popen)

    def test_direct_eof_and_wrong_release_byte_never_execute_selected_interpreter(self):
        marker = self.project / ".moru/interpreter-started"
        command = self.selected("from pathlib import Path; Path('.moru/interpreter-started').write_text('bad')")
        for release in (b"", b"\x00", b"\x02"):
            with self.subTest(release=release):
                done = subprocess.run([str(NATIVE), str(RUNNER), "--unittest-admission", *command],
                                      cwd=self.project, input=release, capture_output=True, timeout=5,
                                      env={**os.environ, "MORU_UNITTEST_ADMISSION": "1"})
                self.assertEqual((125, b"", b""), (done.returncode, done.stdout, done.stderr))
                self.assertFalse(marker.exists())

    def test_exec_preserves_inherited_descriptor_and_exit_status(self):
        with tempfile.TemporaryFile() as descriptor:
            script = f"import os; os.write({descriptor.fileno()}, b'kept'); raise SystemExit(7)"
            process = subprocess.Popen(
                [str(NATIVE), str(RUNNER), "--unittest-admission", *self.selected(script)],
                cwd=self.project, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                pass_fds=(descriptor.fileno(),), start_new_session=True,
                env={**os.environ, "MORU_UNITTEST_ADMISSION": "1"})
            self.addCleanup(self.stop, process)
            out, err = process.communicate(b"\x01", timeout=5)
            self.assertEqual((7, b"", b""), (process.returncode, out, err))
            descriptor.seek(0)
            self.assertEqual(b"kept", descriptor.read())

    def test_private_native_exec_failure_never_softens_or_restarts(self):
        with patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            done = subprocess.run(
                [str(NATIVE), str(RUNNER), "--unittest-admission", str(self.base / "missing-interpreter")],
                input=b"\x01", capture_output=True, timeout=5)
            self.assertEqual(127, done.returncode)
            self.assertIn(b"admitted unittest exec failed", done.stderr)
            self.assertEqual(1, popen.call_count)

    def test_unavailable_interpreter_public_result_keeps_python_exit_and_diagnostic(self):
        non_executable = self.base / "not-executable"
        non_executable.write_text("unavailable")
        cases = (str(self.base / "missing-interpreter"), str(non_executable), str(self.base))
        for program in cases:
            with self.subTest(program=program):
                output = []
                for backend in ("python", "auto"):
                    tail = io.StringIO()
                    with contextlib.redirect_stdout(tail):
                        result = verify.execute_unittest([program], self.project, 5,
                            extra_env={"MORU_LAUNCHER_BACKEND": backend}, process_admission=lambda pid: None)
                    self.assertEqual((1, 0, False), result)
                    output.append(tail.getvalue())
                self.assertEqual(output[0], output[1])

    def test_invalid_nul_argument_preserves_pre_spawn_exception_and_never_admits(self):
        for backend in ("python", "auto"):
            admitted = []
            with self.subTest(backend=backend), self.assertRaisesRegex(ValueError, "embedded null byte"):
                self.execute([str(self.base / "invalid\0interpreter")], admitted.append,
                             {"MORU_LAUNCHER_BACKEND": backend})
            self.assertEqual([], admitted)

    def test_missing_interpreter_guard_negative_control_exposes_exit_difference(self):
        command = [str(self.base / "missing-interpreter")]
        self.assertEqual((1, 0, False), self.execute(command,
                                                  extra_env={"MORU_LAUNCHER_BACKEND": "python"}))
        with patch.object(adapter, "_native_executable", return_value=True):
            observed = self.execute(command)
        self.assertEqual((127, 0, False), observed)
        with self.assertRaises(AssertionError):
            self.assertEqual((1, 0, False), observed)

    def test_relative_executable_keeps_execv_compatibility_profile(self):
        command = [Path(sys.executable).name, "-c", "pass"]
        self.assertEqual([sys.executable, "-I", "-S", str(RUNNER), *command],
                         adapter.admission_bootstrap(command, RUNNER, dict(os.environ)))
        done = subprocess.run([str(NATIVE), str(RUNNER), "--unittest-admission", *command],
                              input=b"\x01", capture_output=True, timeout=5)
        self.assertEqual(2, done.returncode)

    def test_stale_sources_or_executable_fall_back_without_running_candidate(self):
        source = copied_build_root(self.base / "source")
        runner = source / "scripts/agent_unittest_result.py"
        binary = source / ".moru/native/bin/moru-native-launcher"
        marker = self.project / ".moru/old-launcher-ran"
        binary.write_text(f"#!/bin/sh\n/usr/bin/touch '{marker}'\nexit 99\n")
        binary.chmod(0o755)
        receipt_path = source / ".moru/native/build.json"
        receipt = json.loads(receipt_path.read_text())
        for stale in ("binary", "source"):
            with self.subTest(stale=stale):
                if stale == "source":
                    receipt["launcher"]["sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
                    receipt["source_sha256"].pop("native/checkout-identity/src/unittest_admission.rs")
                    receipt_path.write_text(json.dumps(receipt))
                destination = self.project / f".moru/receipt-{stale}.json"
                command = [sys.executable, "-B", str(runner), str(self.project),
                           str(self.project / "tests"), "test_*.py", str(destination)]
                bootstrap = adapter.admission_bootstrap(command, runner, dict(os.environ))
                self.assertEqual([sys.executable, "-I", "-S", str(runner)], bootstrap[:4])
                done = subprocess.run(bootstrap, cwd=self.project, input=b"\x01", capture_output=True,
                                      env={**os.environ, "MORU_UNITTEST_ADMISSION": "1"}, timeout=5)
                self.assertEqual(0, done.returncode, done.stderr)
                self.assertEqual({
                    "tests_run": 0,
                    "successful": False,
                    "passed_count": 0,
                    "skip_events": 0,
                    "passed_ids": [],
                    "failed_ids": [],
                    "passed_selectors": [],
                    "failed_selectors": [],
                    "ids_complete": True,
                }, json.loads(destination.read_text()))
                self.assertFalse(marker.exists(), "no old-launcher capability probe is permitted")

    def test_denial_prevents_startup_and_kills_the_native_group(self):
        marker, env_marker, extra = _startup_fixture(self.project)
        command = [str(self.project / ".venv/bin/python"), "-c", "raise SystemExit(91)"]
        admitted = []

        def deny(pid):
            admitted.append(pid)
            time.sleep(0.1)
            self.assertFalse(marker.exists())
            self.assertFalse(env_marker.exists())
            raise PermissionError("denied")

        with patch.object(verify.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            with self.assertRaisesRegex(PermissionError, "denied"):
                self.execute(command, deny, {"PYTHONPATH": str(extra)})
            self.assert_native(popen)
        for effect in (marker, env_marker):
            self.assertFalse(effect.exists())
        with self.assertRaises(ChildProcessError):
            os.waitpid(admitted[0], os.WNOHANG)
        with self.assertRaises(ProcessLookupError):
            os.killpg(admitted[0], 0)

    def test_startup_observer_rejects_pre_admission_interpreter_negative_control(self):
        marker, _, extra = _startup_fixture(self.project)
        command = [str(self.project / ".venv/bin/python"), "-B", str(RUNNER),
                   str(self.project), str(self.project / "tests"), "test_*.py"]

        def observe(pid):
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(marker.exists(), "selected startup preceded admission")

        with patch.object(adapter, "admission_bootstrap", side_effect=lambda command, runner, environment: command):
            with self.assertRaisesRegex(AssertionError, "selected startup preceded admission"):
                self.execute(command, observe, {"PYTHONPATH": str(extra)})


if __name__ == "__main__":
    unittest.main()
