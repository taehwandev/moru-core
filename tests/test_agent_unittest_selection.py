"""Real named selections feed the existing observed-result ledger."""
import json
import unittest
from pathlib import Path
import contextlib
import io
import sys
from unittest.mock import patch

import test_agent_verification_hook as fixtures
from agent_unittest_selection import UnittestSelection


class NamedTests(unittest.TestCase):
    setUp = fixtures.VerificationHookTests.setUp
    run_hook = fixtures.VerificationHookTests.run_hook
    entries = fixtures.VerificationHookTests.entries

    def test_cli_rejects_selectors_outside_verification(self):
        from test_agent_hook_checkpoint import agent_hook
        with patch.object(sys, 'argv', ['agent-hook.py', 'verify', '--test-selector', 'test_a', '--test-selector', 'test_b.Case']):
            args = agent_hook._parse_args(agent_hook.build_parser())
        self.assertEqual(['test_a', 'test_b.Case'], args.test_selector)
        with patch.object(sys, 'argv', ['agent-hook.py', 'gate-batch', '--test-selector', 'test_case']), \
                contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
            agent_hook._parse_args(agent_hook.build_parser())
        self.assertEqual(2, error.exception.code)
        self.assertIn('--test-selector is only valid for verify', stderr.getvalue())

    def write(self, name, body):
        (self.project / 'tests' / (name + '.py')).write_text(
            'import unittest\nclass Case(unittest.TestCase):\n' + body)

    def test_multiple_modules_and_method_selections_record_exact_unique_count(self):
        self.write('test_a', '    def test_one(self): self.assertTrue(True)\n    def test_two(self): self.assertTrue(True)\n')
        self.write('test_b', '    def test_one(self): self.assertTrue(True)\n')
        self.args.test_selector = ['test_a', 'test_a.Case.test_one', 'test_b.Case.test_one']
        self.assertEqual(0, self.run_hook())
        entry = self.entries()[-1]
        self.assertEqual('SUCCESS', entry['status'])
        self.assertIn('tests=3', entry['fields']['result'])
        self.assertIn('@selectors:', entry['fields']['check'])
        self.assertIn('reuse_snapshot', entry)

    def test_unselected_module_is_not_imported(self):
        self.write('test_ok', '    def test_ok(self): self.assertTrue(True)\n')
        marker = self.project / '.moru' / 'not-selected'
        (self.project / 'tests' / 'test_other.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.args.test_selector = ['test_ok.Case']
        self.assertEqual(0, self.run_hook())
        self.assertFalse(marker.exists())

    def test_fail_missing_method_and_skip_only_never_pass(self):
        for name, body, selector in (
                ('test_fail', '    def test_bad(self): self.fail("actual failure")\n', 'test_fail'),
                ('test_missing', '    def test_ok(self): pass\n', 'test_missing.Case.absent'),
                ('test_skip', '    @unittest.skip("unavailable")\n    def test_skip(self): pass\n', 'test_skip')):
            with self.subTest(selector=selector):
                self.write(name, body)
                self.args.test_selector = [selector]
                self.assertEqual(1, self.run_hook())
                self.assertEqual('FAIL', self.entries()[-1]['status'])

    def test_external_names_symlink_escape_and_mixed_pattern_are_rejected(self):
        self.write('test_ok', '    def test_ok(self): pass\n')
        directory = self.project / 'tests'
        for names in (['os.system'], ['../test_ok'], ['test_ok;whoami'], []):
            with self.subTest(names=names), self.assertRaises(ValueError):
                UnittestSelection.encode(directory, names)
        outside = self.project / 'outside.py'
        outside.write_text('raise AssertionError("must not import")\n')
        (directory / 'test_link.py').symlink_to(outside)
        with self.assertRaises(ValueError):
            UnittestSelection.encode(directory, ['test_link'])
        self.args.test_selector, self.args.test_pattern = ['test_ok'], 'test_ok.py'
        self.assertEqual(1, self.run_hook())

    def test_escaping_package_initializer_and_preloaded_module_are_rejected(self):
        directory = self.project / 'tests'
        package = directory / 'pkg'
        package.mkdir()
        (package / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self): pass\n')
        outside = self.project / 'outside_initializer.py'
        outside.write_text('raise AssertionError("initializer must not execute")\n')
        (package / '__init__.py').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'initializer escapes'):
            UnittestSelection.encode(directory, ['pkg.test_case'])
        (directory / 'json.py').write_text('raise AssertionError("cached module collision")\n')
        self.args.test_selector = ['json']
        self.assertEqual(1, self.run_hook())
        (directory / 'pkg.py').write_text('raise AssertionError("ambiguous module")\n')
        with self.assertRaisesRegex(ValueError, 'initializer escapes'):
            UnittestSelection.encode(directory, ['pkg'])
        (package / '__init__.py').unlink()
        (package / '__init__.py').write_text('raise AssertionError("ambiguous package")\n')
        with self.assertRaisesRegex(ValueError, 'ambiguous module and package'):
            UnittestSelection.encode(directory, ['pkg'])

    def test_every_namespace_prefix_rejects_sibling_module_extension_and_bytecode(self):
        from importlib.machinery import EXTENSION_SUFFIXES
        directory = self.project / 'tests'
        package = directory / 'ns'
        package.mkdir()
        (package / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self): pass\n')
        self.args.test_selector = ['ns.test_case']
        self.assertEqual(0, self.run_hook())
        marker = self.project / '.moru' / 'ambient-import'
        (self.project / 'ns.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.assertEqual(0, self.run_hook())
        self.assertFalse(marker.exists())
        with self.assertRaises(ValueError):
            UnittestSelection.encode(directory, ['NS.test_case'])
        outside = self.project / 'outside.py'
        outside.write_text('raise AssertionError("ancestor must not execute")\n')
        sibling = directory / 'ns.py'
        sibling.symlink_to(outside)
        with self.assertRaises(ValueError):
            UnittestSelection.encode(directory, ['ns.test_case'])
        sibling.unlink()
        for path in (directory / ('ns' + EXTENSION_SUFFIXES[0]), package / '__init__.pyc'):
            path.write_bytes(b'not executable')
            with self.assertRaisesRegex(ValueError, 'unambiguous Python source'):
                UnittestSelection.encode(directory, ['ns.test_case'])
            path.unlink()

    def test_nested_and_mixed_namespace_packages_load_selected_tests(self):
        directory = self.project / 'tests'
        for name in ('outer.inner.test_case', 'regular.inner.test_case'):
            parent = directory.joinpath(*name.split('.')[:-1])
            parent.mkdir(parents=True, exist_ok=True)
            if name.startswith('regular'):
                (directory / 'regular' / '__init__.py').write_text('')
            (parent / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self): pass\n')
            self.args.test_selector = [name]
            self.assertEqual(0, self.run_hook())


if __name__ == '__main__':
    unittest.main()
