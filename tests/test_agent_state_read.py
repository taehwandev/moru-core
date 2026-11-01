"""Read primitives preserve decoding, path ownership and lightweight imports."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import agent_state_read as subject


class AgentStateReadTests(unittest.TestCase):
    def test_json_edge_cases_preserve_existing_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.assertEqual({}, subject.read_json_object(path))
            for value in ({"runs": []}, [], None, False):
                path.write_text(json.dumps(value))
                self.assertEqual(value if isinstance(value, dict) else {"invalid_json": True},
                                 subject.read_json_object(path))
            path.write_text("{")
            self.assertEqual({"invalid_json": True}, subject.read_json_object(path))
            self.assertEqual({"invalid_json": True}, subject.read_json_object(Path(tmp)))
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                subject.read_json_object(path)

    def test_original_owners_reexport_shared_definitions(self):
        import agent_execution_capsule_state as capsule
        import agent_ipc as ipc
        import agent_run_registry as registry
        import agent_scheduler as scheduler
        for owner, name in ((capsule, "read_json_object"), (ipc, "events_path"),
                            (registry, "registry_path"), (scheduler, "scheduler_path")):
            self.assertIs(getattr(subject, name), getattr(owner, name))

    def test_read_cli_imports_do_not_load_mutation_and_capture_owners(self):
        done = subprocess.run([sys.executable, "-B", "-c",
            "import agent_observability, agent_work_cards, sys; "
            "assert not set(('agent_ipc', 'agent_scheduler', 'agent_run_registry', "
            "'agent_execution_capsule_state', 'agent_project_memory')) & set(sys.modules)"],
            capture_output=True)
        self.assertEqual((0, b"", b""), (done.returncode, done.stdout, done.stderr))
