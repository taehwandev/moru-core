"""Canonical lookup must preserve the recursive resolver's acceptance boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_runtime_session as runtime
from agent_run_registry import evidence_binding_key, register_run, registry_path


class RegisteredEvidenceLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.env = patch.dict(os.environ, {"HOME": str(self.root),
                              "MORU_STATE_HOME": str(self.root / "state")}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.session = {"runtime": "claude", "session_id": "synthetic"}

    def add_run(self, relative, session=None):
        path = self.project / ".moru" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        run = register_run(self.project, path, {"command": "task"}, {"request": "fixture"})
        path.write_text(json.dumps({"runtime_session": session or self.session}))
        return path, run

    def update_records(self, change):
        path = registry_path(self.project)
        data = json.loads(path.read_text())
        for record in data["runs"]:
            change(record)
        path.write_text(json.dumps(data))

    def test_all_canonical_claims_resolve_without_recursive_enumeration(self):
        active, _ = self.add_run("runs/" + "a" * 32 + "/preflight.json")
        self.add_run("runs/" + "b" * 32 + "/preflight.json",
                     {"runtime": "codex", "session_id": "peer"})
        with patch.object(runtime.os, "walk", side_effect=AssertionError("recursive walk")):
            self.assertEqual(active, runtime.resolve_runtime_evidence(self.project, self.session))

    def test_custom_claim_and_canonical_decoy_use_legacy_discovery(self):
        self.add_run("runs/" + "a" * 32 + "/preflight.json",
                     {"runtime": "codex", "session_id": "peer"})
        custom, run = self.add_run("custom/preflight.json")
        decoy = self.project / ".moru/runs" / run["run_id"] / custom.name
        decoy.parent.mkdir(parents=True)
        decoy.write_bytes(custom.read_bytes())
        with patch.object(runtime, "_runtime_evidence_candidates",
                          wraps=runtime._runtime_evidence_candidates) as scan:
            self.assertEqual(custom, runtime.resolve_runtime_evidence(self.project, self.session))
        scan.assert_called_once()

    def test_pruned_or_symlinked_canonical_paths_stay_excluded(self):
        for kind in ("nested_run", "nested_runs", "file_symlink", "runs_symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp).resolve()
                path = project / ".moru/runs" / ("a" * 32) / "preflight.json"
                path.parent.mkdir(parents=True)
                register_run(project, path, {"command": "task"}, {"request": "fixture"})
                path.write_text(json.dumps({"runtime_session": self.session}))
                if kind.startswith("nested"):
                    parent = path.parent if kind == "nested_run" else path.parent.parent
                    (parent / ".git").touch()
                elif kind == "file_symlink":
                    target = path.with_name("other.json")
                    path.rename(target)
                    path.symlink_to(target)
                    registry = registry_path(project)
                    data = json.loads(registry.read_text())
                    data["runs"][0]["evidence_key"] = evidence_binding_key(project, path)
                    registry.write_text(json.dumps(data))
                else:
                    runs = path.parent.parent
                    target = project / "external-runs"
                    runs.rename(target)
                    runs.symlink_to(target, target_is_directory=True)
                self.assertIsNone(runtime.resolve_runtime_evidence(project, self.session))

    def test_execute_only_run_directory_keeps_incomplete_scan_denial(self):
        active, _ = self.add_run("runs/" + "a" * 32 + "/preflight.json")
        os.chmod(active.parent, 0o111)
        try:
            try:
                os.listdir(active.parent)
            except PermissionError:
                pass
            else:
                self.skipTest("filesystem permits listing an execute-only directory")
            self.assertTrue(active.is_file())
            self.assertIsNone(runtime.resolve_runtime_evidence(self.project, self.session))
        finally:
            os.chmod(active.parent, 0o755)

    def test_unaccounted_or_invalid_claim_falls_back(self):
        active, _ = self.add_run("runs/" + "a" * 32 + "/preflight.json")
        self.update_records(lambda r: r.update(run_id="not-an-opaque-id"))
        with patch.object(runtime, "_runtime_evidence_candidates",
                          wraps=runtime._runtime_evidence_candidates) as scan:
            self.assertEqual(active, runtime.resolve_runtime_evidence(self.project, self.session))
        scan.assert_called_once()

    def test_direct_lookup_preserves_generation_and_missing_file_denials(self):
        active, _ = self.add_run("runs/" + "a" * 32 + "/preflight.json")
        self.update_records(lambda r: r.update(resume_generation=1))
        self.assertIsNone(runtime.resolve_runtime_evidence(self.project, self.session))
        active.unlink()
        self.assertIsNone(runtime.resolve_runtime_evidence(self.project, self.session))

    def test_settled_timestamp_ties_keep_recursive_path_order(self):
        paths = [self.add_run("runs/" + token * 32 + "/preflight.json")[0]
                 for token in ("b", "a")]
        self.update_records(lambda r: r.update(state="completed"))
        for path in paths:
            os.utime(path, (1700000000, 1700000000))
        self.assertEqual(paths[1], runtime.resolve_runtime_evidence(
            self.project, self.session, frozenset({"completed"}), latest_of_several=True))

    def test_worker_claim_retains_parent_fallback_and_worker_isolation(self):
        parent, _ = self.add_run("runs/" + "a" * 32 + "/preflight.json")
        worker, _ = self.add_run("workers/0123456789abcdef/preflight.json")
        with patch.object(runtime, "_runtime_evidence_candidates",
                          wraps=runtime._runtime_evidence_candidates) as scan:
            self.assertEqual(parent, runtime.resolve_runtime_evidence(self.project, self.session))
        scan.assert_called_once()
        with patch.dict(os.environ, {"MORU_WORKER_EVIDENCE": str(worker)}):
            self.assertEqual(worker, runtime.resolve_runtime_evidence(self.project, self.session))


if __name__ == "__main__":
    unittest.main()
