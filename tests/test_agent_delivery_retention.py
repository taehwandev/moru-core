"""Completed runs keep unobserved delivery through the actual removal guard."""
import unittest
from pathlib import Path
from unittest.mock import patch

import test_agent_pending_publication as fixtures
import agent_pending_publication as pending
from agent_repository_checkouts import checkout_removal_hazard
from claude_pretool_checkout_removal import checkout_removal_denial
from agent_run_registry import register_run
from agent_run_registry import transition_run
from agent_continuation_store import continuation_path
from agent_delivery_retention import DeliveryRetention


class RetentionTests(fixtures.FinishBase):
    def test_cancelled_prepared_receipt_and_incomplete_scan_still_hold(self):
        self.assertEqual('', pending.record_pending(self.project, self.evidence, self.REMAINING))
        transition_run(self.project, self.evidence, 'cancelled')
        self.assertIn('publication.commit', checkout_removal_hazard(self.project))
        from agent_state_read import evidence_binding_key
        custom = self.project / '.moru' / 'custom' / 'preflight.json'
        bindings = {evidence_binding_key(self.project, custom): {
            'run_id': 'a' * 32, 'evidence_name': 'preflight.json', 'state': 'cancelled'}}
        with patch('agent_registry_read.active_run_bindings', return_value=bindings), \
                patch('agent_runtime_session.runtime_evidence_candidates', return_value=((), (), False)):
            self.assertIn('inspection incomplete', DeliveryRetention.reason(self.project))

    def test_missing_preflight_with_declaration_and_oversize_receipt_hold(self):
        self.assertEqual(0, self.finish()[0])
        receipt = self.evidence.with_name('pending-publication.json')
        original = self.evidence.read_bytes()
        receipt.unlink()
        self.evidence.unlink()
        self.assertIn('declared delivery evidence', checkout_removal_hazard(self.project))
        self.evidence.write_bytes(original)
        receipt.write_text('x' * (1024 * 1024 + 1))
        self.assertIn('safe read budget', checkout_removal_hazard(self.project))

    def test_dangling_checkpoint_is_not_treated_as_pruned_history(self):
        self.assertEqual(0, self.finish()[0])
        self.evidence.with_name('pending-publication.json').unlink()
        checkpoint = continuation_path(self.project, self.run.run['run_id'])
        checkpoint.unlink()
        checkpoint.symlink_to(checkpoint.with_name('missing-target'))
        self.assertIn('checkpoint is unreadable', checkout_removal_hazard(self.project))

    def test_corrupt_packet_and_missing_receipt_are_not_empty_debt(self):
        self.assertEqual(0, self.finish()[0])
        self.evidence.with_name('pending-publication.json').unlink()
        continuation_path(self.project, self.run.run['run_id']).write_text('{bad')
        self.assertIn('inspect', checkout_removal_hazard(self.project))

    def test_cancelled_unprepared_work_and_pruned_history_do_not_hold_checkout(self):
        transition_run(self.project, self.evidence, 'cancelled')
        self.assertEqual('', checkout_removal_hazard(self.project))
        from agent_state_read import evidence_binding_key
        from support.global_state import project_state_dir_target
        state = project_state_dir_target(self.project)
        bindings = {}
        for number in range(520):
            run_id = f'{number:032x}'
            path = state / 'runs' / run_id / 'preflight.json'
            bindings[evidence_binding_key(self.project, path)] = {
                'run_id': run_id, 'evidence_name': 'preflight.json', 'state': 'completed'}
        with patch('agent_registry_read.active_run_bindings', return_value=bindings):
            self.assertEqual('', DeliveryRetention.reason(self.project))

    def test_custom_registered_evidence_location_keeps_its_delivery(self):
        self.assertEqual(0, self.finish()[0])
        (self.project / 'source.txt').write_text('first delivery\n')
        fixtures.git(self.project, 'commit', '-qam', 'first')
        self.assertEqual('', pending.settle(self.project, self.evidence, 'publication.commit'))
        custom = self.evidence.parent.parent / 'custom' / 'preflight.json'
        custom.parent.mkdir()
        register_run(self.project, custom, self.run.route, self.run.intake)
        custom.write_bytes(self.evidence.read_bytes())
        self.assertEqual('', pending.record_pending(self.project, custom, self.REMAINING))
        transition_run(self.project, custom, 'completed')
        self.assertIn('publication.commit', checkout_removal_hazard(self.project))

    def test_finished_clean_checkout_retains_pending_delivery(self):
        self.assertEqual(0, self.finish()[0])
        for count_changes in (True, False):
            self.assertIn('publication.commit', checkout_removal_hazard(self.project, count_changes=count_changes))
        reason = checkout_removal_denial(['rm', '-rf', str(self.project)], Path(self.tmp.name))
        self.assertIn('unobserved delivery', reason)
        self.assertTrue(self.project.exists())

    def test_actual_settlement_releases_retention_without_writing_during_check(self):
        self.assertEqual(0, self.finish()[0])
        (self.project / 'source.txt').write_text('delivered\n')
        fixtures.git(self.project, 'commit', '-qam', 'delivered')
        self.assertEqual('', pending.settle(self.project, self.evidence, 'publication.commit'))
        receipt = self.evidence.with_name('pending-publication.json')
        before = receipt.read_bytes()
        self.assertEqual('', checkout_removal_hazard(self.project))
        self.assertEqual(before, receipt.read_bytes())

    def test_corrupt_missing_or_foreign_receipts_do_not_discard_debt(self):
        self.assertEqual(0, self.finish()[0])
        receipt = self.evidence.with_name('pending-publication.json')
        for raw in ('[]', '{bad'):
            receipt.write_text(raw)
            self.assertTrue(checkout_removal_hazard(self.project))
        receipt.unlink()
        self.assertIn('publication.commit', checkout_removal_hazard(self.project))


class CurrentRetentionTests(fixtures.FinishBase):
    def setUp(self):
        def current(project, evidence, route, intake):
            route['local_delivery_contract'] = 'staged_v1'
            return register_run(project, evidence, route, intake)
        with patch('test_agent_run_interruption.register_run', side_effect=current):
            super().setUp()

    def prepare(self):
        (self.project / 'source.txt').write_text('current reviewed content\n')
        fixtures.git(self.project, 'add', 'source.txt')

    def test_clean_committed_but_unobserved_delivery_is_retained_until_settlement(self):
        self.assertEqual(0, self.finish()[0])
        fixtures.git(self.project, 'commit', '-qm', 'current delivery')
        self.assertEqual('', fixtures.git(self.project, 'status', '--porcelain'))
        self.assertIn('publication.commit', checkout_removal_hazard(self.project))
        self.assertEqual('', pending.settle(self.project, self.evidence, 'publication.commit'))
        self.assertEqual('', checkout_removal_hazard(self.project))


if __name__ == '__main__':
    unittest.main()
