"""Custom evidence discovery must preserve exact binding and worker scope."""
import hashlib
import json
import os
import unittest

from agent_run_owner import process_owner
from native_pretool_support import result
import test_native_next_session as session_tests


class NativeNextDiscoveryTests(unittest.TestCase):
    setUp = session_tests.NativeNextSessionTests.setUp
    call = session_tests.NativeNextSessionTests.call
    parity = session_tests.NativeNextSessionTests.parity

    def bind(self, path, *, session="synthetic-next", run_id="d" * 32):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self.preflight, "agent_run_id": run_id,
                   "runtime_session": {"runtime": "codex", "session_id": session}}
        path.write_text(json.dumps(payload))
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({"run_id": run_id, "state": "running", "evidence_name": path.name,
            "evidence_key": hashlib.sha256(path.relative_to(self.project).as_posix().encode()).hexdigest()})
        self.registry.write_text(json.dumps(registry))
        return path

    def remove_original(self):
        self.evidence.unlink()
        registry = json.loads(self.registry.read_text())
        registry["runs"] = registry["runs"][1:]
        self.registry.write_text(json.dumps(registry))

    def selected(self, path):
        self.parity(True)
        self.assertEqual(str(path.resolve()), json.loads(self.call(no_python=True).stdout)["evidence"])

    def test_custom_basename_at_state_root_or_nested_location(self):
        self.remove_original()
        path = self.bind(self.project / ".moru/preflight-한글.json")
        self.selected(path)
        path.unlink()
        self.registry.write_text(json.dumps({"schema_version": 1, "runs": []}))
        path = self.bind(self.project / ".moru/custom/deep/preflight-한글.json")
        self.selected(path)

    def test_exact_key_selects_registered_custom_file_among_same_names(self):
        self.remove_original()
        selected = self.bind(self.project / ".moru/custom/preflight.json")
        other = self.project / ".moru/unregistered/preflight.json"
        other.parent.mkdir()
        other.write_text(selected.read_text())
        self.selected(selected)

    def test_custom_ambiguity_uses_exact_process_owner(self):
        custom = self.bind(self.project / ".moru/custom/peer.json")
        self.parity(False)
        owner = process_owner()
        self.assertGreater(owner.get("pid", 0), 0)
        registry = json.loads(self.registry.read_text())
        registry["runs"][-1]["owner"] = owner
        self.registry.write_text(json.dumps(registry))
        self.selected(custom)

    def test_parent_ignores_worker_match_but_accounts_for_its_binding(self):
        self.bind(self.project / ".moru/workers/opaque/preflight.json")
        self.selected(self.evidence)

    def test_worker_hint_selects_only_its_own_record(self):
        worker = self.bind(self.project / ".moru/workers/opaque/preflight.json")
        self.identity["MORU_WORKER_EVIDENCE"] = " \t" + str(worker) + "\u2003"
        self.selected(worker)
        self.identity["MORU_WORKER_EVIDENCE"] = str(worker.relative_to(self.project))
        self.selected(worker)

    def test_blank_worker_hint_preserves_parent_scope(self):
        for hint in ("", " \t\u2003"):
            self.identity["MORU_WORKER_EVIDENCE"] = hint
            self.selected(self.evidence)

    def test_worker_hint_expands_current_home(self):
        worker = self.bind(self.project / ".moru/workers/opaque/preflight.json")
        self.identity.update(HOME=str(self.project), MORU_WORKER_EVIDENCE="~/.moru/workers/opaque/preflight.json")
        self.selected(worker)

    def test_worker_hint_rejects_symlink_file_or_worker_directory(self):
        worker = self.bind(self.project / ".moru/workers/opaque/preflight.json")
        self.identity["MORU_WORKER_EVIDENCE"] = str(worker)
        target = self.project / ".moru/saved.json"
        worker.rename(target)
        worker.symlink_to(target)
        self.parity(False)
        worker.unlink()
        worker.parent.rmdir()
        worker.parent.symlink_to(target.parent, target_is_directory=True)
        self.parity(False)

    def test_invalid_foreign_missing_and_deep_worker_hint_never_choose_parent(self):
        missing = self.project / ".moru/workers/none/preflight.json"
        deep = self.bind(self.project / ".moru/workers/one/deep/preflight.json")
        for hint in (str(self.evidence), str(missing), str(deep), "/foreign/workers/one/preflight.json"):
            with self.subTest(hint=hint):
                self.identity["MORU_WORKER_EVIDENCE"] = hint
                self.parity(False)

    def test_nested_checkout_file_directory_or_dangling_marker_is_pruned(self):
        self.remove_original()
        path = self.bind(self.project / ".moru/custom/preflight.json")
        marker = path.parent / ".git"
        marker.write_text("gitdir: elsewhere")
        self.parity(False)
        marker.unlink()
        marker.mkdir()
        self.parity(False)
        marker.rmdir()
        marker.symlink_to("missing")
        self.parity(False)

    def test_symlink_files_and_directories_are_not_discovered(self):
        self.remove_original()
        path = self.bind(self.project / ".moru/custom/preflight.json")
        outside = self.project / "outside"
        outside.mkdir()
        target = outside / "preflight.json"
        path.rename(target)
        path.symlink_to(target)
        self.parity(False)
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(outside, target_is_directory=True)
        self.parity(False)

    def test_missing_unresolved_binding_does_not_hide_complete_scan_match(self):
        missing = self.bind(self.project / ".moru/custom/absent.json")
        missing.unlink()
        self.selected(self.evidence)

    def test_unreadable_parent_subtree_requires_all_claims_accounted_for(self):
        self.remove_original()
        selected = self.bind(self.project / ".moru/custom/preflight.json")
        denied = self.project / ".moru/unreadable"
        denied.mkdir()
        denied.chmod(0)
        try:
            try:
                with os.scandir(denied):
                    self.skipTest("host can enumerate mode-zero directories")
            except PermissionError:
                pass
            self.selected(selected)
            missing = self.bind(self.project / ".moru/custom/absent.json", run_id="e" * 32)
            missing.unlink()
            self.parity(False)
        finally:
            denied.chmod(0o700)

    def test_unreadable_worker_subtree_does_not_make_parent_scan_incomplete(self):
        worker = self.bind(self.project / ".moru/workers/opaque/preflight.json")
        denied = worker.parent
        denied.chmod(0)
        try:
            try:
                with os.scandir(denied):
                    self.skipTest("host can enumerate mode-zero directories")
            except PermissionError:
                pass
            self.selected(self.evidence)
        finally:
            denied.chmod(0o700)

    def test_readable_nonsearchable_directory_keeps_version_specific_stat_errors(self):
        denied = self.project / ".moru/readable-only"
        path = self.bind(denied / "preflight.json")
        (denied / "unknown-child").mkdir()
        denied.chmod(0o400)
        try:
            with os.scandir(denied) as entries:
                self.assertEqual(2, len(list(entries)))
            try:
                path.stat()
                self.skipTest("host can stat through a nonsearchable directory")
            except PermissionError:
                pass
            reference = self.call(backend="python")
            self.assertEqual(result(reference), result(self.call()))
            self.assertEqual(127, self.call(no_python=True).returncode)
        finally:
            denied.chmod(0o700)

    def test_bound_nonmatching_names_and_unbound_invalid_json_are_ignored(self):
        state = self.project / ".moru"
        (state / "preflight.json").write_text("{invalid")
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({"state": "running", "run_id": "e" * 32,
            "evidence_name": "../preflight.json", "evidence_key": "0" * 64})
        self.registry.write_text(json.dumps(registry))
        self.selected(self.evidence)


if __name__ == "__main__":
    unittest.main()
