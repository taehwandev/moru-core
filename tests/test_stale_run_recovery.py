"""Parallel Claude calls and foreign checkout edits must not strand a run."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_continuation_mutation_state import MutationCheckpointState
from agent_continuation_packet import ContinuationPacketError
from agent_execution_capsule_state import PREFLIGHT_SNAPSHOT_SCHEMA_VERSION
from agent_route_state import request_fingerprint, route_fingerprint
from agent_transfer_cancel import cancel_no_change_run
from claude_continuation_hook import ClaudeContinuationAdapter
from test_agent_runtime_session import RuntimeFixture
from test_agent_transfer_cancel import TransferFixture
from test_claude_continuation_hook import _payload


class ParallelMutationRecoveryTests(unittest.TestCase):
    def pre(self, fixture, payload):
        return ClaudeContinuationAdapter.pre_mutation(
            payload, root=fixture.project, cwd=fixture.project, session_id="old-session"
        )

    def test_parallel_pre_before_either_write_keeps_both_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            second = {**first, "tool_use_id": "toolu_second"}
            self.assertIsNone(self.pre(fixture, first))
            self.assertIsNone(self.pre(fixture, second))
            ClaudeContinuationAdapter.post_mutation(first)
            self.assertIsNotNone(fixture.packet()["checkpoint"]["mutation_pending"])
            # Retried and unrelated post hooks cannot close the second call.
            ClaudeContinuationAdapter.post_mutation(first)
            ClaudeContinuationAdapter.post_mutation({**first, "tool_use_id": "toolu_foreign"})
            ClaudeContinuationAdapter.post_mutation({**second, "tool_name": "Bash"})
            self.assertIsNotNone(fixture.packet()["checkpoint"]["mutation_pending"])
            (fixture.project / "src/module.py").write_text("value = 2\n")
            ClaudeContinuationAdapter.post_mutation(second)
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])
            self.assertEqual([{"path": "src/module.py", "role": "modified"}],
                             fixture.packet()["work"]["changed_scope"])

    def test_different_paths_and_failed_sibling_close_in_reverse_order(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            second = {**first, "tool_use_id": "toolu_second",
                      "tool_input": {"file_path": str(fixture.project / "src/other.py")}}
            self.assertIsNone(self.pre(fixture, first))
            self.assertIsNone(self.pre(fixture, second))
            (fixture.project / "src/module.py").write_text("value = 2\n")
            ClaudeContinuationAdapter.run({**second, "hook_event_name": "PostToolUseFailure"})
            self.assertIsNotNone(fixture.packet()["checkpoint"]["mutation_pending"])
            ClaudeContinuationAdapter.run({**first, "hook_event_name": "PostToolUse"})
            self.assertEqual([{"path": "src/module.py", "role": "modified"}],
                             fixture.packet()["work"]["changed_scope"])
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])
            self.assertFalse(MutationCheckpointState.path(fixture.project, fixture.run_id).exists())

    def test_sidecar_write_failure_never_publishes_a_pending_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            with patch("agent_continuation_checkpoint.atomic_write_json", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    write_continuation_checkpoint(project=fixture.project, rules=fixture.rules,
                        run_id=fixture.run_id, binding_path=fixture.evidence, kind="pre_mutation",
                        mutation={"kind": "update", "paths": ["src/module.py"]})
                self.assertIsNotNone(self.pre(fixture, _payload(fixture, event="PreToolUse")),
                                     "a bound tool must not run without its durable pre checkpoint")
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])

    def test_semantic_checkpoint_between_parallel_hooks_keeps_baseline_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            self.assertIsNone(self.pre(fixture, first))
            write_continuation_checkpoint(project=fixture.project, rules=fixture.rules,
                run_id=fixture.run_id, binding_path=fixture.evidence, kind="decision")
            (fixture.project / "src/module.py").write_text("value = 2\n")
            ClaudeContinuationAdapter.post_mutation(first)
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])

    def test_simultaneous_pre_hooks_do_not_lose_a_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            calls = [{**first, "tool_use_id": f"toolu_{n}"} for n in range(4)]
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = [executor.submit(self.pre, fixture, call) for call in calls]
                self.assertEqual([None] * 4, [result.result(timeout=20) for result in results])
            for call in calls[:-1]:
                ClaudeContinuationAdapter.post_mutation(call)
                self.assertIsNotNone(fixture.packet()["checkpoint"]["mutation_pending"])
            ClaudeContinuationAdapter.post_mutation(calls[-1])
            self.assertIsNone(fixture.packet()["checkpoint"]["mutation_pending"])

    def test_long_running_identified_sibling_is_not_expired_by_the_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            self.assertIsNone(self.pre(fixture, first))
            (fixture.project / "src/module.py").write_text("value = 2\n")
            with patch("agent_continuation_checkpoint.PARALLEL_MUTATION_WINDOW_SECONDS", -1):
                self.assertIsNone(self.pre(fixture, {**first, "tool_use_id": "toolu_later"}))

    def test_missing_sidecar_reconciles_only_with_exact_session_and_observed_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            self.assertIsNone(self.pre(fixture, first))
            (fixture.project / "src/module.py").write_text("value = 2\n")
            MutationCheckpointState.path(fixture.project, fixture.run_id).unlink()
            arguments = dict(project=fixture.project, rules=fixture.rules,
                             run_id=fixture.run_id, binding_path=fixture.evidence,
                             kind="reconcile", phase="acting",
                             work={"objective": "reconcile observed edit", "verification": [],
                                   "changed_scope": [{"path": "src/module.py", "role": "modified"}]})
            with patch("agent_continuation_checkpoint.runtime_session",
                       return_value={"runtime": "claude", "session_id": "foreign"}):
                with self.assertRaises(ValueError):
                    write_continuation_checkpoint(**arguments)
            with patch("agent_continuation_checkpoint.runtime_session",
                       return_value=fixture.preflight["runtime_session"]):
                with self.assertRaises(ValueError):
                    write_continuation_checkpoint(**{**arguments, "work": {
                        "objective": "missing scope", "verification": []}})
                packet = write_continuation_checkpoint(**arguments)
            self.assertIsNone(packet["checkpoint"]["mutation_pending"])
            self.assertEqual([], packet["work"]["verification"])
            self.assertIsNone(self.pre(fixture, {**first, "tool_use_id": "toolu_recovered"}))

    def test_parallel_scope_still_refuses_an_undeclared_write(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(directory)
            first = _payload(fixture, event="PreToolUse")
            self.assertIsNone(self.pre(fixture, first))
            (fixture.project / "foreign.py").write_text("unowned\n")
            with self.assertRaises(ContinuationPacketError):
                write_continuation_checkpoint(project=fixture.project, rules=fixture.rules,
                    run_id=fixture.run_id, kind="post_mutation", binding_path=fixture.evidence,
                    mutation={"tool_use_id": first["tool_use_id"]})
            self.assertIsNotNone(fixture.packet()["checkpoint"]["mutation_pending"])


def initialize_source(fixture):
    binding = json.loads(fixture.source_evidence.read_text())
    binding["execution_snapshot"] = {
        "schema_version": PREFLIGHT_SNAPSHOT_SCHEMA_VERSION,
        "route_fingerprint": route_fingerprint(binding["route"]),
        "request_fingerprint": request_fingerprint(binding["request_intake"]),
        "required_docs": [],
    }
    fixture.source_evidence.write_text(json.dumps(binding))
    return write_continuation_checkpoint(project=fixture.source, rules=fixture.rules,
        run_id=fixture.source_run_id, kind="initial", binding_path=fixture.source_evidence,
        work={"objective": "verify local main already up to date"})


def cancel_source(fixture):
    args = Namespace(project=fixture.source, rules=fixture.rules, evidence=fixture.source_evidence,
                     output=None, repair_cycle=0)
    output = io.StringIO()
    with redirect_stdout(output):
        code = cancel_no_change_run(args)
    return code, output.getvalue()


class NoMutationCancellationTests(unittest.TestCase):
    def test_foreign_tracked_and_untracked_changes_do_not_prevent_cancellation(self):
        with TransferFixture(True, "same request") as fixture:
            initialize_source(fixture)
            (fixture.source / "tracked.txt").write_text("another session\n")
            (fixture.source / "foreign.txt").write_text("keep me\n")
            with patch("agent_transfer_cancel.no_mutation_evidence", return_value=None):
                before, refusal = cancel_source(fixture)
            self.assertEqual(1, before, refusal)
            self.assertIn("stopped being clean", refusal)
            code, output = cancel_source(fixture)
            self.assertEqual(0, code, output)
            self.assertEqual("another session\n", (fixture.source / "tracked.txt").read_text())
            self.assertTrue((fixture.source / "foreign.txt").exists())

    def test_a_noop_mutation_cannot_be_laundered_into_no_mutation(self):
        with TransferFixture(True, "same request") as fixture:
            initialize_source(fixture)
            common = dict(project=fixture.source, rules=fixture.rules,
                          run_id=fixture.source_run_id, binding_path=fixture.source_evidence)
            write_continuation_checkpoint(**common, kind="pre_mutation",
                mutation={"kind": "update", "paths": ["tracked.txt"]})
            write_continuation_checkpoint(**common, kind="post_mutation")
            write_continuation_checkpoint(**common, kind="decision")
            (fixture.source / "foreign.txt").write_text("another session\n")
            code, output = cancel_source(fixture)
            self.assertEqual(1, code, output)

    def test_a_commit_without_file_mutations_is_not_no_change(self):
        with TransferFixture(True, "same request") as fixture:
            initialize_source(fixture)
            fixture.git("commit", "--allow-empty", "-m", "own commit", cwd=fixture.source)
            code, output = cancel_source(fixture)
            self.assertEqual(1, code, output)

    def test_a_pending_mutation_is_not_proof_of_no_change(self):
        with TransferFixture(True, "same request") as fixture:
            initialize_source(fixture)
            write_continuation_checkpoint(project=fixture.source, rules=fixture.rules,
                run_id=fixture.source_run_id, kind="pre_mutation", binding_path=fixture.source_evidence,
                mutation={"kind": "update", "paths": ["tracked.txt"]})
            code, output = cancel_source(fixture)
            self.assertEqual(1, code, output)

    def test_a_mutation_arriving_during_cancellation_is_rechecked_under_lock(self):
        import agent_transfer_cancel
        with TransferFixture(True, "same request") as fixture:
            initialize_source(fixture)
            original = agent_transfer_cancel.cancel_run

            def raced(*args, **kwargs):
                write_continuation_checkpoint(project=fixture.source, rules=fixture.rules,
                    run_id=fixture.source_run_id, kind="pre_mutation", binding_path=fixture.source_evidence,
                    mutation={"kind": "update", "paths": ["tracked.txt"]})
                return original(*args, **kwargs)

            with patch.object(agent_transfer_cancel, "cancel_run", side_effect=raced):
                code, output = cancel_source(fixture)
            self.assertEqual(1, code, output)
            self.assertIn("after validation", output)
