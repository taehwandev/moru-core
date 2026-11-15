"""Immutable272e553f CLI oracle, actual native IO and source-bound selection."""
import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent_behavior_trace as trace

ROOT = Path(__file__).resolve().parents[1]
NATIVE = Path(os.environ.get('MORU_BEHAVIOR_NATIVE', ROOT / '.moru/native/bin/moru-native-launcher'))
ORACLE = ROOT / 'tests/fixtures/behavior-trace-original.py'
DIGITS = str(getattr(sys, 'get_int_max_str_digits', lambda: 0)())


def record():
    return {'phase': 'finished', 'runtime_path': '/private/runtime', 'runtime_digest': 'digest',
            'status': 'ok', 'response': 'private response', 'session_id': 'private-session',
            'events': [{'event_type': 'review.record_initialized'},
                       {'event_type': 'review.finished', 'status': 'ok'}]}


@unittest.skipUnless(NATIVE.is_file(), 'native test candidate requires explicit compilation approval')
class NativeBehaviorReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='moru-trace-test-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / '검토 record.json'
        self.path.write_text(json.dumps(record()), encoding='utf-8')
        self.args = argparse.Namespace(review_record=self.path, provider='agy', case_id='case-1',
                                       native_executable=NATIVE)

    def oracle(self, *, provider='agy', case='case-1', native=NATIVE):
        return subprocess.run([sys.executable, '-B', str(ORACLE), '--review-record', str(self.path),
            '--provider', provider, '--case-id', case, '--native-executable', str(native)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=15)

    def native(self, *, provider='agy', case='case-1', **env):
        return subprocess.run([str(NATIVE), 'offline', '--behavior-review-export', str(self.path),
            provider, case, DIGITS], capture_output=True, stdin=subprocess.DEVNULL,
            env={**os.environ, **env}, timeout=15)

    def parity(self, **options):
        before = self.path.read_bytes() if self.path.is_file() else None
        expected = self.oracle(**options)
        actual = self.native(**options)
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                         (expected.returncode, expected.stdout, expected.stderr))
        if before is not None:
            self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [self.path.name])
        return actual

    def test_valid_records_exact_bytes_and_private_metadata_truthiness(self):
        for provider in ('codex', 'claude', 'agy'):
            for status in ('ok', 'blocked', 'needs_inspection'):
                with self.subTest(provider=provider, status=status):
                    data = record()
                    data['status'] = data['events'][-1]['status'] = status
                    data['runtime_path'], data['runtime_digest'] = [1], float('nan')
                    self.path.write_text(json.dumps(data), encoding='utf-8')
                    done = self.parity(provider=provider)
                    self.assertEqual(done.returncode, 0)
                    self.assertNotIn(b'private', done.stdout + done.stderr)

    def test_invalid_records_fail_without_private_content(self):
        changes = [('phase', 'submitted'), ('runtime_path', ''), ('runtime_digest', {}),
            ('status', 'blocked'), ('events', []), ('events', {}), ('events', [None]),
            ('events', [{'event_type': 'review.finished', 'status': 'ok', 'content': 'private'}]),
            ('events', [{'event_type': 'review.finished', 'status': 'ok'}, {'event_type': 'worker.result'}]),
            ('events', [{'event_type': 'unknown'}, {'event_type': 'review.finished', 'status': 'ok'}])]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                data = record()
                data[field] = value
                self.path.write_text(json.dumps(data), encoding='utf-8')
                self.assertEqual(self.parity().returncode, 1)

    def test_bom_duplicates_nonfinite_private_data_and_invalid_json(self):
        rows = [b'\xef\xbb\xbf' + json.dumps(record()).encode(),
                json.dumps(record()).replace('"phase": "finished"', '"phase":"bad","phase":"finished"').encode(),
                b'null', b'[]', b'{', b'{"secret":"private"}', b'x' * (trace.MAX_BYTES + 1)]
        for index, raw in enumerate(rows):
            with self.subTest(index=index):
                self.path.write_bytes(raw)
                self.parity()

    def test_event_count_and_case_boundaries(self):
        for count in (2048, 2049):
            data = record()
            data['events'] = [{'event_type': 'worker.result'}] * (count - 1) + data['events'][-1:]
            self.path.write_text(json.dumps(data), encoding='utf-8')
            with self.subTest(count=count):
                self.parity()
        self.path.write_text(json.dumps(record()), encoding='utf-8')
        for case in ('x' * 80, 'x' * 81, '', '한글', 'has space'):
            with self.subTest(case=case):
                self.parity(case=case)

    def test_record_byte_limit_includes_ignored_private_metadata(self):
        data = record()
        data['private_padding'] = ''
        packet = json.dumps(data).encode()
        raw = packet.replace(b'"private_padding": ""',
            b'"private_padding": "' + b'p' * (trace.MAX_BYTES - len(packet)) + b'"')
        self.assertEqual(len(raw), trace.MAX_BYTES)
        self.path.write_bytes(raw)
        self.assertEqual(self.parity().returncode, 0)
        self.path.write_bytes(raw + b' ')
        self.assertEqual(self.parity().returncode, 1)

    def test_missing_and_directory_errors_are_fixed_without_softening(self):
        self.path.unlink()
        for directory in (False, True):
            if directory:
                self.path.mkdir()
            expected = self.oracle()
            actual = self.native(MORU_HOOK_SOFT_FAIL='1')
            self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                             (expected.returncode, expected.stdout, expected.stderr))
            self.assertEqual(actual.returncode, 1)

    def test_public_main_is_fused_and_uses_one_native_process(self):
        observed = []
        run = subprocess.run
        def observe(command, **kwargs):
            observed.append(command)
            return run(command, **kwargs)
        argv = ['agent_behavior_trace.py', '--review-record', str(self.path), '--provider', 'agy',
                '--case-id', 'case-1', '--native-executable', str(NATIVE)]
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), patch.object(trace.subprocess, 'run', side_effect=observe), \
                patch.object(trace, 'export_review', side_effect=AssertionError('Python record replay')), \
                patch.dict(os.environ, {'MORU_LAUNCHER_BACKEND': 'auto'}), contextlib.redirect_stdout(output):
            trace.main()
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][2], '--behavior-review-export')
        self.assertEqual(output.getvalue().encode(), self.oracle().stdout)

    def test_unsupported_encoding_and_depth_use_exact_read_only_oracle(self):
        data = record()
        for encoding in ('utf-16', 'utf-32', 'utf-16-le', 'utf-32-be'):
            with self.subTest(encoding=encoding):
                self.path.write_bytes(json.dumps(data).encode(encoding))
                done = self.native()
                self.assertEqual((done.returncode, done.stdout, done.stderr), (78, b'', b''))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(trace._native_export(self.args))
                self.assertEqual(self.oracle().returncode, 0)
        data['private_nested'] = []
        raw = json.dumps(data).replace('"private_nested": []', '"private_nested":' + '[' * 150 + '0' + ']' * 150)
        self.path.write_text(raw, encoding='utf-8')
        self.assertEqual(self.native().returncode, 78)
        self.assertEqual(self.oracle().returncode, 0)

    def test_rollback_stale_and_alternate_executables_select_before_spawn(self):
        with patch.dict(os.environ, {'MORU_LAUNCHER_BACKEND': 'python'}), \
                patch('support.native_launcher_install.artifact_plan') as plan:
            self.assertIsNone(trace._native_export_command(self.args))
            plan.assert_not_called()
        with patch('support.native_launcher_install.artifact_plan', return_value=None):
            self.assertIsNone(trace._native_export_command(self.args))
        alternate = copy.copy(self.args)
        alternate.native_executable = Path(sys.executable)
        self.assertIsNone(trace._native_export_command(alternate))

    def test_alternate_executable_keeps_original_cli_contract(self):
        alternate = self.directory / 'alternate-normalizer'
        alternate.write_text('#!/bin/sh\nprintf \'{"custom": true}\'\n', encoding='utf-8')
        alternate.chmod(0o700)
        argv = [sys.executable, '-B', str(ROOT / 'scripts/agent_behavior_trace.py'),
                '--review-record', str(self.path), '--provider', 'agy', '--case-id', 'case-1',
                '--native-executable', str(alternate)]
        actual = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        expected = self.oracle(native=alternate)
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                         (expected.returncode, expected.stdout, expected.stderr))
        self.assertEqual(actual.stdout, b'{"custom": true}\n')

    def test_integer_limit_profile_declines_before_opening_record(self):
        done = subprocess.run([str(NATIVE), 'offline', '--behavior-review-export',
            str(self.directory / 'absent'), 'agy', 'case', str(int(DIGITS) + 1)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (78, b'', b''))

    def test_loaded_python_startup_customizers_keep_reference_before_artifact_probe(self):
        for name in ('sitecustomize', 'usercustomize'):
            with self.subTest(name=name), patch.dict(sys.modules, {name: object()}), \
                    patch('support.native_launcher_install.artifact_plan') as plan:
                self.assertIsNone(trace._native_export_command(self.args))
                plan.assert_not_called()

    def test_selected_errors_never_replay_or_accept_dirty_decline(self):
        for code, out, err in ((1, b'', b'failure'), (78, b'private', b''), (78, b'', b'failure')):
            with self.subTest(code=code, out=out, err=err), \
                    patch.object(trace, '_native_export_command', return_value=['selected']), \
                    patch.object(trace.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, out, err)):
                with self.assertRaises(ValueError):
                    trace._native_export(self.args)


if __name__ == '__main__':
    unittest.main()
