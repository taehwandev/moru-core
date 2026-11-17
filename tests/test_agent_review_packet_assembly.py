"""Review assembly retains source once, with budget-safe fallback definitions."""
import unittest
import test_agent_review_packet as fixture
from agent_review_packet import ReviewPacket


class AssemblyTests(unittest.TestCase):
    setUp = fixture.ReviewPacketTest.setUp
    write = fixture.ReviewPacketTest.write

    def test_added_source_is_not_repeated_when_whole_diff_is_kept(self):
        self.write('new.py', 'def new():\n    return "single-source-marker"\n')
        fixture.git(self.root, 'add', 'new.py')
        packet = ReviewPacket.build(self.root, ['new.py'])
        self.assertEqual(1, ReviewPacket.render(packet).count('single-source-marker'))
        self.assertEqual([], packet['definitions'])
        self.assertTrue(any(o['reason'] == 'covered_by_diff' for o in packet['omissions']))

    def test_large_added_diff_falls_back_to_complete_small_definitions(self):
        self.write('new.py', '\n'.join(f'VALUE_{i} = "long padding {i}"' for i in range(400)) + '\ndef tiny():\n    return 1\n')
        fixture.git(self.root, 'add', 'new.py')
        packet = ReviewPacket.build(self.root, ['new.py'], max_bytes=4000)
        self.assertEqual([], packet['diffs'])
        self.assertEqual(['tiny'], [d['symbol'] for d in packet['definitions']])
        self.assertLessEqual(len(ReviewPacket.render(packet).encode()), 4000)
