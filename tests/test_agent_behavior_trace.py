"""Real ACP journal ingress plus an opt-in native/evaluator protocol contract."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agent_behavior_trace import export_review
from agent_behavior_eval import evaluate
import test_agent_review_journal as journal_fixture

NATIVE = os.environ.get('MORU_BEHAVIOR_NATIVE', '')


class BehaviorTraceTests(unittest.TestCase):
    def record(self):
        helper = journal_fixture.ReviewJournalTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        subprocess.run(helper.command('normal'), capture_output=True, check=True, timeout=5)
        return helper.output

    def test_exports_real_events_without_response_or_runtime_details(self):
        record = self.record()
        with patch('agent_behavior_trace.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'{}', b'')) as run:
            export_review(record, provider='agy', case_id='durable_prompt_completion', native_executable=sys.executable)
        payload = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(set(payload), {'schema_version', 'provider', 'case_id', 'events'})
        self.assertEqual(payload['events'][0], {'event_type': 'review.record_initialized'})
        self.assertEqual(payload['events'][-1], {'event_type': 'review.finished', 'status': 'ok'})
        for private in ('response', 'runtime_path', 'runtime_digest', 'session_id', 'request_digest'):
            self.assertNotIn(private, run.call_args.kwargs['input'].decode())

    def test_rejects_running_or_mismatched_receipt_before_native_execution(self):
        record = self.record()
        original = json.loads(record.read_text())
        for field, value in (('phase', 'submitted'), ('status', 'blocked'), ('runtime_digest', '')):
            changed = {**original, field:value}
            record.write_text(json.dumps(changed))
            with patch('agent_behavior_trace.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    export_review(record, provider='agy', case_id='case', native_executable=sys.executable)
                run.assert_not_called()

    def test_content_fields_in_event_are_rejected_instead_of_forwarded(self):
        record = self.record()
        raw = json.loads(record.read_text())
        raw['events'][0]['content'] = 'private data'
        record.write_text(json.dumps(raw))
        with patch('agent_behavior_trace.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'review_event_schema_invalid'):
                export_review(record, provider='agy', case_id='case', native_executable=sys.executable)
            run.assert_not_called()

    def test_native_failure_is_not_replaced_by_python_or_synthetic_trace(self):
        record = self.record()
        with patch('agent_behavior_trace.subprocess.run', return_value=subprocess.CompletedProcess([], 2, b'', b'rejected')) as run:
            with self.assertRaisesRegex(ValueError, 'native_trace_rejected'):
                export_review(record, provider='agy', case_id='case', native_executable=sys.executable)
            self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(NATIVE, 'native test candidate requires explicit compilation approval')
    def test_real_acp_journal_through_rust_and_shared_evaluator(self):
        record = self.record()
        trace = export_review(record, provider='agy', case_id='durable_prompt_completion', native_executable=NATIVE)
        all_cases = json.loads((ROOT / 'tests/fixtures/agent-behavior-cases.json').read_text())
        cases = {'schema_version':1, 'cases':[c for c in all_cases['cases'] if c['id']=='durable_prompt_completion']}
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'agy/durable_prompt_completion/result.txt'
            artifact.parent.mkdir(parents=True)
            artifact.write_text('ready\n')  # Explicit local artifact fixture, no provider score.
            result = evaluate(cases, trace, Path(tmp), providers=('agy',))
        self.assertTrue(result['passed'], result)
        # Deliberate corruption of an observed record must fail the grader.
        raw = json.loads(record.read_text())
        raw['events'].insert(2, {'event_type':'review.prompt_submitted'})
        record.write_text(json.dumps(raw))
        trace = export_review(record, provider='agy', case_id='durable_prompt_completion', native_executable=NATIVE)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'agy/durable_prompt_completion/result.txt'
            artifact.parent.mkdir(parents=True)
            artifact.write_text('ready\n')
            result = evaluate(cases, trace, Path(tmp), providers=('agy',))
        self.assertFalse(result['passed'], result)


if __name__ == '__main__':
    unittest.main()
