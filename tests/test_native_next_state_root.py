"""Root aliases retain canonical keys and never grant worker scope."""
import hashlib
import json
import unittest

from native_pretool_support import result
import test_native_next_session as session_tests


class NativeNextStateRootTests(unittest.TestCase):
    setUp = session_tests.NativeNextSessionTests.setUp
    call = session_tests.NativeNextSessionTests.call

    def key(self, path):
        canonical = path.resolve()
        try:
            text = canonical.relative_to(self.project).as_posix()
        except ValueError:
            text = str(canonical)
        return hashlib.sha256(text.encode()).hexdigest()

    def alias(self, target, relative=False):
        state = self.project / ".moru"
        state.rename(target)
        state.symlink_to(target.name if relative else target, target_is_directory=True)
        self.evidence = target / "runs" / ("a" * 32) / "preflight.json"
        self.registry = target / "run-registry.json"
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["evidence_key"] = self.key(self.evidence)
        self.registry.write_text(json.dumps(registry))
        with (self.project / ".git/info/exclude").open("a") as stream:
            stream.write("\n.moru\n")
        return target

    def parity(self, active):
        state = (self.project / ".moru").resolve()
        before = {p: p.read_bytes() for p in state.rglob("*") if p.is_file()}
        session_tests.NativeNextSessionTests.parity(self, active)
        self.assertEqual(before, {p: p.read_bytes() for p in state.rglob("*") if p.is_file()})

    def selected(self, path):
        self.parity(True)
        self.assertEqual(str(path.resolve()), json.loads(self.call(no_python=True).stdout)["evidence"])

    def test_external_state_root_uses_absolute_canonical_key(self):
        self.alias(self.base / "external-state 한글")
        self.selected(self.evidence)

    def test_internal_state_root_uses_project_relative_canonical_key(self):
        self.alias(self.project / "physical-state", relative=True)
        self.selected(self.evidence)

    def test_lexical_key_cannot_claim_the_resolved_evidence(self):
        self.alias(self.base / "external-state")
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["evidence_key"] = hashlib.sha256(
            (".moru/runs/" + "a" * 32 + "/preflight.json").encode()).hexdigest()
        self.registry.write_text(json.dumps(registry))
        self.parity(False)

    def test_parent_excludes_workers_below_aliased_root(self):
        state = self.alias(self.base / "external-state")
        worker = state / "workers/opaque/preflight.json"
        worker.parent.mkdir(parents=True)
        worker.write_text(self.evidence.read_text())
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({"run_id": "c" * 32, "state": "running",
            "evidence_name": worker.name, "evidence_key": self.key(worker)})
        self.registry.write_text(json.dumps(registry))
        self.selected(self.evidence)
        for hint in (str(worker), str(self.project / ".moru/workers/opaque/preflight.json")):
            self.identity["MORU_WORKER_EVIDENCE"] = hint
            self.parity(False)
        self.identity["MORU_WORKER_EVIDENCE"] = " \t\u2003"
        self.selected(self.evidence)

    def test_legacy_default_key_resolves_through_root_alias(self):
        state = self.alias(self.base / "external-state")
        default = state / "preflight.json"
        default.write_text(self.evidence.read_text())
        registry = json.loads(self.registry.read_text())
        del registry["runs"][0]["evidence_key"]
        self.registry.write_text(json.dumps(registry))
        self.selected(default)

    def test_global_install_marker_files_do_not_change_read_only_selection(self):
        state = self.project / ".moru"
        for name in ("moru-root", "projects.json", "bin/moru-hook"):
            marker = state / name
            marker.parent.mkdir(exist_ok=True)
            marker.write_text("synthetic marker")
            self.selected(self.evidence)
            marker.unlink()
            marker.symlink_to("missing")
            self.selected(self.evidence)
            marker.unlink()

    def test_nested_links_remain_excluded_inside_resolved_state(self):
        state = self.alias(self.base / "external-state")
        self.evidence.parent.joinpath(".git").symlink_to("missing")
        self.parity(False)
        self.evidence.parent.joinpath(".git").unlink()
        target = state / "runs" / ("a" * 32)
        outside = self.base / "saved-run"
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=True)
        registry = json.loads(self.registry.read_text())
        registry["runs"][0]["evidence_key"] = self.key(outside / "preflight.json")
        self.registry.write_text(json.dumps(registry))
        # Following the link would select the bound file outside the scanned state.
        self.parity(False)

    def test_dangling_root_and_legacy_default_leaf_link_keep_reference(self):
        state = self.project / ".moru"
        moved = self.base / "saved-state"
        state.rename(moved)
        state.symlink_to(self.base / "missing-state", target_is_directory=True)
        reference = self.call(backend="python")
        self.assertEqual(result(reference), result(self.call()))
        self.assertEqual(127, self.call(no_python=True).returncode)
        state.unlink()
        state.write_text("not a directory")
        reference = self.call(backend="python")
        self.assertEqual(result(reference), result(self.call()))
        self.assertEqual(127, self.call(no_python=True).returncode)
        state.unlink()
        moved.rename(state)
        state.joinpath("preflight.json").symlink_to(self.evidence)
        reference = self.call(backend="python")
        self.assertEqual(result(reference), result(self.call()))
        self.assertEqual(127, self.call(no_python=True).returncode)


if __name__ == "__main__":
    unittest.main()
