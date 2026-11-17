"""Real admitted worker lifetime, native selection and original receipt parity."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_scheduler import claim_task, enqueue_task
from native_pretool_support import environment
import workflow_dispatch_process as source

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / ".moru/native/bin/moru-native-launcher"
GUARDIAN = ROOT / "scripts/workflow_dispatch_guardian.py"
BASELINE = "7b6b230ed8ea49594d3117a1e12e7c63efa243b6"
STATE = {"run_id": "run", "task_id": "task", "attempt": 1, "execution_id": "e" * 32, "state": "admitted"}
SAFE_BOOTSTRAP_FLAGS = {"PYTHONUTF8", "PYTHONCOERCECLOCALE", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"}


def inherited_environment(base=None):
    env = environment(base) if base is not None else dict(os.environ)
    for name in list(env):
        if name.startswith(('PYTHON', '_PYTHON')):
            env.pop(name)
    env.update({name: value for name, value in os.environ.items() if name in SAFE_BOOTSTRAP_FLAGS})
    env['PYTHONNOUSERSITE'] = '1'
    return env


class NativeDispatchGuardianTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-dispatch-guardian-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "project 한글"
        self.project.mkdir()
        (self.base / "home").mkdir()
        self.env = inherited_environment(self.base)

    def run_worker(self, command, *, backend="auto", environment_extra=None, before_start=None, run_id="synthetic"):
        env = {**self.env, "MORU_LAUNCHER_BACKEND": backend, **(environment_extra or {})}
        with patch.dict(os.environ, env, clear=True):
            task = enqueue_task(self.project, run_id, max_retries=1)
            task = claim_task(self.project, task["task_id"])
            output = self.base / "stdout"
            with output.open("wb") as stream, patch.object(source.subprocess, "Popen", wraps=subprocess.Popen) as popen:
                result = source.run_worker(command, env=dict(env), stdout=stream,
                                           project=self.project, task=task, before_start=before_start)
        return result, popen, output.read_bytes()

    def assert_native(self, popen):
        self.assertEqual(1, popen.call_count)
        self.assertEqual([str(NATIVE), str(GUARDIAN), "--dispatch-guardian"],
                         popen.call_args.args[0][:3])

    def test_real_worker_selects_source_bound_native_guardian_before_spawn(self):
        result, popen, stdout = self.run_worker(["/bin/sh", "-c", "printf 'worker output'"])
        self.assertEqual((0, b"worker output"), (result.returncode, stdout))
        self.assert_native(popen)
        receipts = list(self.project.rglob("worker-executions/*.json"))
        self.assertEqual(1, len(receipts))
        self.assertEqual("finished", json.loads(receipts[0].read_text())["state"])

    def test_spooled_dispatch_end_to_end_uses_native_guardian_and_delivers_result_packet(self):
        from workflow_dispatch_launch import _run_spooled_worker
        from workflow_dispatch_handoff import worker_output_paths
        prepared = {"preflight_evidence": str(self.base / "preflight.json"),
                    "execution_capsule": {"reusable": True}}
        with patch.dict(os.environ, self.env, clear=True):
            task = enqueue_task(self.project, "synthetic", max_retries=1)
            task = claim_task(self.project, task["task_id"])
            paths = worker_output_paths(prepared)
            command = ["/bin/sh", "-c", 'printf \'{"status":"ok"}\' > "$1"', "owned", paths["last_message_path"]]
            with patch.object(source.subprocess, "Popen", wraps=subprocess.Popen) as popen:
                outcome = _run_spooled_worker(command, prepared, task, "", project=self.project)
        self.assert_native(popen)
        self.assertEqual(0, outcome.returncode)
        self.assertEqual("ok", json.loads(Path(paths["result_path"]).read_text())["status"])

    def test_forced_python_does_not_probe_or_launch_a_native_candidate(self):
        with patch("support.native_launcher_install.artifact_plan", side_effect=AssertionError("unexpected probe")):
            result, popen, stdout = self.run_worker(["/bin/sh", "-c", "printf compatibility"], backend="python")
        self.assertEqual((0, b"compatibility"), (result.returncode, stdout))
        self.assertEqual([sys.executable, str(GUARDIAN)], popen.call_args.args[0][:2])

    def startup_fixture(self):
        marker = self.base / "interpreter-started"
        startup = self.base / "startup"
        startup.mkdir()
        (startup / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('started')\n")
        empty = self.base / "empty-path"
        empty.mkdir()
        return marker, {"PYTHONPATH": str(startup), "PATH": str(empty)}

    def test_guardian_and_exec_gate_execute_with_python_absent_from_path(self):
        empty = self.base / "empty-path"
        empty.mkdir()
        result, popen, stdout = self.run_worker(["/bin/sh", "-c", "printf native"], environment_extra={"PATH": str(empty)})
        self.assertEqual((0, b"native"), (result.returncode, stdout))
        self.assert_native(popen)

    def test_startup_observer_detects_python_rollback_negative_control(self):
        marker, extra = self.startup_fixture()
        result, _, stdout = self.run_worker(["/bin/sh", "-c", "printf reference"], backend="python", environment_extra=extra)
        self.assertEqual((0, b"reference"), (result.returncode, stdout))
        with self.assertRaises(AssertionError):
            self.assertFalse(marker.exists(), "observer must see original interpreter startup")

    def test_worker_stdin_is_eof_and_selected_environment_cwd_and_exit_survive(self):
        program = "printf '%s\\n' \"$SYNTHETIC_VALUE\"; pwd; if IFS= read -r line; then printf bad; else printf eof; fi; exit 7"
        result, popen, stdout = self.run_worker(["/bin/sh", "-c", program], environment_extra={"SYNTHETIC_VALUE": "preserved 한글"})
        self.assert_native(popen)
        self.assertEqual((7, f"preserved 한글\n{Path.cwd()}\neof".encode()), (result.returncode, stdout))
        receipt = next(self.project.rglob("worker-executions/*.json")).read_text()
        self.assertNotIn("SYNTHETIC_VALUE", receipt)
        self.assertNotIn("preserved", receipt)
        self.assertEqual(("finished", 7), (json.loads(receipt)["state"], json.loads(receipt)["returncode"]))

    def test_signal_exit_is_recorded_as_128_plus_signal(self):
        result, popen, stdout = self.run_worker(["/bin/sh", "-c", "kill -TERM $$"])
        self.assert_native(popen)
        self.assertEqual((143, b""), (result.returncode, stdout))
        receipt = json.loads(next(self.project.rglob("worker-executions/*.json")).read_text())
        self.assertEqual(("finished", 143), (receipt["state"], receipt["returncode"]))

    def test_running_receipt_failure_never_releases_the_gated_worker(self):
        marker = self.base / "unexpected-exec"
        directories = []
        def make_readonly():
            directory = next(self.project.rglob("worker-executions"))
            directory.chmod(0o500)
            directories.append(directory)
        try:
            result, popen, stdout = self.run_worker(["/bin/sh", "-c", 'printf bad > "$1"', "owned", str(marker)], before_start=make_readonly)
            self.assert_native(popen)
            self.assertEqual((125, b""), (result.returncode, stdout))
            self.assertFalse(marker.exists())
            receipt = json.loads(next(self.project.rglob("worker-executions/*.json")).read_text())
            self.assertEqual("admitted", receipt["state"])
        finally:
            for directory in directories:
                directory.chmod(0o700)

    def test_final_receipt_failure_keeps_running_uncertainty_and_never_replays(self):
        location = self.base / "receipt-directory"
        marker = self.base / "worker-ran"
        directories = []
        def record_location():
            directory = next(self.project.rglob("worker-executions"))
            location.write_text(str(directory))
            directories.append(directory)
        program = ("import sys; from pathlib import Path; "
                   "Path(sys.argv[2]).write_text('once'); "
                   "Path(Path(sys.argv[1]).read_text()).chmod(0o500)")
        try:
            result, popen, stdout = self.run_worker([sys.executable, "-c", program, str(location), str(marker)],
                                                   before_start=record_location)
            self.assert_native(popen)
            self.assertEqual((125, b""), (result.returncode, stdout))
            self.assertEqual("once", marker.read_text())
            receipt = json.loads(next(self.project.rglob("worker-executions/*.json")).read_text())
            self.assertEqual("running", receipt["state"])
            self.assertNotIn("returncode", receipt)
        finally:
            for directory in directories:
                directory.chmod(0o700)

    def test_selected_native_failure_is_not_replayed_in_python(self):
        candidate = self.base / "selected-candidate"
        candidate.write_text("#!/bin/sh\nprintf 'uncertain candidate'\nexit 125\n")
        candidate.chmod(0o700)
        marker = self.base / "must-not-run"
        with patch("support.native_launcher_install.artifact_plan", return_value={"source": candidate}):
            result, popen, stdout = self.run_worker(["/bin/sh", "-c", 'printf bad > "$1"', "owned", str(marker)])
        self.assertEqual(1, popen.call_count)
        self.assertEqual(str(candidate), popen.call_args.args[0][0])
        self.assertEqual((125, b"uncertain candidate"), (result.returncode, stdout))
        self.assertFalse(marker.exists())
        receipt = json.loads(next(self.project.rglob("worker-executions/*.json")).read_text())
        self.assertEqual("admitted", receipt["state"])

    def test_worker_environment_iteration_order_matches_the_requested_mapping(self):
        keys = ("GUARDIAN_ORDER_Z", "GUARDIAN_ORDER_A", "GUARDIAN_ORDER_M")
        program = "import json,os; print(json.dumps([k for k in os.environ if k.startswith('GUARDIAN_ORDER_')]))"
        result, popen, stdout = self.run_worker([sys.executable, "-c", program], environment_extra=dict.fromkeys(keys, "value"))
        self.assert_native(popen)
        self.assertEqual((0, list(keys)), (result.returncode, json.loads(stdout)))

    def test_worker_is_its_own_group_leader_and_inherits_no_guardian_lock(self):
        program = ("import fcntl,json,os\n"
                   "def opened(n):\n"
                   " try: fcntl.fcntl(n, fcntl.F_GETFD); return True\n"
                   " except OSError: return False\n"
                   "descriptors = os.listdir('/dev/fd')\n"
                   "print(json.dumps({'pid':os.getpid(),'pgid':os.getpgid(0),"
                   "'fds':[int(n) for n in descriptors if int(n)>2 and opened(int(n))]}))\n")
        result, popen, stdout = self.run_worker([sys.executable, "-c", program])
        self.assert_native(popen)
        self.assertEqual(0, result.returncode)
        observed = json.loads(stdout)
        self.assertEqual(observed["pid"], observed["pgid"])
        self.assertEqual([], observed["fds"])

    def test_surrogate_receipt_identity_keeps_python_before_native_selection(self):
        result, popen, stdout = self.run_worker(["/bin/sh", "-c", "printf compatibility"], run_id="run\ud800")
        self.assertEqual((0, b"compatibility"), (result.returncode, stdout))
        self.assertEqual([sys.executable, str(GUARDIAN)], popen.call_args.args[0][:2])


class GuardianSelectionCompatibilityTests(unittest.TestCase):
    def test_relative_guardian_carrier_keeps_legacy_instead_of_native_refusal(self):
        inherited = inherited_environment()
        relative = GUARDIAN.relative_to(ROOT)
        path = Path('/owned/receipt.json')
        with patch.dict(os.environ, inherited, clear=True):
            self.assertEqual([sys.executable, str(relative), str(path)],
                             source._guardian_command(relative, path, ['/bin/sh'], inherited, STATE))

    def test_unsupported_objects_and_raw_strings_decline_before_artifact_lookup(self):
        path = Path("/owned/receipt.json")
        inherited = inherited_environment()
        class Opaque(dict):
            def get(self, *args):
                raise AssertionError("opaque get")
            def values(self):
                raise AssertionError("opaque values")
        with patch.dict(os.environ, inherited, clear=True), \
             patch("support.native_launcher_install.artifact_plan", side_effect=AssertionError("unsupported probe")):
            for command, env in ((["/bin/sh"], Opaque()), (["/bin/sh", "\udcff"], inherited),
                                 (["/bin/sh"], {**inherited, "raw": "\udcff"}), (["/bin/sh"], {**inherited, "bad": 1}),
                                 (["/bin/sh"], {**inherited, "MORU_LAUNCHER_BACKEND": "python"})):
                with self.subTest(command=command, env_type=type(env)):
                    self.assertEqual([sys.executable, str(GUARDIAN), str(path)],
                                     source._guardian_command(GUARDIAN, path, command, env, STATE))

    def test_stale_artifact_selects_compatibility_without_a_capability_probe(self):
        path = Path("/owned/receipt.json")
        inherited = inherited_environment()
        with patch.dict(os.environ, inherited, clear=True), \
             patch("support.native_launcher_install.artifact_plan", return_value=None) as plan, \
             patch.object(subprocess, "run", side_effect=AssertionError("capability process")):
            self.assertEqual([sys.executable, str(GUARDIAN), str(path)],
                             source._guardian_command(GUARDIAN, path, ["/bin/sh"],
                                 inherited, STATE))
        plan.assert_called_once_with(ROOT, GUARDIAN)

    def test_unsupported_receipt_profiles_decline_before_artifact_lookup(self):
        for field, value in (("attempt", True), ("attempt", 0), ("attempt", 2**63),
                             ("run_id", "run\ud800"), ("task_id", []), ("state", "running")):
            with self.subTest(field=field, value_type=type(value)), \
                 patch("support.native_launcher_install.artifact_plan", side_effect=AssertionError("unsupported state probe")):
                path = Path("/owned/receipt.json")
                self.assertEqual([sys.executable, str(GUARDIAN), str(path)],
                                 source._guardian_command(GUARDIAN, path, ["/bin/sh"], dict(os.environ), {**STATE, field: value}))

    def test_executable_bootstrap_overrides_decline_even_when_snapshot_matches(self):
        inherited = inherited_environment()
        for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', '_PYTHON_SYSCONFIGDATA_NAME'):
            with self.subTest(name=name), patch.dict(os.environ, {**inherited, name: 'owned override'}, clear=True), \
                 patch.object(source, '_GUARDIAN_BOOTSTRAP_ENV', {**source._GUARDIAN_BOOTSTRAP_ENV, name: 'owned override'}):
                self.assertFalse(source._guardian_environment_profile(dict(os.environ)))


class StartupOverrideCompatibilityTests(unittest.TestCase):
    def test_unchanged_startup_override_preserves_reference_environment_and_detects_native_mutant(self):
        with tempfile.TemporaryDirectory(prefix='guardian-bootstrap-') as temporary:
            base = Path(temporary).resolve()
            (base / 'home').mkdir()
            startup = base / 'startup'
            startup.mkdir()
            (startup / 'sitecustomize.py').write_text(
                "import os\nos.environ['GUARDIAN_STARTUP_COUNT'] = str(int(os.environ.get('GUARDIAN_STARTUP_COUNT','0'))+1)\n")
            supervisor = base / 'supervisor.py'
            supervisor.write_text(
                "import json,os,subprocess,sys,tempfile\nfrom pathlib import Path\n"
                "from agent_scheduler import enqueue_task,claim_task\nimport workflow_dispatch_process as p\n"
                "if sys.argv[2]=='mutant': p._guardian_environment_profile=lambda env: True\n"
                "project=Path(sys.argv[1]);project.mkdir()\n"
                "task=enqueue_task(project,'fixture',max_retries=1);task=claim_task(project,task['task_id'])\n"
                "observed=[];original=p.subprocess.Popen\n"
                "def spawn(argv,*args,**kw):\n observed.append(argv[0]!=sys.executable);return original(argv,*args,**kw)\n"
                "p.subprocess.Popen=spawn\n"
                "with tempfile.TemporaryFile() as output:\n"
                " result=p.run_worker(['/bin/sh','-c','printf %s \"$GUARDIAN_STARTUP_COUNT\"'],"
                "env=dict(os.environ),stdout=output,project=project,task=task)\n"
                " output.seek(0);counter=output.read().decode()\n"
                "print(json.dumps({'code':result.returncode,'native':observed,'counter':counter}))\n")
            env = {**inherited_environment(base), 'PYTHONPATH': str(startup) + os.pathsep + str(ROOT / 'scripts')}
            for mode, expected in (('ordinary', {'code': 0, 'native': [False], 'counter': '2'}),
                                   ('mutant', {'code': 0, 'native': [True], 'counter': '1'})):
                with self.subTest(mode=mode):
                    done = subprocess.run([sys.executable, '-B', str(supervisor), str(base / mode), mode],
                                          env=env, capture_output=True, timeout=8)
                    self.assertEqual((0, b''), (done.returncode, done.stderr))
                    self.assertEqual(expected, json.loads(done.stdout))


class DirectGuardianOracleTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        # Keep the real dependency layout when the original self-spawns its
        # gate with the requested environment (which need not have PYTHONPATH).
        cls.original = ROOT / "scripts"
        for name in ("workflow_dispatch_guardian.py", "workflow_dispatch_execution.py"):
            raw = subprocess.run(["git", "show", BASELINE + ":scripts/" + name],
                                 cwd=ROOT, check=True, capture_output=True, timeout=5).stdout
            if (cls.original / name).read_bytes() != raw:
                raise AssertionError("immutable Python guardian/receipt oracle changed: " + name)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="guardian-protocol-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / "home").mkdir()
        self.worker_env = inherited_environment(self.base)
        self.env = {**self.worker_env, "PYTHONPATH": str(ROOT / "scripts")}
        self.state = {"run_id": "run 한글", "task_id": "task", "attempt": 1,
                      "execution_id": "e" * 32, "state": "admitted"}

    def guard(self, command, *, original=False, parent_eof=False, symlink=False, raw=None, worker_env=None, select=False):
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            directory = Path(temporary)
            receipt = directory / "receipt.json"
            receipt.write_text(json.dumps(self.state))
            if symlink:
                receipt.rename(directory / "target.json")
                receipt.symlink_to("target.json")
            requested = self.worker_env if worker_env is None else worker_env
            args = ([sys.executable, str(self.original / GUARDIAN.name), str(receipt)] if original else
                    source._guardian_command(GUARDIAN, receipt, command, requested, self.state) if select else
                    [str(NATIVE), str(GUARDIAN), "--dispatch-guardian", str(receipt)])
            proc = subprocess.Popen(args, cwd=self.base, env=self.env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
            try:
                payload = raw if raw is not None else json.dumps({"command": command, "env": requested}).encode() + b"\n"
                proc.stdin.write(payload)
                proc.stdin.flush()
                if parent_eof:
                    proc.stdin.close()
                code = proc.wait(timeout=5)
                stdout, stderr = proc.stdout.read(), proc.stderr.read()
                return code, stdout, stderr, receipt.read_bytes(), receipt.stat().st_mode & 0o777, sorted(p.name for p in directory.iterdir())
            finally:
                if not proc.stdin.closed:
                    proc.stdin.close()
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
                proc.stdout.close()
                proc.stderr.close()

    def same(self, command, **options):
        expected = self.guard(command, original=True, **options)
        actual = self.guard(command, **options)
        self.assertEqual(expected, actual)
        return actual

    def test_success_receipt_has_exact_original_bytes_mode_and_no_temporary_files(self):
        actual = self.same(["/bin/sh", "-c", 'printf "%s" "$VALUE"'], worker_env={**self.worker_env, "VALUE": "한글"})
        self.assertEqual((0, "한글".encode(), b""), actual[:3])
        self.assertEqual(0o600, actual[4])
        self.assertEqual(["receipt.json"], actual[5])

    def test_requested_worker_environment_matches_original_without_reordering(self):
        import hashlib
        expected = self.guard(["/usr/bin/env"], original=True)
        actual = self.guard(["/usr/bin/env"])
        # Never dump the inherited environment in a failing assertion.
        self.assertEqual(expected[:1] + expected[2:], actual[:1] + actual[2:])
        self.assertEqual(hashlib.sha256(expected[1]).hexdigest(), hashlib.sha256(actual[1]).hexdigest())

    def test_minimal_environment_uses_python_before_native_to_preserve_bootstrap_fields(self):
        requested = {"PATH": "", "VALUE": "한글", "HOME": str(self.base / "home"),
                     "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        expected = self.guard(["/usr/bin/env"], original=True, worker_env=requested)
        actual = self.guard(["/usr/bin/env"], select=True, worker_env=requested)
        self.assertEqual(expected, actual)

    def test_environment_profile_observer_rejects_forced_native_negative_control(self):
        import hashlib
        requested = {"PATH": "", "VALUE": "한글", "HOME": str(self.base / "home"),
                     "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        expected = self.guard(["/usr/bin/env"], original=True, worker_env=requested)
        with patch.object(source, "_guardian_environment_profile", return_value=True):
            actual = self.guard(["/usr/bin/env"], select=True, worker_env=requested)
        self.assertEqual(0, actual[0])
        with self.assertRaises(AssertionError):
            self.assertEqual(hashlib.sha256(expected[1]).hexdigest(), hashlib.sha256(actual[1]).hexdigest())

    def test_nonzero_and_signal_completion_keep_exact_original_receipts(self):
        for script, code in (("exit 7", 7), ("kill -TERM $$", 143)):
            with self.subTest(script=script):
                actual = self.same(["/bin/sh", "-c", script])
                self.assertEqual((code, b"", b""), actual[:3])

    def test_parent_eof_before_release_keeps_worker_unexecuted(self):
        marker = self.base / "unexpected"
        actual = self.same(["/bin/sh", "-c", 'printf bad > "$1"', "owned", str(marker)], parent_eof=True)
        self.assertEqual((130, b"", b""), actual[:3])
        self.assertFalse(marker.exists())
        self.assertEqual("interrupted", json.loads(actual[3])["state"])

    def test_symlink_receipt_refuses_before_releasing_work(self):
        marker = self.base / "unexpected"
        actual = self.same(["/bin/sh", "-c", 'printf bad > "$1"', "owned", str(marker)], symlink=True)
        self.assertEqual((125, b"", b""), actual[:3])
        self.assertFalse(marker.exists())
        self.assertEqual(self.state, json.loads(actual[3]))

    def test_truncated_and_malformed_lines_preserve_silent_exit_and_receipt(self):
        for raw, code in ((b"", 130), (b"{", 130), (b"{\n", 125)):
            with self.subTest(raw=raw):
                actual = self.same(["/bin/sh"], parent_eof=True, raw=raw)
                self.assertEqual((code, b"", b""), actual[:3])
                self.assertEqual(self.state, json.loads(actual[3]))

    def test_exec_gate_preserves_pid_worker_stdin_and_missing_exec_failure(self):
        for command, expected_code in ((["/bin/sh", "-c", 'printf "%s " "$$"; if IFS= read -r line; then printf bad; else printf eof; fi'], 0),
                                       ([str(self.base / "missing")], 127)):
            for original in (False, True):
                with self.subTest(original=original, command=command[0]):
                    args = ([sys.executable, str(self.original / GUARDIAN.name), "--exec-gate"] if original
                            else [str(NATIVE), str(GUARDIAN), "--dispatch-exec-gate"])
                    proc = subprocess.Popen(args, cwd=self.base, env=self.env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                    try:
                        stdout, stderr = proc.communicate(json.dumps(command).encode() + b"\n", timeout=5)
                        self.assertEqual((expected_code, b""), (proc.returncode, stderr))
                        self.assertEqual(f"{proc.pid} eof".encode() if expected_code == 0 else b"", stdout)
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait(timeout=2)

    def test_guardian_keeps_inherited_lock_until_eof_cleanup_finishes(self):
        receipt = self.base / "receipt.json"
        receipt.write_text(json.dumps(self.state))
        lock_path = self.base / "execution.lock"
        lock = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = self.base / "started"
        proc = subprocess.Popen([str(NATIVE), str(GUARDIAN), "--dispatch-guardian", str(receipt)],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=self.base, env=self.env, pass_fds=(lock,), start_new_session=True)
        try:
            command = ["/bin/sh", "-c", 'printf started > "$1"; exec /bin/sleep 10', "owned", str(marker)]
            proc.stdin.write(json.dumps({"command": command, "env": {"PATH": ""}}).encode() + b"\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 3
            while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.exists(), "owned worker did not start")
            os.close(lock)
            lock = None
            with lock_path.open("r+b") as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            proc.stdin.close()
            self.assertEqual(130, proc.wait(timeout=5))
            with lock_path.open("r+b") as probe:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual("interrupted", json.loads(receipt.read_text())["state"])
        finally:
            if lock is not None:
                os.close(lock)
            if not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
