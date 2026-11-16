"""Default notices stay bounded while retaining actionable evidence/authority."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_agent_hook_summary import agent_hook as hook


class NoticeBudgetTests(unittest.TestCase):
    COMMON = ['common/skills/agent-operating-skill/SKILL.md',
              'workflows/skills/review-and-commit/SKILL.md']
    NEW_CARD = 'workflows/skills/new-task/SKILL.md'

    def _partial_summary(self, reused, *, effect='local_write'):
        docs = [*self.COMMON, self.NEW_CARD]
        payload = {'runtime_session': {'runtime': 'claude', 'session_id': 'fixture'},
            'route': {'command': 'bugfix', 'required_docs': docs, 'retrospective_contract': 'causal_v1',
                'gates': ['tests', 'review hook', 'retrospective check'],
                'hooks': [{'hook': h, 'required': True} for h in ('start', 'review', 'finish')],
                'request_classification': {'intent_envelope': {'effective_effect': effect}}}}
        with patch.object(Path, 'read_text', return_value=json.dumps(payload)), \
                patch.object(hook, '_isolated_run_preflight', return_value=True), \
                patch.object(hook, 'required_doc_reuse', return_value={
                    'reused': reused, 'unread': [d for d in docs if d not in reused], 'takeaways': []}):
            return '\n'.join(hook._hook_summary_from_preflight(Path('manifest.json')))

    def test_new_task_card_keeps_reading_obligation_without_reprinting_proven_common_guidance(self):
        summary = self._partial_summary(self.COMMON)
        self.assertIn('Required knowledge (1 required docs', summary)
        self.assertIn(self.NEW_CARD, summary)
        self.assertIn('Guidance reuse:', summary)
        self.assertNotIn('Work continuity:', summary)
        self.assertNotIn('Closeout reuse:', summary)
        for dynamic in ('Required hooks:', '--review-outcome', 'tests: check, result',
                        'retrospective check: skills_checked', 'causal_v1 requires'):
            self.assertIn(dynamic, summary)

    def test_missing_common_proof_keeps_full_guidance(self):
        for reused in ([], self.COMMON[:1], self.COMMON[1:], [self.NEW_CARD]):
            with self.subTest(reused=reused):
                summary = self._partial_summary(reused)
                self.assertIn('Work continuity:', summary)
                self.assertIn('Closeout reuse:', summary)

    def test_partial_reuse_keeps_current_commit_authority_and_current_gate_fields(self):
        for effect in ('local_write', 'git_write', 'external_write'):
            with self.subTest(effect=effect):
                summary = self._partial_summary(self.COMMON, effect=effect)
                self.assertEqual(effect != 'local_write', 'Same-run local commit:' in summary)
                self.assertIn('tests: check, result', summary)
                self.assertIn('learning_decision', summary)

    def test_valid_retrospective_pairs_are_visible_before_first_submission(self):
        for contract in ('compact_v1', 'causal_v1'):
            payload = {'route': {'gates': ['tests', 'review hook', 'retrospective check'],
                                 'retrospective_contract': contract}}
            with self.subTest(contract=contract), patch.object(
                    Path, 'read_text', return_value=json.dumps(payload)):
                summary = '\n'.join(hook._hook_summary_from_preflight(Path('manifest.json')))
            for pair in ('"no_reusable_gap" + "not_needed"', '"no_skill_used" + "not_needed"',
                         '"reusable_gap" + "recorded"', '"skills_checked":"none"'):
                self.assertIn(pair, summary)

    def test_common_notice_groups_drop_at_least_a_quarter_from_2371_bytes(self):
        route = {'gates': ['tests', 'review hook', 'retrospective check'],
                 'request_classification': {'intent_envelope': {'effective_effect': 'git_write'}}}
        groups = [hook._required_hooks_lines(['start', 'review', 'finish']),
                  hook._continuation_summary_lines('bugfix'), hook._closeout_reuse_lines(),
                  hook._same_run_commit_lines(route), hook._gate_batch_guidance_lines(route['gates'])]
        self.assertLessEqual(sum(len('\n'.join(g).encode()) for g in groups), 1778)

    def test_shorter_notices_preserve_all_runtime_gate_and_authority_fields(self):
        for runtime in ('codex', 'claude', 'antigravity'):
            for contract in ('compact_v1', 'causal_v1'):
                payload = {'runtime_session': {'runtime': runtime}, 'route': {
                    'command': 'small-change' if contract == 'compact_v1' else 'bugfix',
                    'retrospective_contract': contract,
                    'gates': ['tests', 'review hook', 'retrospective check'],
                    'hooks': [{'hook': h, 'required': True} for h in ('start', 'review', 'finish')],
                    'request_classification': {'intent_envelope': {'effective_effect': 'git_write'}}}}
                with self.subTest(runtime=runtime, contract=contract), patch.object(
                        Path, 'read_text', return_value=json.dumps(payload)):
                    text = '\n'.join(hook._hook_summary_from_preflight(Path('manifest.json')))
                for required in ('start', 'review', 'finish', '--review-outcome', '--code-review-evidence',
                                 'tests: check, result', 'skills_checked', 'learning_decision',
                                 'same session, target, HEAD and staged bytes', 'matching authority'):
                    self.assertIn(required, text)
                self.assertIn(contract, text)

    def test_local_write_alone_never_gets_commit_guidance(self):
        route = {'gates': ['review hook'],
                 'request_classification': {'intent_envelope': {'effective_effect': 'local_write'}}}
        self.assertEqual([], hook._same_run_commit_lines(route))

    def test_verified_doc_reuse_suppresses_common_prose_but_keeps_current_gates(self):
        payload = {'runtime_session': {'runtime': 'claude', 'session_id': 'fixture-session'}, 'route': {
            'command': 'bugfix', 'required_docs': ['known.md'], 'retrospective_contract': 'causal_v1',
            'gates': ['tests', 'review hook', 'retrospective check'],
            'hooks': [{'hook': h, 'required': True} for h in ('start', 'review', 'finish')]}}
        results = []
        for reused, unread in (([], ['known.md']), (['known.md'], [])):
            with patch.object(Path, 'read_text', return_value=json.dumps(payload)), \
                    patch.object(hook, '_isolated_run_preflight', return_value=True), \
                    patch.object(hook, 'required_doc_reuse', return_value={
                        'reused': reused, 'unread': unread, 'takeaways': []}):
                results.append('\n'.join(hook._hook_summary_from_preflight(Path('manifest.json'))))
        fresh, retained = results
        self.assertIn('Work continuity:', fresh)
        self.assertNotIn('Work continuity:', retained)
        self.assertNotIn('Closeout reuse:', retained)
        self.assertIn('Guidance reuse:', retained)
        self.assertLess(len(retained.encode()), len(fresh.encode()) - 700)
        for required in ('Required hooks:', '--review-outcome', 'tests: check, result',
                         'retrospective check: skills_checked', 'causal_v1 requires'):
            self.assertIn(required, retained)
