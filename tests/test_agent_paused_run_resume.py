from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

import agent_paused_run_resume
from agent_paused_run_resume import resume_session_paused_run
from agent_run_registry import registry_path, transition_run
from agent_runtime_session import resolve_runtime_evidence
from test_agent_run_interruption import Run
from test_agent_run_registry import dead_pid

HOOK_SPEC = importlib.util.spec_from_file_location('agent_hook_paused_resume', ROOT / 'scripts' / 'agent-hook.py')
agent_hook = importlib.util.module_from_spec(HOOK_SPEC)
HOOK_SPEC.loader.exec_module(agent_hook)


def _session(identity):
    return patch.multiple(
        'agent_paused_run_resume', runtime_session=lambda: identity,
    ), patch('agent_continuation_claim.runtime_session', return_value=identity)


class ResumeSessionPausedRunTests(unittest.TestCase):
    def _stopped(self, directory):
        run = Run(directory, packet=True)
        run.checkpoint()
        run.stop()
        self.assertEqual('interrupted', run.state())
        return run

    def _resume(self, run, identity, evidence=None):
        own, claim = _session(identity)
        with own, claim, patch('agent_runtime_session.runtime_session', return_value=identity):
            return resume_session_paused_run(run.project, evidence)

    def test_own_paused_run_is_resumed_before_a_ledger_write(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            resumed, note = self._resume(run, run.session)
            self.assertEqual(run.evidence.resolve(), resumed.resolve())
            self.assertIn(run.run['run_id'], note)
            self.assertEqual('running', run.state())

    def test_explicit_evidence_of_the_same_run_is_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            resumed, _ = self._resume(run, run.session, run.evidence)
            self.assertIsNotNone(resumed)
            self.assertEqual('running', run.state())

    def test_another_sessions_paused_run_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            foreign = dict(run.session, session_id='foreign')
            self.assertEqual((None, ''), self._resume(run, foreign))
            self.assertEqual('interrupted', run.state())

    def test_explicit_evidence_of_another_run_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            other = run.project / '.tao' / 'runs' / 'other' / 'preflight.json'
            self.assertEqual((None, ''), self._resume(run, run.session, other))
            self.assertEqual('interrupted', run.state())

    def test_worker_never_resumes_the_parents_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            with patch.dict(os.environ, {'TAO_WORKER_EVIDENCE': str(run.evidence)}):
                self.assertEqual((None, ''), self._resume(run, run.session))
            self.assertEqual('interrupted', run.state())

    def test_refused_claim_is_reported_not_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self._stopped(directory)
            refusal = {'result': 'reconcile_required', 'changed_signals': ['pending_mutation']}
            with patch.object(agent_paused_run_resume, 'resume_own_paused_run', return_value=refusal):
                resumed, note = self._resume(run, run.session)
            self.assertIsNone(resumed)
            self.assertIn('reconcile_required (changed: pending_mutation)', note)


class LedgerHookDispatchTests(unittest.TestCase):
    def _dispatch(self, hook, **extra):
        args = argparse.Namespace(hook=hook, project=Path('/project'), evidence=None, **extra)
        resumed = Path('/project/.tao/runs/abc/preflight.json')
        with patch('agent_paused_run_resume.resume_session_paused_run', return_value=(resumed, 'resumed')) as resume, \
                patch.object(agent_hook, '_checkpointed_hook', return_value=0), \
                patch.object(agent_hook, 'finish_hook', return_value=0):
            agent_hook._dispatch_lifecycle_hook(args)
        return resume, args

    def test_ledger_writing_hooks_resume_first(self):
        for hook in ('gate', 'gate-batch', 'review', 'verify', 'finish'):
            with self.subTest(hook=hook):
                resume, args = self._dispatch(hook)
                resume.assert_called_once()
                self.assertEqual('abc', args.evidence.parent.name)

    def test_gate_template_and_other_hooks_do_not_resume(self):
        resume, _ = self._dispatch('gate-batch', gate_template=True)
        resume.assert_not_called()
        with patch.object(agent_hook, 'handoff_hook', return_value=0):
            resume, _ = self._dispatch('handoff')
        resume.assert_not_called()


class CloseoutSessionBindingTests(unittest.TestCase):
    def test_failed_closeout_rebinds_after_dead_owner_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, packet=True)
            run.checkpoint()
            registry = registry_path(run.project)
            state = json.loads(registry.read_text(encoding='utf-8'))
            state['runs'][-1]['state'] = 'failed'
            state['runs'][-1]['owner'] = {'pid': dead_pid(), 'start_token': ''}
            registry.write_text(json.dumps(state), encoding='utf-8')
            args = argparse.Namespace(project=run.project, evidence=run.evidence)

            with patch.object(agent_hook, 'runtime_session', return_value=run.session):
                agent_hook._resume_run_for_closeout(args)

            bound = json.loads(run.evidence.read_text(encoding='utf-8'))['runtime_session']
            current = json.loads(registry.read_text(encoding='utf-8'))['runs'][-1]
            self.assertEqual(1, current['resume_generation'])
            self.assertEqual(1, bound['resume_generation'])
            self.assertEqual('resuming', current['state'])
            self.assertEqual(run.evidence.resolve(), resolve_runtime_evidence(run.project, run.session))
            transition_run(run.project, run.evidence, 'completed', run_id=run.run['run_id'])
            self.assertEqual(
                run.evidence.resolve(),
                resolve_runtime_evidence(
                    run.project, run.session, frozenset({'completed'}), latest_of_several=True
                ),
            )


if __name__ == '__main__':
    unittest.main()
