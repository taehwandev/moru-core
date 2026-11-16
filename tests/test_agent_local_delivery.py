"""Actual Git content, finish and Stop contracts for local delivery."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_agent_pending_publication as fixtures
import agent_pending_publication as pending
from agent_local_delivery import LocalDeliveryProof as Proof
from agent_run_registry import register_run, transition_run
from agent_route_state import route_fingerprint

git = fixtures.git
ITEMS = [{"checkpoint": "publication.commit", "action": "commit reviewed unit"},
         {"checkpoint": "publication.integrate/main", "action": "integrate locally"}]


class AdmissionTests(unittest.TestCase):
    def test_fresh_route_manifest_selects_the_versioned_contract(self):
        from workflow_route import resolve_docs
        for command in ('task', 'commit', 'analysis'):
            with self.subTest(command=command):
                self.assertEqual(Proof.CONTRACT, resolve_docs(command, None, [])['local_delivery_contract'])

    def test_only_current_writable_routes_with_authority_defer_local_delivery(self):
        for effect, command, expected in (("git_write", "task", True), ("local_write", "task", False),
                ("git_write", "analysis", False), ("git_write", "unknown", False)):
            preflight = fixtures.admitted(effect, command)
            preflight['route']['local_delivery_contract'] = Proof.CONTRACT
            with self.subTest(effect=effect, command=command):
                blocking, deferred = pending.split_remaining(preflight, ITEMS)
                self.assertEqual(ITEMS if expected else [], deferred)
                self.assertEqual([] if expected else ITEMS, blocking)
        preflight = fixtures.admitted("external_write", "task")
        preflight['route']['local_delivery_contract'] = Proof.CONTRACT
        remote = [{"checkpoint": "publication.push"}, {"checkpoint": "publication.pull-request/main"}]
        self.assertEqual((remote, []), pending.split_remaining(preflight, remote))
        preflight['route']['request_classification']['intent_envelope']['authority'] = 'assumed'
        self.assertEqual((ITEMS, []), pending.split_remaining(preflight, ITEMS))

    def test_contract_is_fingerprinted_and_legacy_routes_stay_frozen(self):
        legacy = fixtures.admitted("git_write", "task")
        before = route_fingerprint(legacy['route'])
        self.assertEqual((ITEMS, []), pending.split_remaining(legacy, ITEMS))
        legacy['route']['local_delivery_contract'] = Proof.CONTRACT
        self.assertNotEqual(before, route_fingerprint(legacy['route']))


class LocalFinishTests(fixtures.FinishBase):
    RUNTIME = 'codex'
    REMAINING = ITEMS

    def setUp(self):
        def current(project, evidence, route, intake):
            route['command'] = 'task'
            route['local_delivery_contract'] = Proof.CONTRACT
            route['request_classification']['intent_envelope']['effective_effect'] = 'git_write'
            return register_run(project, evidence, route, intake)
        with patch('test_agent_run_interruption.register_run', side_effect=current):
            super().setUp()

    def prepare(self):
        git(self.project, 'branch', '-M', 'work')
        git(self.project, 'branch', 'main')
        (self.project / 'source.txt').write_text('reviewed staged content\n')
        git(self.project, 'add', 'source.txt')

    def receipt(self):
        return json.loads(self.evidence.with_name('pending-publication.json').read_text())

    def commit(self):
        git(self.project, 'commit', '-qm', 'reviewed')

    def integrate(self):
        git(self.project, 'checkout', '-q', 'main')
        git(self.project, 'merge', '--ff-only', 'work')

    def test_finish_commit_then_integration_are_distinct_observed_outcomes(self):
        code, details = self.finish()
        self.assertEqual(0, code, details)
        self.assertEqual(2, self.receipt()['schema_version'])
        self.assertEqual('block', self.stop()['decision'])
        self.commit()
        self.assertEqual('block', self.stop()['decision'])
        self.assertEqual(['observed', 'pending'], [x['state'] for x in self.receipt()['items']])
        self.integrate()
        self.assertEqual({}, self.stop())
        self.assertEqual(['observed', 'observed'], [x['state'] for x in self.receipt()['items']])

    def test_empty_and_unrelated_commits_are_not_reviewed_content(self):
        self.assertEqual(0, self.finish()[0])
        git(self.project, 'reset', '-q', 'HEAD', 'source.txt')
        git(self.project, 'commit', '--allow-empty', '-qm', 'empty')
        (self.project / 'unrelated.txt').write_text('different\n')
        git(self.project, 'add', 'unrelated.txt')
        git(self.project, 'commit', '-qm', 'unrelated')
        self.assertEqual('block', self.stop()['decision'])
        self.assertEqual(['pending', 'pending'], [x['state'] for x in self.receipt()['items']])

    def test_oldest_reviewed_commit_survives_long_history_and_is_cached(self):
        self.assertEqual(0, self.finish()[0])
        self.commit()
        approved = git(self.project, 'rev-parse', 'HEAD')
        for number in range(65):
            git(self.project, 'commit', '--allow-empty', '-qm', f'later {number}')
        self.assertEqual('block', self.stop()['decision'])
        self.assertEqual(approved, self.receipt()['local_delivery']['reviewed_commit'])
        calls = []
        def reader(project, *args):
            calls.append(args)
            return pending._git(project, *args)
        self.assertTrue(Proof.observe(self.project, self.receipt(), 'publication.integrate/main', reader)[1])
        self.assertFalse(any(args[0] == 'rev-list' for args in calls))

    def test_integrated_content_is_observed_after_source_branch_deletion(self):
        self.assertEqual(0, self.finish()[0])
        self.commit()
        self.integrate()
        git(self.project, 'branch', '-D', 'work')
        self.assertEqual({}, self.stop())

    def test_non_ff_target_history_does_not_hide_the_reviewed_descendant(self):
        git(self.project, 'reset', '-q', 'HEAD', 'source.txt')
        (self.project / 'fork-base.txt').write_text('source base after fork\n')
        git(self.project, 'add', 'fork-base.txt')
        git(self.project, 'commit', '-qm', 'source base')
        git(self.project, 'add', 'source.txt')
        self.assertEqual(0, self.finish()[0])
        self.commit()
        target = Path(self.tmp.name) / 'target'
        git(self.project, 'worktree', 'add', '-q', str(target), 'main')
        import os
        import subprocess
        target_env = {**os.environ, 'GIT_AUTHOR_DATE': '2001-01-01T00:00:00+0000',
                      'GIT_COMMITTER_DATE': '2001-01-01T00:00:00+0000'}
        for number in range(65):
            subprocess.run(['git', '-C', str(target), 'commit', '--allow-empty', '-qm', f'target history {number}'],
                           env=target_env, capture_output=True, check=True)
        git(target, 'merge', '--no-ff', 'work', '-m', 'integrate')
        git(self.project, 'checkout', '--detach', '-q')
        git(self.project, 'branch', '-D', 'work')
        def unfiltered_reader(project, *args):
            return pending._git(project, *(arg for arg in args if arg != '--ancestry-path'))
        self.assertTrue(Proof.observe(self.project, self.receipt(), 'publication.integrate/main', unfiltered_reader)[1])
        self.assertEqual({}, self.stop())

    def test_amended_same_content_replaces_an_unreachable_cached_oid(self):
        self.assertEqual(0, self.finish()[0])
        self.commit()
        self.assertEqual('block', self.stop()['decision'])
        old = self.receipt()['local_delivery']['reviewed_commit']
        git(self.project, 'commit', '--amend', '-qm', 'same reviewed content, new metadata')
        new = git(self.project, 'rev-parse', 'HEAD')
        self.assertNotEqual(old, new)
        self.integrate()
        self.assertEqual({}, self.stop())
        self.assertEqual(new, self.receipt()['local_delivery']['reviewed_commit'])

    def test_repeated_stop_preserves_debt_without_an_unbounded_continuation_loop(self):
        self.assertEqual(0, self.finish()[0])
        repeated = self.stop(stop_hook_active=True)
        if self.RUNTIME == 'codex':
            self.assertIs(False, repeated['continue'])
        else:
            self.assertEqual({}, repeated)
        self.assertEqual(['publication.commit', 'publication.integrate/main'], pending.outstanding(self.project, self.evidence))

    def test_stop_or_approval_wait_never_observes_even_after_git_delivery(self):
        self.assertEqual(0, self.finish()[0])
        self.commit()
        self.integrate()
        before = self.evidence.with_name('pending-publication.json').read_bytes()
        if self.RUNTIME == 'claude':
            self.assertEqual({}, self.stop(stop_hook_active=True))
            self.assertEqual(before, self.evidence.with_name('pending-publication.json').read_bytes())
        for signal in ({'user_interrupted': True}, {'approval_pending': True}, {'stop_reason': 'user_stop'}):
            self.assertEqual({}, self.stop(**signal))
            self.assertEqual(before, self.evidence.with_name('pending-publication.json').read_bytes())
        self.assertEqual({}, self.stop())

    def test_foreign_session_and_newer_completed_run_cannot_hide_or_steal_debt(self):
        self.assertEqual(0, self.finish()[0])
        self.assertEqual('', pending.pending_session_reason(self.project, {'runtime': self.RUNTIME, 'session_id': 'other'}))
        newer = self.evidence.parent.parent / 'newer' / 'preflight.json'
        newer.parent.mkdir()
        binding = json.loads(self.evidence.read_text())
        register_run(self.project, newer, binding['route'], binding['request_intake'])
        newer.write_text(json.dumps(binding))
        transition_run(self.project, newer, 'completed')
        self.assertEqual('block', self.stop()['decision'])

    def test_main_checkout_stop_observes_delivery_from_its_source_worktree(self):
        self.assertEqual(0, self.finish()[0])
        main = Path(self.tmp.name) / 'main-checkout'
        git(self.project, 'worktree', 'add', '-q', str(main), 'main')
        identity = {'runtime': self.RUNTIME, 'session_id': 'bound-session'}
        self.assertTrue(pending.pending_session_reason(main, identity))
        self.commit()
        self.assertTrue(pending.pending_session_reason(main, identity))
        git(main, 'merge', '--ff-only', 'work')
        self.assertEqual('', pending.pending_session_reason(main, identity))

    def test_corrupt_or_missing_receipt_is_still_owed(self):
        self.assertEqual(0, self.finish()[0])
        receipt = self.evidence.with_name('pending-publication.json')
        receipt.write_text('{}')
        self.assertEqual('block', self.stop()['decision'])
        receipt.unlink()
        self.assertEqual('block', self.stop()['decision'])

    def test_prepare_rejects_unstaged_unit_and_observation_requires_completion(self):
        git(self.project, 'reset', '-q', 'HEAD', 'source.txt')
        self.assertIn('worktree content must match', pending.record_pending(self.project, self.evidence, ITEMS))
        git(self.project, 'checkout', '--', 'source.txt')
        self.assertIn('stage the reviewed changes', pending.record_pending(self.project, self.evidence, ITEMS))
        (self.project / 'source.txt').write_text('reviewed staged content\n')
        git(self.project, 'add', 'source.txt')
        self.assertEqual('', pending.record_pending(self.project, self.evidence, ITEMS))
        self.commit()
        self.assertIn('completed bound run', pending.settle(self.project, self.evidence, 'publication.commit'))

    def test_staged_and_reviewed_worktree_must_match(self):
        (self.project / 'source.txt').write_text('different unstaged content\n')
        self.assertIn('worktree content must match', pending.record_pending(self.project, self.evidence, ITEMS))

    def test_foreign_checkout_and_missing_or_wrong_target_fail(self):
        self.assertEqual(0, self.finish()[0])
        self.commit()
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory)
            fixtures.initialize_git(foreign)
            self.assertIn('different repository', Proof.observe(foreign, self.receipt(), 'publication.commit', pending._git)[1])
        git(self.project, 'branch', '-D', 'main')
        self.assertTrue(Proof.observe(self.project, self.receipt(), 'publication.integrate/main', pending._git)[1])
        self.assertIn('not prepared', Proof.observe(self.project, self.receipt(), 'publication.integrate/other', pending._git)[1])

    def test_unmerged_index_is_never_prepared(self):
        git(self.project, 'reset', '-q', 'HEAD', 'source.txt')
        blob = git(self.project, 'rev-parse', 'HEAD:source.txt')
        # Feed a real conflict stage through update-index, rather than mocking proof output.
        import subprocess
        subprocess.run(['git', '-C', str(self.project), 'update-index', '--index-info'],
                       input=f'0 {"0" * 40}\tsource.txt\n100644 {blob} 1\tsource.txt\n',
                       text=True, check=True, capture_output=True)
        self.assertTrue(pending.record_pending(self.project, self.evidence, ITEMS))


class ClaudeLocalFinishTests(LocalFinishTests):
    RUNTIME = 'claude'


class MixedDeliveryTests(fixtures.FinishBase):
    REMAINING = [{'checkpoint': 'publication.commit', 'action': 'commit'},
                 {'checkpoint': 'publication.push', 'action': 'push'}]

    def setUp(self):
        def current(project, evidence, route, intake):
            route['local_delivery_contract'] = Proof.CONTRACT
            return register_run(project, evidence, route, intake)
        with patch('test_agent_run_interruption.register_run', side_effect=current):
            super().setUp()

    def prepare(self):
        self.branch = fixtures.attach_remote(self.project, self.tmp.name)
        (self.project / 'source.txt').write_text('reviewed mixed delivery\n')
        git(self.project, 'add', 'source.txt')

    def test_local_observation_keeps_remote_debt_and_manual_settle_guidance(self):
        self.assertEqual(0, self.finish()[0])
        initial = self.stop()['reason']
        self.assertIn('publication.commit', initial)
        self.assertIn('publication.push', initial)
        self.assertIn('settle', initial)
        git(self.project, 'commit', '-qm', 'reviewed')
        reason = self.stop()['reason']
        self.assertIn('publication.push', reason)
        self.assertIn('settle', reason)
        self.assertNotIn('publication.commit', reason)
        git(self.project, 'push', '-qu', 'origin', self.branch)
        self.assertEqual('', pending.settle(self.project, self.evidence, 'publication.push'))
        self.assertEqual({}, self.stop())


class LegacyVisibilityTests(fixtures.FinishBase):
    def test_newer_completed_run_does_not_hide_legacy_manual_settlement_debt(self):
        self.assertEqual(0, self.finish()[0])
        newer = self.evidence.parent.parent / 'newer' / 'preflight.json'
        newer.parent.mkdir()
        register_run(self.project, newer, self.run.route, self.run.intake)
        newer.write_bytes(self.evidence.read_bytes())
        transition_run(self.project, newer, 'completed')
        self.assertIn('publication.commit', self.stop()['reason'])


if __name__ == '__main__':
    unittest.main()
