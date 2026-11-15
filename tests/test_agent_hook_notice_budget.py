"""Default notices stay bounded while retaining actionable evidence/authority."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_agent_hook_summary import agent_hook as hook


class NoticeBudgetTests(unittest.TestCase):
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
