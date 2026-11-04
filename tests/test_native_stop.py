"""Native quiet proof never replaces active Stop authority or state transitions."""
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

from native_pretool_support import environment, result
from native_mailbox_support import reference, restore, snapshot, warm
from native_stop_support import invoke, markers, prepare_stop, stable_state
from test_agent_run_interruption import Run
from agent_continuation_checkpoint import write_continuation_checkpoint


class NativeStopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-stop-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare_stop(self.base)
        scoped = patch.dict(os.environ, environment(self.base), clear=True)
        scoped.start()
        self.addCleanup(scoped.stop)
        self.bin = self.base / "git-only"
        self.bin.mkdir()
        (self.bin / "git").symlink_to(shutil.which("git"))

    def hook(self, runtime="claude", project=None, **kwargs):
        return invoke(self.launcher, self.base, project or self.project, runtime, **kwargs)

    def parity(self, runtime="claude", project=None, **kwargs):
        project = project or self.project
        before = snapshot(self.base, project)
        metadata = {path: (stat.S_IMODE((self.base / path).stat().st_mode),
                           (self.base / path).stat().st_mtime_ns)
                    for path, (kind, _) in before.items() if kind != "link"}
        expected = self.hook(runtime, project, backend="python", **kwargs)
        after = stable_state(snapshot(self.base, project))
        restore(self.base, project, before)
        for path, (mode, stamp) in metadata.items():
            os.chmod(self.base / path, mode)
            os.utime(self.base / path, ns=(stamp, stamp))
        actual = self.hook(runtime, project, **kwargs)
        self.assertEqual(result(expected), result(actual))
        # The native progress advisor has its own explicitly tested metadata;
        # compare all delivery/authority state while retaining that boundary.
        def delivery_state(data):
            return {path: value for path, value in data.items()
                    if not re.fullmatch(r"\.?completion-progress-[0-9a-f]{24}\.json(?:\.lock)?", Path(path).name)}
        self.assertEqual(delivery_state(after), delivery_state(stable_state(snapshot(self.base, project))))
        return actual

    def fallback(self, runtime="claude", project=None, **kwargs):
        project = project or self.project
        before = snapshot(self.base, project)
        self.assertEqual(127, self.hook(runtime, project, PATH=str(self.bin), **kwargs).returncode)
        self.assertEqual(before, snapshot(self.base, project))
        return self.parity(runtime, project, **kwargs)

    def fixture(self, runtime="codex", *, version=2, remaining=True, phase="acting"):
        directory = self.base / ("run-" + runtime + str(len(list(self.base.glob("run-*")))))
        directory.mkdir()
        run = Run(str(directory), runtime, version=version, packet=True, writable=True)
        if version == 2:
            write_continuation_checkpoint(project=run.project, rules=run.project, run_id=run.run["run_id"],
                binding_path=run.evidence, kind="initial", phase=phase,
                work={"objective": "Deliver the complete approved fixture", "acceptance_criteria": ["All fixture outputs exist"],
                      "remaining_work": [{"checkpoint": "delivery", "action": "Finish approved outputs"}] if remaining else [],
                      "blockers": ["Waiting on user decision"] if phase == "blocked" else []})
        warm(self.launcher, self.base, run.project, runtime)
        return run

    def test_no_work_and_terminal_history_are_native_for_both_runtimes(self):
        for runtime in ("claude", "codex"):
            self.assertEqual((0, b"", b""), result(self.hook(runtime, PATH=str(self.bin))))
            self.parity(runtime)
        (self.project / ".moru/run-registry.json").unlink()
        for runtime in ("claude", "codex"):
            self.assertEqual((0, b"", b""), result(self.hook(runtime, PATH=str(self.bin))))
            self.parity(runtime)

    def test_settled_and_previously_reported_legacy_edits_are_native(self):
        markers(self.project)
        self.assertEqual((0, b"", b""), result(self.hook(PATH=str(self.bin))))
        self.parity()
        directory = self.project / ".moru/claude-pretool-gate"
        (directory / "synthetic-stop.finished").rename(directory / "synthetic-stop.settled")
        self.assertEqual((0, b"", b""), result(self.hook(PATH=str(self.bin))))
        (directory / "synthetic-stop.settled").rename(directory / "synthetic-stop.stop-blocked")
        self.assertEqual((0, b"", b""), result(self.hook(PATH=str(self.bin))))

    def test_unreported_or_newer_edits_keep_legacy_block_and_marker(self):
        markers(self.project, closed=False)
        done = self.fallback()
        self.assertEqual("block", json.loads(done.stdout)["decision"])
        directory = self.project / ".moru/claude-pretool-gate"
        self.assertTrue((directory / "synthetic-stop.stop-blocked").exists())
        markers(self.project)
        (directory / "synthetic-stop.stop-blocked").unlink()
        os.utime(directory / "synthetic-stop.edited", ns=(300000000000, 300000000000))
        self.assertEqual("block", json.loads(self.fallback().stdout)["decision"])

    def test_active_remaining_work_keeps_current_continuation_for_both_runtimes(self):
        for runtime in ("claude", "codex"):
            run = self.fixture(runtime)
            done = self.fallback(runtime, run.project,
                payload={"cwd": str(run.project), "session_id": "bound-session"})
            self.assertEqual("block", json.loads(done.stdout)["decision"])
            self.assertEqual("running", run.state())
            self.assertFalse(list((run.project / ".moru").rglob("finish.json")))

    def test_approval_stop_flags_and_global_blockers_preserve_interruption(self):
        for runtime in ("claude", "codex"):
            for flags in ({"approval_pending": True}, {"user_interrupted": True},
                          {"stop_hook_active": True}, {"stop_reason": "cancelled"}):
                run = self.fixture(runtime)
                done = self.fallback(runtime, run.project,
                    payload={"cwd": str(run.project), "session_id": "bound-session", **flags})
                self.assertEqual((0, b"", b""), result(done))
                self.assertNotEqual("completed", run.state())
            run = self.fixture(runtime, phase="blocked")
            done = self.fallback(runtime, run.project,
                payload={"cwd": str(run.project), "session_id": "bound-session"})
            self.assertEqual((0, b"", b""), result(done))

    def test_active_v2_boundary_and_legacy_closeout_never_become_native_noops(self):
        for runtime in ("claude", "codex"):
            run = self.fixture(runtime, remaining=False)
            self.fallback(runtime, run.project, payload={"cwd": str(run.project), "session_id": "bound-session"})
            self.assertEqual("interrupted", run.state())
            run = self.fixture(runtime, version=1)
            markers(run.project, "bound-session", closed=False)
            done = self.fallback(runtime, run.project, payload={"cwd": str(run.project), "session_id": "bound-session"})
            self.assertEqual("block", json.loads(done.stdout)["decision"])

    def test_mailbox_ack_still_commits_shown_messages_even_with_gate_disabled(self):
        from agent_mailbox_delivery import SessionDelivery
        for runtime in ("claude", "codex"):
            store = reference(self.base, self.project)
            packet = store.enqueue(sender="codex", recipient=runtime, kind="task", body="Synthetic shown reference.", ttl_seconds=3600)
            delivery = SessionDelivery(self.project, runtime, "synthetic-stop")
            delivery.claim()
            delivery.mark_delivered([packet["message_id"]])
            self.fallback(runtime, **{"MORU_" + runtime.upper() + "_STOP_GATE": "0"})
            self.assertTrue((store.root / "acked" / runtime / (packet["message_id"] + ".json")).is_file())

    def test_unknown_registry_shapes_and_states_select_python(self):
        path = self.project / ".moru/run-registry.json"
        for content in ("{broken", "[]", '{"schema_version":2,"runs":[]}',
                        *[json.dumps({"schema_version":1,"runs":[{"state": state}]})
                          for state in ("running", "paused", "resuming", "claiming", "blocked", "interrupted", "reconcile_required", "unknown")]):
            path.write_text(content)
            for runtime in ("claude", "codex"): self.fallback(runtime)

    def test_registered_other_project_edits_are_not_silenced(self):
        other = self.base / "other"
        other.mkdir()
        (other / ".moru").mkdir()
        markers(other, closed=False)
        index = self.base / "state/claude-session-projects/synthetic-stop"
        index.parent.mkdir(parents=True)
        index.write_text(str(other) + "\n")
        self.assertEqual("block", json.loads(self.fallback(project=other,
            payload={"cwd": str(self.project), "session_id": "synthetic-stop"}).stdout)["decision"])

    def test_missing_busy_and_symlinked_locks_require_compatibility(self):
        path = self.project / ".moru/.state.lock.lock"
        path.unlink()
        self.fallback()
        outside = self.base / "lock"
        path.replace(outside)
        path.symlink_to(outside)
        self.fallback()
        path.unlink()
        outside.replace(path)
        with path.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.assertEqual(127, self.hook(PATH=str(self.bin)).returncode)

    def test_unknown_arguments_payloads_and_python_environment_replay(self):
        self.fallback(extra=("--compat-control",))
        self.fallback(PYTHONPATH="synthetic")
        for payload in (b"{broken", b"[]", {}, {"cwd": str(self.project), "session_id": "id/unsafe"}):
            for runtime in ("claude", "codex"): self.fallback(runtime, payload=payload)
