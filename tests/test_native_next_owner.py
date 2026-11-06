"""Ambiguous session selection needs one exact current process owner."""
import json
import unittest

from agent_run_owner import process_owner
import test_native_next_session as session_tests


class NativeNextOwnerTests(unittest.TestCase):
    setUp = session_tests.NativeNextSessionTests.setUp
    call = session_tests.NativeNextSessionTests.call
    parity = session_tests.NativeNextSessionTests.parity
    add_run = session_tests.NativeNextSessionTests.add_run

    def owner(self):
        owner = process_owner()
        self.assertGreater(owner.get("pid", 0), 0, "fixture must resolve the real POSIX owner")
        return owner

    def owners(self, *owners):
        registry = json.loads(self.registry.read_text())
        self.assertEqual(len(registry["runs"]), len(owners))
        for run, owner in zip(registry["runs"], owners):
            run["owner"] = owner
        self.registry.write_text(json.dumps(registry))

    def selected(self, path):
        self.parity(True)
        self.assertEqual(str(path), json.loads(self.call(no_python=True).stdout)["evidence"])

    def test_exact_current_owner_selects_older_or_newer_peer(self):
        peer = self.add_run("c" * 32, session="synthetic-next")
        owner = self.owner()
        self.owners(owner, {})
        self.selected(self.evidence)
        self.owners({}, owner)
        self.selected(peer)

    def test_wrong_pid_start_token_and_extra_keys_never_match(self):
        self.add_run("c" * 32, session="synthetic-next")
        owner = self.owner()
        for wrong in ({**owner, "pid": owner["pid"] + 1},
                      {**owner, "start_token": owner["start_token"] + "wrong"},
                      {**owner, "extra": True}):
            with self.subTest(owner=wrong):
                self.owners(wrong, {})
                self.parity(False)

    def test_duplicate_current_owner_stays_ambiguous(self):
        self.add_run("c" * 32, session="synthetic-next")
        owner = self.owner()
        self.owners(owner, owner)
        self.parity(False)

    def test_malformed_or_missing_owner_is_not_a_claim(self):
        self.add_run("c" * 32, session="synthetic-next")
        for value in (None, [], 1, "owner", {"pid": self.owner()["pid"]}):
            self.owners(value, {})
            self.parity(False)

    def test_foreign_session_owner_does_not_compete(self):
        self.add_run("c" * 32, session="foreign")
        self.owners({}, self.owner())
        self.selected(self.evidence)

    def test_numeric_pid_equality_and_exact_token_type(self):
        self.add_run("c" * 32, session="synthetic-next")
        owner = self.owner()
        self.owners({**owner, "pid": float(owner["pid"])}, {})
        self.selected(self.evidence)
        self.owners({**owner, "pid": str(owner["pid"])}, {})
        self.parity(False)
        self.owners({**owner, "start_token": None}, {})
        self.parity(False)

    def test_terminal_record_suppresses_owned_active_peer(self):
        peer = self.add_run("c" * 32, session="synthetic-next")
        self.owners(self.owner(), {})
        registry = json.loads(self.registry.read_text())
        registry["runs"].append({**registry["runs"][0], "state": "completed"})
        self.registry.write_text(json.dumps(registry))
        self.selected(peer)


if __name__ == "__main__":
    unittest.main()
