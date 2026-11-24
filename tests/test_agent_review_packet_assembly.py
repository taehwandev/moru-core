"""Review assembly retains source once, with budget-safe fallback definitions."""
import hashlib
import os
import unittest
from unittest.mock import patch

import test_agent_review_packet as fixture
from agent_review_packet import ReviewPacket
from agent_review_packet_assembly import ReviewAssembly


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

    def test_native_assembly_matches_reference_at_multiple_byte_budgets(self):
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.base / "home"
        home.mkdir()
        install(home)
        self.write("new.py", "padding = \"" + "한😀" * 280 + "\"\ndef tiny():\n    return 1\n")
        fixture.git(self.root, "add", "new.py")
        paths = ["new.py", "app.py", "notes.txt"]
        env = environment(self.base)
        for limit in (4000, 32768):
            with self.subTest(limit=limit):
                with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = ReviewPacket.build(self.root, paths, max_bytes=limit)
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(ReviewAssembly, "build", side_effect=AssertionError("Python assembly")):
                    actual = ReviewPacket.build(self.root, paths, max_bytes=limit)
                rendered = ReviewPacket.render(actual).encode("utf-8")
                self.assertEqual(rendered, ReviewPacket.render(expected).encode("utf-8"))
                self.assertLessEqual(len(rendered), limit)
                body = {key: value for key, value in actual.items() if key != "packet_sha256"}
                self.assertEqual(actual["packet_sha256"], hashlib.sha256(ReviewPacket.render(body).encode()).hexdigest())
                self.assertNotIn(fixture.SECRET.encode(), rendered)
        self.assertFalse((self.root / "EXECUTED").exists())

    def test_native_metadata_overflow_preserves_packet_error(self):
        from native_launcher_support import NATIVE, install
        from native_pretool_support import environment

        if not NATIVE.is_file():
            self.skipTest("native test artifact unavailable")
        home = self.base / "home"
        home.mkdir()
        install(home)
        checks = [{"check": f"fixture {index}", "result": "한글" * 120} for index in range(12)]
        with patch.dict(os.environ, environment(self.base), clear=True), \
                patch.object(ReviewAssembly, "build", side_effect=AssertionError("Python assembly")):
            with self.assertRaisesRegex(ValueError, "max_bytes is too small for the packet metadata and omissions"):
                ReviewPacket.build(self.root, ["app.py"], checks=checks, max_bytes=2048)
