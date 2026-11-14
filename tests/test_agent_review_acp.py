"""Exercise review orchestration through a real subprocess speaking ACP."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_review_acp import run_review


FAKE = r'''
import json, sys, time
from pathlib import Path
scenario, log = sys.argv[1:]
def emit(data):
    print(json.dumps({'jsonrpc':'2.0', **data}), flush=True)
def update(kind, text='working', sid='owned'):
    emit({'method':'session/update','params':{'sessionId':sid,'update':
        {'sessionUpdate':kind,'content':{'type':'text','text':text}}}})
if scenario == 'startup_retry':
    marker=Path(log+'.started')
    if not marker.exists():
        marker.touch(); sys.exit(1)
for line in sys.stdin:
    m=json.loads(line); method=m.get('method')
    with open(log,'a') as f: f.write(json.dumps(m)+'\n')
    if method=='initialize':
        if scenario=='rpc_error': emit({'id':m['id'],'error':{'code':-32000,'message':'provider error'}})
        else: emit({'id':m['id'],'result':{'protocolVersion':1}})
    elif method=='session/new':
        emit({'id':m['id'],'result':{'sessionId':'owned','modes':
            {'currentModeId':'default','availableModes':None if scenario=='malformed_modes' else [{'id':'plan'}]}}})
    elif method=='session/set_mode': emit({'id':m['id'],'result':{}})
    elif method=='session/prompt':
        prompt_id=m['id']
        if scenario in ('idle','cancel_unknown'):
            continue
        if scenario in ('foreign','usage'):
            for _ in range(6):
                time.sleep(.04)
                if scenario=='foreign': update('agent_thought_chunk',sid='foreign')
                else: update('usage_update')
            update('agent_message_chunk','No blocking defects found.')
            emit({'id':prompt_id,'result':{'stopReason':'end_turn'}})
            continue
        if scenario=='lost_after_prompt': sys.exit(1)
        if scenario=='permission':
            emit({'id':90,'method':'session/request_permission','params':{'sessionId':'owned','options':[]}})
            continue
        if scenario=='progress':
            for _ in range(6):
                time.sleep(.04); update('agent_thought_chunk','private reasoning')
        if scenario!='empty': update('agent_message_chunk','No blocking defects found.')
        emit({'id':prompt_id,'result':{'stopReason':'end_turn'}})
    elif method=='session/cancel':
        if scenario!='cancel_unknown': emit({'id':prompt_id,'result':{'stopReason':'cancelled'}})
    elif m.get('id')==90 and 'result' in m:
        update('agent_message_chunk','No blocking defects found.')
        emit({'id':prompt_id,'result':{'stopReason':'end_turn'}})
'''


class AcpReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root / 'fake.py'
        self.fake.write_text(FAKE)
        self.log = self.root / 'calls.jsonl'

    def review(self, scenario, **kwargs):
        return run_review([sys.executable, str(self.fake), scenario, str(self.log)],
                          self.root, 'Review this code without tools.',
                          idle_timeout=.12, max_seconds=kwargs.pop('max_seconds', 2), cancel_timeout=.1, **kwargs)

    def calls(self, method):
        if not self.log.exists():
            return []
        return [x for x in map(json.loads, self.log.read_text().splitlines())
                if x.get('method') == method]

    def test_active_progress_survives_multiple_idle_windows(self):
        result = self.review('progress')
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['response'], 'No blocking defects found.')
        self.assertEqual(result['activity_events'], 7)
        self.assertNotIn('private reasoning', json.dumps(result))
        self.assertEqual(len(self.calls('session/prompt')), 1)
        self.assertFalse(self.calls('session/cancel'))

    def test_idle_is_cancelled_and_not_replayed(self):
        result = self.review('idle')
        self.assertEqual(result['failure_code'], 'idle_timeout')
        self.assertTrue(result['cancellation_confirmed'])
        self.assertEqual(len(self.calls('session/prompt')), 1)
        self.assertEqual(len(self.calls('session/cancel')), 1)

    def test_unknown_cancellation_preserves_session_for_observation(self):
        result = self.review('cancel_unknown')
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['next_action'], 'observe_existing_session')
        self.assertEqual(result['session_id'], 'owned')
        self.assertFalse(result['cancellation_confirmed'])

    def test_setup_transport_failure_retries_before_prompt_only(self):
        result = self.review('startup_retry')
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['launch_attempts'], 2)
        self.assertEqual(len(self.calls('session/prompt')), 1)

    def test_transport_loss_after_prompt_is_never_replayed(self):
        result = self.review('lost_after_prompt')
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['launch_attempts'], 1)
        self.assertEqual(result['next_action'], 'observe_existing_session')
        self.assertEqual(len(self.calls('session/prompt')), 1)

    def test_empty_success_is_not_a_review(self):
        result = self.review('empty')
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['failure_code'], 'missing_final_response')

    def test_permission_denial_cannot_masquerade_as_complete_review(self):
        result = self.review('permission')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['permissions_denied'], 1)
        rows = list(map(json.loads, self.log.read_text().splitlines()))
        reply = next(x for x in rows if x.get('id') == 90)
        self.assertEqual(reply['result']['outcome']['outcome'], 'cancelled')

    def test_nonprogress_notifications_do_not_prevent_idle_timeout(self):
        for scenario in ('foreign', 'usage'):
            with self.subTest(scenario=scenario):
                result = self.review(scenario)
                self.assertEqual(result['failure_code'], 'idle_timeout')
                self.assertEqual(result['activity_events'], 0)

    def test_invalid_time_limits_fail_before_launch(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    run_review([sys.executable], self.root, 'review', idle_timeout=value)
        self.assertFalse(self.log.exists())

    def test_malformed_mode_capability_blocks_before_prompt(self):
        result = self.review('malformed_modes')
        self.assertEqual(result['failure_code'], 'read_only_mode_unavailable')
        self.assertFalse(self.calls('session/prompt'))

    def test_structured_provider_error_is_preserved_without_blind_retry(self):
        result = self.review('rpc_error')
        self.assertEqual(result['failure_code'], 'protocol_error')
        self.assertEqual(result['protocol_error_code'], -32000)
        self.assertEqual(result['launch_attempts'], 1)
        self.assertFalse(self.calls('session/prompt'))

    def test_total_budget_still_bounds_an_active_turn(self):
        result = self.review('progress', max_seconds=.09)
        self.assertEqual(result['failure_code'], 'total_timeout')
        self.assertEqual(len(self.calls('session/prompt')), 1)
        self.assertEqual(len(self.calls('session/cancel')), 1)
