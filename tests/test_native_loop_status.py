"""Exercise explicit-run native status with synthetic persisted loop state."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from native_pretool_support import environment, prepare
from agent_run_owner import process_owner
from test_agent_loop_contract import valid_state


class NativeLoopStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="moru-loop-status-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.launcher, self.project = prepare(base)
        self.env = environment(base)
        self.empty = base / "empty"
        self.empty.mkdir()
        self.state = valid_state()
        self.run_id = self.state["run_id"]
        self.path = self.project / ".moru" / "runs" / self.run_id / "loop.json"
        self.path.parent.mkdir(parents=True)

    def invoke(self, *args, backend="auto", **env):
        path = str(self.empty) if backend == "auto" else os.environ["PATH"]
        return subprocess.run([str(self.launcher), "loop", *args], cwd=self.project,
            env={**self.env, "PATH": path, "MORU_LAUNCHER_BACKEND": backend, **env},
            capture_output=True, timeout=10)

    def status(self, backend="auto"):
        return self.invoke("status", "--run-id", self.run_id, "--project", str(self.project),
                           backend=backend)

    def write(self, state):
        self.path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return self.path.read_bytes()

    def test_valid_persisted_states_and_json_order_match_python_without_python_on_path(self):
        self.state["accepted"]["owned"]["한글"] = {"z": 10**30, "a": [-0.0, 0.25]}
        self.state["config"]["objective"] = "상태 읽기"
        history = {"id": "f" * 32, "hypothesis": "accepted", "started_at": 100,
                   "calls": 1, "result": None, "verdict": "accepted"}
        observation = {"goal": {"exit": 1, "tests": 1, "passed": False},
                       "regression": {"exit": 0, "tests": 2, "passed": True},
                       "timely": True, "value": 5.0}
        self.state.update(history=[history], baseline_result=observation)
        for status, expected in (("ready", 0), ("checking", 0), ("evaluated", 0), ("exhausted", 4)):
            with self.subTest(status=status):
                self.state["status"] = status
                self.state["inflight"] = {"owner": 123, "groups": [456]} if status == "checking" else None
                attempt = None
                if status == "evaluated":
                    attempt = {**history, "id": "e" * 32, "verdict": "pending",
                               "result": {**observation, "candidate": self.state["accepted"]}}
                self.state.update(attempt=attempt, iterations=1 + int(attempt is not None),
                                  model_calls=1 + int(attempt is not None))
                before = self.write(self.state)
                native = self.status()
                python = self.status(backend="python")
                self.assertEqual((expected, python.stdout, b""),
                                 (native.returncode, native.stdout, native.stderr))
                self.assertEqual(expected, python.returncode)
                self.assertEqual(self.state, json.loads(native.stdout))
                self.assertEqual(before, self.path.read_bytes())
        implicit_project = self.invoke("status", f"--run-id={self.run_id}")
        self.assertEqual((4, self.status().stdout, b""),
                         (implicit_project.returncode, implicit_project.stdout, implicit_project.stderr))

    def test_invalid_history_deadline_results_and_symlinks_do_not_emit_native_status(self):
        valid = {"goal": {"exit": 0, "tests": 0, "passed": True},
                 "regression": {"exit": 0, "tests": 1, "passed": True},
                 "timely": True, "value": None}
        invalid = ({"deadline": 161.0}, {"iterations": 1}, {"baseline_result": valid},
                   {"iterations": 0.0}, {"model_calls": -1}, {"status": "unknown"},
                   {"inflight": {"owner": 1, "groups": [1]}},
                   {"run_id": "b" * 32}, {"accepted": {}},
                   {"accepted": {**self.state["accepted"], "owned": {"x": float("inf")}}})
        for update in invalid:
            with self.subTest(update=update):
                before = self.write({**copy.deepcopy(self.state), **update})
                native = self.status()
                python = self.status(backend="python")
                self.assertEqual((127, b""), (native.returncode, native.stdout))
                self.assertEqual((2, b""), (python.returncode, python.stdout))
                self.assertEqual(before, self.path.read_bytes())

        before = self.write(self.state)
        other = self.project / "elsewhere.json"
        self.path.rename(other)
        self.path.symlink_to(other)
        self.assertEqual(127, self.status().returncode)
        self.assertEqual(2, self.status(backend="python").returncode)
        self.assertEqual(before, other.read_bytes())

    def test_mutation_and_missing_binding_stay_outside_native_status(self):
        before = self.write(self.state)
        for args in (("begin", "--run-id", self.run_id, "--hypothesis", "try"), ("status",)):
            done = self.invoke(*args)
            self.assertEqual((127, b""), (done.returncode, done.stdout))
            self.assertEqual(before, self.path.read_bytes())

    def binding(self, run_id, session, *, runtime="codex", generation=2):
        evidence = self.path.parent.parent / run_id / "preflight.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"runtime_session": {
            "runtime":runtime,"session_id":session,"resume_generation":generation}}))
        state = copy.deepcopy(self.state)
        state["run_id"] = run_id
        evidence.with_name("loop.json").write_text(json.dumps(state))
        return {"run_id":run_id,"evidence_name":"preflight.json","state":"running",
                "resume_generation":generation,"evidence_key":hashlib.sha256(
                    evidence.relative_to(self.project).as_posix().encode()).hexdigest()}

    def registry(self, rows):
        directory = self.project / ".moru"
        for name in (".state.lock.lock",".run-registry.json.lock"):
            (directory / name).touch()
        (directory / "run-registry.json").write_text(json.dumps({"schema_version":1,"runs":rows}))

    def test_inferred_status_selects_bound_generation_and_preserves_mixed_runtime_precedence(self):
        own = self.binding(self.run_id, "codex-session")
        peer = self.binding("b" * 32,"claude-session",runtime="claude")
        self.registry([own,peer])
        for env in ({"CODEX_THREAD_ID":"codex-session"},
                    {"CODEX_THREAD_ID":"codex-session","CLAUDE_CODE_SESSION_ID":"claude-session"}):
            with self.subTest(env=env):
                native = self.invoke("status", **env)
                reference = self.invoke("status", backend="python", **env)
                self.assertEqual((0,reference.stdout,b""),(native.returncode,native.stdout,native.stderr))
                self.assertEqual(0, reference.returncode)
        self.registry([own,peer,{**own,"resume_generation":3}])
        self.assertEqual(127,self.invoke("status", CODEX_THREAD_ID="codex-session").returncode)
        self.assertEqual(2,self.invoke("status", backend="python",CODEX_THREAD_ID="codex-session").returncode)

    def test_shared_session_status_declines_ambiguity_and_honors_exact_process_owner(self):
        own = self.binding(self.run_id,"shared-session")
        peer = self.binding("b" * 32,"shared-session")
        self.registry([own,peer])
        env = {"CODEX_THREAD_ID":"shared-session"}
        native = self.invoke("status", **env)
        self.assertEqual((127,b""),(native.returncode,native.stdout))
        self.assertEqual(2,self.invoke("status", backend="python", **env).returncode)

        owner = process_owner()
        self.assertTrue(owner)
        self.registry([{**own,"owner":owner}, peer])
        native = self.invoke("status", **env)
        reference = self.invoke("status", backend="python", **env)
        self.assertEqual((0,reference.stdout,b""),(native.returncode,native.stdout,native.stderr))
        self.assertEqual(self.run_id,json.loads(native.stdout)["run_id"])

    def test_process_only_status_selects_one_exact_owner_and_current_generation(self):
        owner = process_owner()
        self.assertTrue(owner)
        own = {**self.binding(self.run_id, "owned-session", runtime=" AGY "), "owner": owner}
        peer = {**self.binding("b" * 32, "peer-session", runtime="cli"),
                "owner": {**owner, "start_token": "different-birth"}}
        self.registry([own, peer])

        native = self.invoke("status")
        reference = self.invoke("status", backend="python")
        self.assertEqual((0, reference.stdout, b""),
                         (native.returncode, native.stdout, native.stderr))
        self.assertEqual(0, reference.returncode)
        self.assertEqual(self.run_id, json.loads(native.stdout)["run_id"])

        for label, rows, env in (
            ("reused pid", [peer], {}),
            ("same-owner ambiguity", [own, {**peer, "owner": owner}], {}),
            ("superseded generation", [own, {**own, "resume_generation": 3}], {}),
            ("settled latest record", [own, {**own, "state": "completed"}], {}),
            ("worker override", [own], {"MORU_WORKER_EVIDENCE": "ignored-worker.json"}),
            ("runtime id never falls back", [own], {"CODEX_THREAD_ID": "unbound"}),
        ):
            with self.subTest(label=label):
                self.registry(rows)
                native = self.invoke("status", **env)
                reference = self.invoke("status", backend="python", **env)
                self.assertEqual((127, b""), (native.returncode, native.stdout))
                self.assertEqual((2, b""), (reference.returncode, reference.stdout))

        for runtime in ("claude", "codex"):
            with self.subTest(runtime=runtime):
                strict = self.binding(self.run_id, "strict-session", runtime=runtime)
                self.registry([{**strict, "owner": owner}])
                self.assertEqual(127, self.invoke("status").returncode)
                self.assertEqual(2, self.invoke("status", backend="python").returncode)
