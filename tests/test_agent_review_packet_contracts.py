"""Static cross-file contracts and compact added-source representation."""
import json
import unittest
from unittest.mock import patch
import test_agent_review_packet as fixture
from agent_review_packet import ReviewPacket


class ContractTests(unittest.TestCase):
    setUp = fixture.ReviewPacketTest.setUp
    write = fixture.ReviewPacketTest.write

    def test_imported_signature_and_referenced_constants_without_execution(self):
        self.write('api.py', 'from pathlib import Path\nPath(__file__).with_name("API_EXECUTED").touch()\n'
                   'LIMIT = 7\ndef fetch(key: str, timeout: int = 3) -> dict:\n    return {"body-must-stay-out": key}\n')
        fixture.git(self.root, 'add', 'api.py')
        fixture.git(self.root, 'commit', '-qm', 'local api')
        self.write('app.py', 'from api import fetch, LIMIT\nLOCAL = 2\ndef run():\n    return fetch("value", timeout=LIMIT + LOCAL)\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        contracts = {(c['path'], c['symbol']): c for c in packet['contracts']}
        self.assertIn(('api.py', 'fetch'), contracts)
        self.assertIn('timeout: int=3', contracts[('api.py', 'fetch')]['signature'])
        self.assertIn(('api.py', 'LIMIT'), contracts)
        self.assertIn(('app.py', 'LOCAL'), contracts)
        self.assertNotIn('body-must-stay-out', ReviewPacket.render(packet))
        self.assertFalse((self.root / 'API_EXECUTED').exists())
        self.assertEqual('contract', next(f['role'] for f in packet['files'] if f['path'] == 'api.py'))

    def test_untracked_and_symlink_import_sources_are_omitted_not_read(self):
        self.write('unsafe.py', 'LIMIT = "hidden-contract-marker"\n')
        self.write('app.py', 'from unsafe import LIMIT\ndef run():\n    return LIMIT\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        self.assertNotIn('hidden-contract-marker', ReviewPacket.render(packet))
        self.assertTrue(any(o['reason'] == 'guarded_source_unavailable' for o in packet['omissions']))

    def test_shadowed_imports_and_duplicate_definitions_are_not_claimed_as_contracts(self):
        self.write('api.py', 'def fetch(value):\n    return value\ndef twice(value):\n    return value\ndef twice(other):\n    return other\n')
        fixture.git(self.root, 'add', 'api.py')
        fixture.git(self.root, 'commit', '-qm', 'api ambiguity')
        self.write('app.py', 'from api import fetch, twice\ndef run(fetch):\n    return fetch(twice(1))\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        self.assertFalse(any(c['symbol'] == 'fetch' for c in packet['contracts']))

        self.assertTrue(any(o.get('symbol') == 'twice' and o['reason'] == 'explicit_context_required' for o in packet['omissions']))
        self.write('app.py', 'from api import fetch\ndef run():\n    from elsewhere import fetch\n    return fetch(1)\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        self.assertFalse(any(c['symbol'] == 'fetch' for c in packet['contracts']))


    def test_automatic_literals_are_redacted_and_sensitive_constants_omitted(self):
        self.write('settings.py', 'API_TOKEN = "secret-auto-marker"\nLABEL = "label-auto-marker"\ndef connect(password="password-auto-marker"):\n    return password\n')
        fixture.git(self.root, 'add', 'settings.py')
        fixture.git(self.root, 'commit', '-qm', 'settings contract')
        self.write('app.py', 'from settings import API_TOKEN, LABEL, connect\ndef run():\n    return connect(), API_TOKEN, LABEL\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        text = ReviewPacket.render(packet)
        for marker in ('secret-auto-marker', 'label-auto-marker', 'password-auto-marker'):
            self.assertNotIn(marker, text)
        self.assertIn('<redacted literal>', text)
        self.assertTrue(any(o.get('symbol') == 'API_TOKEN' and o['reason'] == 'explicit_context_required' for o in packet['omissions']))

    def test_duplicate_augmented_and_conditional_constants_are_not_claimed(self):
        self.write('config.py', 'A = 1\nA = 2\nB = 1\nB += 1\nC = 1\nif True:\n    C = 2\nX, Y = 3, 4\n')
        fixture.git(self.root, 'add', 'config.py')
        fixture.git(self.root, 'commit', '-qm', 'constant bindings')
        self.write('app.py', 'from config import A, B, C, X, Y\ndef run():\n    return A, B, C, X, Y\n')
        packet = ReviewPacket.build(self.root, ['app.py'])
        self.assertFalse(any(c['symbol'] in ('A', 'B', 'C') for c in packet['contracts']))
        tuples = [c for c in packet['contracts'] if c['path'] == 'config.py']
        self.assertEqual(1, len(tuples))
        self.assertEqual({'X', 'Y'}, set(tuples[0]['symbols']))

    def test_import_rebinding_and_wildcards_do_not_claim_stale_signatures(self):
        for body in ('def fetch(x):\n    return x\nfrom _fast import fetch\n',
                     'def fetch(x):\n    return x\ntry:\n    from _fast import fetch\nexcept ImportError:\n    pass\n',
                     'def fetch(x):\n    return x\nfrom _fast import *\n'):
            with self.subTest(body=body):
                self.write('api.py', body)
                fixture.git(self.root, 'add', 'api.py')
                self.write('app.py', 'from api import fetch\ndef run():\n    return fetch(1)\n')
                packet = ReviewPacket.build(self.root, ['app.py'])
                self.assertFalse(any(c['symbol'] == 'fetch' for c in packet['contracts']))
                self.assertTrue(any(o.get('symbol') == 'fetch' and o['reason'] == 'explicit_context_required' for o in packet['omissions']))

    def test_deep_signature_projection_is_reported_as_missing_context(self):
        self.write('api.py', 'def fetch(value):\n    return value\n')
        fixture.git(self.root, 'add', 'api.py')
        self.write('app.py', 'from api import fetch\ndef run():\n    return fetch(1)\n')
        with patch('agent_review_packet_contracts.ast.unparse', side_effect=RecursionError):
            packet = ReviewPacket.build(self.root, ['app.py'])
        self.assertTrue(any(o['reason'] == 'explicit_context_required' for o in packet['omissions']))


if __name__ == '__main__':
    unittest.main()
