"""Regression tests for orchestrated headless AGY Moru Core lifecycle defects."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from _moru_test_support import TemplateRepository, fake_vibeguard_environment
import agent_run_owner
import agent_run_registry
import agy_hook_adapter as adapter
import claude_stop_gate
from support import runtime_bridge
from test_work_continuity_lifecycle_e2e import (
    TESTS_GATE,
    environment,
    git,
    hook,
    record_gate,
    run_id,
    start,
)

_MODULE_STATE: list = []


def _build_repo(project: Path) -> None:
    (project / "src").mkdir(parents=True)
    (project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(".moru/\n", encoding="utf-8")
    (project / "README.md").write_text("Baseline.\n", encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.email", "agy-lifecycle@example.invalid")
    git(project, "config", "user.name", "AGY Lifecycle")
    git(project, "add", ".")
    git(project, "commit", "-qm", "fixture")


_FIXTURE = TemplateRepository(_build_repo)


def setUpModule() -> None:
    directory = tempfile.TemporaryDirectory(prefix="moru-agy-lifecycle-")
    state = patch.dict(os.environ, {"MORU_STATE_HOME": directory.name})
    state.start()
    vibeguard = fake_vibeguard_environment()
    vibeguard.start()
    _MODULE_STATE.extend((state, directory, vibeguard))


def tearDownModule() -> None:
    state, directory, vibeguard = _MODULE_STATE
    vibeguard.stop()
    state.stop()
    directory.cleanup()
    _MODULE_STATE.clear()
    _FIXTURE.cleanup()


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


def _runs_by_id(project: Path) -> dict[str, dict]:
    path = project / ".moru" / "run-registry.json"
    return {run["run_id"]: run for run in json.loads(path.read_text(encoding="utf-8"))["runs"]}


class DeadOwnerSweepAndDarwinTokenTests(unittest.TestCase):
    def test_claim_run_on_isolated_path_fails_dead_owner_on_other_isolated_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            ev_dead = project / ".moru" / "runs" / uuid.uuid4().hex / "preflight.json"
            ev_dead.parent.mkdir(parents=True)
            dead_run = agent_run_registry.register_run(
                project, ev_dead, {"command": "bugfix"}, {"request": "crashed agy"}
            )
            reg_path = agent_run_registry.registry_path(project)
            payload = json.loads(reg_path.read_text(encoding="utf-8"))
            payload["runs"][0]["owner"] = {"pid": _dead_pid(), "start_token": ""}
            reg_path.write_text(json.dumps(payload), encoding="utf-8")

            ev_new = project / ".moru" / "runs" / uuid.uuid4().hex / "preflight.json"
            ev_new.parent.mkdir(parents=True)
            claim = agent_run_registry.claim_run(
                project, ev_new, {"command": "bugfix"}, {"request": "next run"}
            )

            self.assertFalse(claim["conflict"])
            self.assertEqual([dead_run["run_id"]], [r["run_id"] for r in claim["recovered"]])
            self.assertEqual("failed", _runs_by_id(project)[dead_run["run_id"]]["state"])

    def test_negative_control_claim_run_spares_live_and_ownerless_runs_on_other_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            ev_live = project / ".moru" / "runs" / uuid.uuid4().hex / "preflight.json"
            ev_ownerless = project / ".moru" / "runs" / uuid.uuid4().hex / "preflight.json"
            ev_live.parent.mkdir(parents=True)
            ev_ownerless.parent.mkdir(parents=True)
            live = agent_run_registry.register_run(project, ev_live, {"command": "bugfix"}, {"request": "live"})
            ownerless = agent_run_registry.register_run(project, ev_ownerless, {"command": "bugfix"}, {"request": "legacy"})
            reg_path = agent_run_registry.registry_path(project)
            payload = json.loads(reg_path.read_text(encoding="utf-8"))
            old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            payload["runs"][0]["owner"] = {"pid": os.getpid(), "start_token": ""}
            payload["runs"][0]["updated_at"] = old
            payload["runs"][1].pop("owner", None)
            payload["runs"][1]["updated_at"] = old
            reg_path.write_text(json.dumps(payload), encoding="utf-8")

            ev_new = project / ".moru" / "runs" / uuid.uuid4().hex / "preflight.json"
            ev_new.parent.mkdir(parents=True)
            claim = agent_run_registry.claim_run(
                project, ev_new, {"command": "bugfix"}, {"request": "next run"}
            )

            self.assertFalse(claim["conflict"])
            self.assertEqual([], claim["recovered"])
            states = _runs_by_id(project)
            self.assertEqual("running", states[live["run_id"]]["state"])
            self.assertEqual("running", states[ownerless["run_id"]]["state"])

    def test_darwin_process_start_token_uses_libproc_birth_and_detects_pid_reuse(self) -> None:
        with (
            patch.object(agent_run_owner.sys, "platform", "darwin"),
            patch.object(agent_run_owner.os, "name", "posix"),
            patch.object(agent_run_owner.Path, "read_text", side_effect=FileNotFoundError),
            patch.object(agent_run_owner, "_pid_exists", return_value=True),
        ):
            with patch.object(
                agent_run_owner, "_darwin_process_info", return_value=(10, "agy-real", "1795482461-524067")
            ):
                token = agent_run_owner._process_start_token(42_000)
                self.assertEqual("1795482461-524067", token)
                self.assertFalse(
                    agent_run_owner.owner_death_is_proven({"pid": 42_000, "start_token": token})
                )
            with patch.object(
                agent_run_owner, "_darwin_process_info", return_value=(10, "other", "1795489999-111111")
            ):
                self.assertTrue(
                    agent_run_owner.owner_death_is_proven({"pid": 42_000, "start_token": token})
                )


class AgyStopRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve() / "project"
        _FIXTURE.copy_to(self.project)

    def test_agy_stop_passes_antigravity_runtime_and_pauses_active_v2_agy_run(self) -> None:
        agy_sid = "agy-stop-session-01"
        env = {
            **os.environ,
            "ANTIGRAVITY_CONVERSATION_ID": agy_sid,
            "ANTIGRAVITY_AGENT": "1",
        }
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.pop("CODEX_THREAD_ID", None)
        started = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "agent-hook.py"),
                "start",
                "--project",
                str(self.project),
                "--rules",
                str(ROOT),
                "--command",
                "bugfix",
                "--request",
                "Fix src/module.py guard",
                "--intent",
                "debugging",
                "--target-summary",
                "src/module.py",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        agy_run = run_id(started)
        self.assertEqual("running", _runs_by_id(self.project)[agy_run]["state"])

        # Negative control: a Claude run in the same repo must not be touched by AGY stop.
        claude_start = start(self.project, ROOT, "Other Claude task", session="claude-peer-session")
        self.assertEqual(0, claude_start.returncode, claude_start.stdout + claude_start.stderr)
        claude_run = run_id(claude_start)

        with (
            tempfile.TemporaryDirectory() as marker_dir,
            patch.object(adapter, "verify_in_session", return_value=(False, {})),
            patch.object(adapter, "unverified_reminder", return_value={}),
            patch("agy_hook_state.MARKER_DIR", Path(marker_dir)),
        ):
            payload = {
                "conversationId": agy_sid,
                "workspacePaths": [str(self.project)],
                "executionNum": 1,
            }
            verdict = adapter.stop(payload)

        self.assertEqual({}, verdict)
        states = _runs_by_id(self.project)
        self.assertEqual("interrupted", states[agy_run]["state"])
        self.assertEqual("running", states[claude_run]["state"])


class FailedRunSupersessionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve() / "project"
        _FIXTURE.copy_to(self.project)

    def _agy_env(self, session: str) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.pop("CODEX_THREAD_ID", None)
        env["ANTIGRAVITY_CONVERSATION_ID"] = session
        env["ANTIGRAVITY_AGENT"] = "1"
        return env

    def _agy_hook(self, *arguments: str, session: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "agent-hook.py"),
                *arguments,
                "--project",
                str(self.project),
                "--rules",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            env=self._agy_env(session),
            timeout=30,
        )

    def _agy_start(self, request: str, *extra: str, session: str) -> subprocess.CompletedProcess:
        return self._agy_hook(
            "start",
            "--command",
            "bugfix",
            "--request",
            request,
            "--intent",
            "debugging",
            "--target-summary",
            "src/module.py",
            *extra,
            session=session,
        )

    def _start_and_fail_dirty_run(
        self, session: str = "agy-fail-session", *, record_failed_tests: bool = False
    ) -> str:
        res = self._agy_start("Fix src/module.py guard", session=session)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        rid = run_id(res)
        (self.project / "src" / "module.py").write_text("value = 2\n", encoding="utf-8")
        if record_failed_tests:
            failed_tests = {
                "gate": "tests",
                "status": "FAIL",
                "fields": {"check": "pytest -q", "result": "1 failed, exit 1"},
            }
            gb = self._agy_hook("gate-batch", "--gate-record", json.dumps([failed_tests]), session=session)
            self.assertEqual(0, gb.returncode, gb.stdout + gb.stderr)
        work = self.project / ".moru" / "work.json"
        work.write_text(
            json.dumps({"objective": "Fix guard in src/module.py", "remaining_work": []}),
            encoding="utf-8",
        )
        cp = self._agy_hook(
            "checkpoint",
            "--checkpoint-kind",
            "decision",
            "--phase",
            "verifying",
            "--work-file",
            str(work),
            session=session,
        )
        self.assertEqual(0, cp.returncode, cp.stdout + cp.stderr)
        fin = self._agy_hook("finish", session=session)
        self.assertEqual(1, fin.returncode, fin.stdout + fin.stderr)
        self.assertEqual("failed", _runs_by_id(self.project)[rid]["state"])
        return rid

    def test_unlinked_start_refuses_to_supersede_dirty_failed_run_in_same_checkout(self) -> None:
        failed_id = self._start_and_fail_dirty_run()

        fresh = self._agy_start("Fix src/module.py guard", session="agy-fail-session")

        self.assertNotEqual(0, fresh.returncode, fresh.stdout + fresh.stderr)
        self.assertIn(failed_id, fresh.stdout)
        self.assertIn("--continue-from", fresh.stdout)
        self.assertEqual("failed", _runs_by_id(self.project)[failed_id]["state"])

    def test_same_run_recovery_after_failed_finish_succeeds(self) -> None:
        session = "agy-fail-session"
        failed_id = self._start_and_fail_dirty_run(session=session)
        retro = {
            "gate": "retrospective check",
            "status": "SUCCESS",
            "fields": {
                "skills_checked": "agent_operating_skill",
                "outcome": "no_reusable_gap",
                "observation": "not_needed",
                "memory_decision": "not_needed",
                "memory_reason": "Temporary test fixture has no durable project lesson.",
                "alignment_evidence": "Requested fix in src/module.py matched final diff and test check.",
                "causal_assessment": "First finish failed because tests and review were missing; recording them closed the run cleanly.",
                "learning_decision": "Keep existing gate checks in agent-finish-check.py; no reusable gap.",
                "efficiency": "no_waste",
                "efficiency_evidence": "Recovered in-place without starting a duplicate run.",
            },
        }
        gb = self._agy_hook(
            "gate-batch",
            "--gate-record",
            json.dumps([TESTS_GATE, retro]),
            session=session,
        )
        self.assertEqual(0, gb.returncode, gb.stdout + gb.stderr)
        rev = self._agy_hook(
            "review",
            "--review-outcome",
            "pass",
            "--code-review-evidence",
            "Reviewed src/module.py change against request and rules.",
            "--docs-freshness-evidence",
            "No docs affected; README.md inspected and still accurate.",
            session=session,
        )
        self.assertEqual(0, rev.returncode, rev.stdout + rev.stderr)
        fin = self._agy_hook("finish", session=session)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertEqual("completed", _runs_by_id(self.project)[failed_id]["state"])

    def test_continue_from_failed_run_preserves_failure_and_does_not_carry_failed_gates(self) -> None:
        session = "agy-fail-session"
        failed_id = self._start_and_fail_dirty_run(session=session, record_failed_tests=True)

        retry = self._agy_start(
            "Fix src/module.py guard",
            "--continue-from",
            failed_id,
            "--reuse-inputs",
            "Retry after diagnosing failure",
            session=session,
        )
        self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
        retry_id = run_id(retry)
        self.assertNotEqual(failed_id, retry_id)
        self.assertIn(f"work id: {failed_id}", retry.stdout)
        self.assertIn(f"continued action: {failed_id}", retry.stdout)
        self.assertEqual("failed", _runs_by_id(self.project)[failed_id]["state"])
        retry_preflight = json.loads(
            (self.project / ".moru" / "runs" / retry_id / "preflight.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failed_id, retry_preflight["work"]["previous_action"])
        self.assertIn("Local gate not carried: tests", retry.stdout)

    def test_clean_same_checkout_still_allows_new_request_after_failed_run(self) -> None:
        session = "agy-clean-session"
        res = self._agy_start("Fix src/module.py guard", session=session)
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        failed_id = run_id(res)
        work = self.project / ".moru" / "work.json"
        work.write_text(json.dumps({"objective": "Test clean failure", "remaining_work": []}), encoding="utf-8")
        self.assertEqual(
            0,
            self._agy_hook(
                "checkpoint",
                "--checkpoint-kind",
                "decision",
                "--phase",
                "verifying",
                "--work-file",
                str(work),
                session=session,
            ).returncode,
        )
        self.assertEqual(1, self._agy_hook("finish", session=session).returncode)
        self.assertEqual("failed", _runs_by_id(self.project)[failed_id]["state"])

        fresh = self._agy_start("Update README.md wording", session=session)
        self.assertEqual(0, fresh.returncode, fresh.stdout + fresh.stderr)
        self.assertEqual("cancelled", _runs_by_id(self.project)[failed_id]["state"])


class AgyBinaryReadGuardAndGuidanceTests(unittest.TestCase):
    def _read_call(self, workspace: Path, path: Path) -> dict:
        return {
            "conversationId": "c-bin",
            "workspacePaths": [str(workspace)],
            "toolCall": {"name": "read_file", "args": {"Path": str(path)}},
        }

    def test_pre_tool_denies_binary_assets_and_empty_or_corrupt_media_but_allows_valid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            glb = ws / "cruiser.glb"
            glb.write_bytes(b"glTF\x02\x00\x00\x00")
            pyc = ws / "mod.pyc"
            pyc.write_bytes(b"\x00\x01\x02\x03")
            empty_png = ws / "empty.png"
            empty_png.write_bytes(b"")
            corrupt_jpg = ws / "corrupt.jpg"
            corrupt_jpg.write_bytes(b"not a jpeg header")
            valid_png = ws / "valid.png"
            valid_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            valid_jpg = ws / "valid.jpg"
            valid_jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
            text_md = ws / "NOTES.md"
            text_md.write_text("# Notes\n", encoding="utf-8")

            with patch.dict(os.environ, {"MORU_AGY_GATE": ""}):
                for bad in (glb, pyc, empty_png, corrupt_jpg):
                    with self.subTest(bad=bad.name):
                        verdict = adapter.pre_tool(self._read_call(ws, bad))
                        self.assertEqual("deny", verdict["decision"], verdict)
                        self.assertIn("read_file", verdict["reason"])
                for good in (valid_png, valid_jpg, text_md):
                    with self.subTest(good=good.name):
                        verdict = adapter.pre_tool(self._read_call(ws, good))
                        self.assertEqual("allow", verdict["decision"], verdict)

    def test_agy_binary_read_rule_lives_in_docs_and_the_hook_not_the_bridge(self) -> None:
        # The PreToolUse guard enforces the rule; the always-loaded bridge stays within its budget.
        agy_block = runtime_bridge.runtime_bridge_block(ROOT, "Antigravity", "AGENTS.md")
        docs = (ROOT / "docs/skills/agent-runtime-integration/references/current-guidance.md").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(".glb", agy_block)
        self.assertIn("read_file", docs)
        self.assertIn(".glb", docs)
        self.assertIn("agy_hook_adapter.py", docs)

if __name__ == "__main__":
    unittest.main()
