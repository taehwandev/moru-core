"""Finding identity, claim provenance, source bindings and observed closure."""
import unittest

from agent_review_findings import build_re_review_summary, normalize_findings

A, B = 'a' * 64, 'b' * 64
SNAPSHOTS = {'app.py': {'sha256': B, 'status': 'modified'}}


class ReviewFindingsTests(unittest.TestCase):
    def finding(self, **changes):
        return {'id': 'F-1', 'file': 'app.py', 'line': 1, 'severity': 'high',
                'claim': 'synthetic bug', 'state': 'fixed', 'original_sha256': A, **changes}

    def observed(self, **changes):
        return {'F-1': {'after_pass': {'ok': True, 'id': 'c' * 32,
                                     'successful': True, 'tests_run': 1, **changes}}}

    def test_stable_ids_preserve_explicit_identity_and_untruncated_claims(self):
        raw = [{'file': 'app.py', 'line': 1, 'claim': 'x' * 300 + suffix} for suffix in ('a', 'b')]
        first = normalize_findings(raw)
        self.assertEqual([r['id'] for r in first], [r['id'] for r in normalize_findings(raw)])
        self.assertNotEqual(first[0]['id'], first[1]['id'])
        self.assertEqual(first[0]['claim'], first[1]['claim'])
        self.assertEqual('explicit', normalize_findings([{'id': 'explicit', 'claim': 'x'}])[0]['id'])

    def test_duplicate_explicit_identity_is_not_silently_conflated(self):
        with self.assertRaises(ValueError):
            normalize_findings([self.finding(), self.finding(claim='different issue')])

    def test_bare_pass_and_caller_hashes_never_close_a_finding(self):
        for verification in ({'outcome': 'pass'}, {'outcome': 'pass', 'source_sha256': B},
                             {'receipt_ref': 'a' * 32, 'execution_id': 'c' * 32, 'outcome': 'pass'}):
            with self.subTest(verification=verification):
                result = normalize_findings([self.finding(verification=verification)], source_snapshots=SNAPSHOTS)
                self.assertEqual('reopened', result[0]['state'])
        claimed_binding = self.finding(source_binding={'current_sha256': B},
                                      verification={'outcome': 'pass'})
        self.assertEqual('reopened', normalize_findings([claimed_binding])[0]['state'])

    def test_only_separately_observed_current_evidence_can_close(self):
        result = normalize_findings([self.finding(verification={'execution_id': 'c' * 32})],
            source_snapshots=SNAPSHOTS, observations=self.observed())
        self.assertEqual('resolved', result[0]['state'])
        self.assertEqual('c' * 32, result[0]['resolution_evidence']['id'])
        changed_id = normalize_findings([self.finding(verification={'execution_id': 'd' * 32})],
            source_snapshots=SNAPSHOTS, observations=self.observed())
        self.assertEqual('reopened', changed_id[0]['state'])

    def test_wrong_file_finding_hash_or_zero_claim_remains_unresolved(self):
        refs = [{'file': 'other.py'}, {'finding_id': 'other'}, {'source_sha256': A},
                {'tests_run': 0}, {'outcome': 'fail'}]
        for ref in refs:
            with self.subTest(ref=ref):
                result = normalize_findings([self.finding(verification=ref)],
                    source_snapshots=SNAPSHOTS, observations=self.observed())
                self.assertEqual('reopened', result[0]['state'])

    def test_missing_source_does_not_close_even_with_observed_test_facts(self):
        result = normalize_findings([self.finding(verification={'source_sha256': B})],
            source_snapshots={'app.py': {'status': 'deleted'}}, observations=self.observed())
        self.assertEqual('reopened', result[0]['state'])

    def test_changed_low_impact_prose_still_requires_observed_review(self):
        raw = self.finding(severity='low', verification={'kind': 'source_review'})
        self.assertEqual('reopened', normalize_findings([raw], source_snapshots=SNAPSHOTS)[0]['state'])
        observations = self.observed(kind='source_review', successful=False)
        self.assertEqual('resolved', normalize_findings([raw], source_snapshots=SNAPSHOTS,
                                                     observations=observations)[0]['state'])
        reproducible = {**raw, 'reproducible': True}
        self.assertEqual('reopened', normalize_findings([reproducible], source_snapshots=SNAPSHOTS,
                                                      observations=observations)[0]['state'])

    def test_before_fail_must_be_an_observed_failure_when_supplied(self):
        raw = self.finding(verification={'before_fail': {}, 'after_pass': {}})
        self.assertEqual('reopened', normalize_findings([raw], source_snapshots=SNAPSHOTS,
                                                      observations=self.observed())[0]['state'])
        observed = self.observed()
        observed['F-1']['before_fail'] = {'ok': True, 'successful': False, 'id': 'd' * 32}
        result = normalize_findings([raw], source_snapshots=SNAPSHOTS, observations=observed)
        self.assertEqual('resolved', result[0]['state'])

    def test_open_finding_tracks_initial_and_changed_source_for_re_review(self):
        initial = normalize_findings([{'id': 'F-1', 'file': 'app.py', 'claim': 'check'}],
                                     source_snapshots={'app.py': {'sha256': A, 'status': 'modified'}})
        self.assertEqual(A, initial[0]['source_binding']['original_sha256'])
        changed = normalize_findings(initial, source_snapshots=SNAPSHOTS)
        summary = build_re_review_summary(changed, provenance='caller')
        self.assertEqual('stale', changed[0]['state'])
        self.assertEqual(['F-1'], summary['unresolved_ids'])
        self.assertEqual(['app.py'], summary['changed_paths'])


if __name__ == '__main__':
    unittest.main()
