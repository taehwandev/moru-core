"""Actual installed manifest checker parity, no-Python execution and refusal."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from native_pretool_support import PROJECT, environment, prepare, result


class NativeManifestChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-manifests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.path = self.base / "git-only"
        self.path.mkdir()
        (self.path / "git").symlink_to(shutil.which("git"))

    def call(self, alias, args=(), backend="auto", **overrides):
        return subprocess.run([str(self.entry), alias, *args], cwd=self.project,
                              env={**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides},
                              capture_output=True, timeout=40)

    def parity(self, alias, args=()):
        expected = self.call(alias, args, backend="python")
        self.assertIn(expected.returncode, (0, 1), expected.stderr)
        self.assertEqual(result(expected), result(self.call(alias, args)))
        self.assertEqual(result(expected), result(self.call(alias, args, PATH=str(self.path))))
        return expected

    def test_android_default_and_ignored_arguments_match_without_python(self):
        self.parity("check-android-skill-manifest")
        self.parity("check-android-skill-manifest", ["--ignored-by-original-entry"])

    def test_react_default_manifest_runs_without_python(self):
        self.assertEqual(0, self.parity("check-react-rn-skill-manifest").returncode)

    def test_react_validation_preserves_ordered_failures(self):
        source = PROJECT / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        original = json.loads(source.read_text())
        variants = []
        for key, value in (("schema_version", 2), ("skills", []), ("repositories", {})):
            payload = copy.deepcopy(original)
            payload[key] = value
            variants.append(payload)
        payload = copy.deepcopy(original)
        payload["skills"][0].update(path="../invalid/SKILL.md", owners=["missing-owner.md"], sha256="BAD")
        variants.append(payload)
        for index, payload in enumerate(variants):
            with self.subTest(index=index):
                path = self.base / f"manifest-{index}.json"
                path.write_text(json.dumps(payload))
                self.assertEqual(1, self.parity("check-react-rn-skill-manifest", ["--manifest", str(path)]).returncode)

    def test_react_empty_source_tree_reports_missing_skills_without_network(self):
        source = self.base / "empty-source"
        source.mkdir()
        self.assertEqual(1, self.parity("check-react-rn-skill-manifest", ["--source-root", str(source)]).returncode)

    def test_source_selection_and_python_environment_remain_authoritative(self):
        for alias in ("check-android-skill-manifest", "check-react-rn-skill-manifest"):
            done = self.call(alias, PATH=str(self.path), PYTHONVERBOSE="1")
            self.assertEqual(127, done.returncode)

    def test_exceptional_inputs_defer_before_output(self):
        malformed = self.base / "malformed.json"
        malformed.write_text("{")
        cases = (["--manifest", str(malformed)],)
        for args in cases:
            with self.subTest(args=args):
                expected = self.call("check-react-rn-skill-manifest", args, backend="python")
                self.assertEqual(result(expected), result(self.call("check-react-rn-skill-manifest", args)))
                absent = self.call("check-react-rn-skill-manifest", args, PATH=str(self.path))
                self.assertEqual(127, absent.returncode)
                self.assertEqual(b"", absent.stdout)

    def test_help_and_cli_errors_match_without_python(self):
        cases = (["--help"], ["-h"], ["--he"], ["--unknown"], ["--"],
                 ["--manifest"], ["--source-root"], ["--manifest", "--help"],
                 ["--remote-check=yes"], ["--help=yes"], ["--s"],
                 ["--unknown", "--help"], ["--help", "--unknown"],
                 ["--manifest", "--unknown"], ["-xyz"], ["a", "b"],
                 ["--remote-check", "--help"], ["-hfoo"], ["--unknown", "--manifest"],
                 ["--=x"], ["-hh"], ["-hhfoo"], ["--=x", "--help"],
                 ["--manifest", "-1\n", "--help"], ["--manifest", "-.2\n", "--help"],
                 ["--manifest", "-1\n\n", "--help"], ["-h=foo"],
                 ["--manifest", "-1e2", "--help"], ["--manifest", "-1tail", "--help"],
                 ["--manifest", "-.٢tail", "--help"], ["--help", "--=x"],
                 ["-h=h"], ["-hh=foo"])
        for width in ("40", "80", "120"):
            for args in cases:
                with self.subTest(width=width, args=args):
                    expected = self.call("check-react-rn-skill-manifest", args,
                                         backend="python", COLUMNS=width)
                    self.assertIn(expected.returncode, (0, 2))
                    actual = self.call("check-react-rn-skill-manifest", args,
                                       PATH=str(self.path), COLUMNS=width)
                    self.assertEqual(result(expected), result(actual))

    def test_manifest_option_abbreviations_and_equals(self):
        source = PROJECT / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        for args in (["--manifest=" + str(source)], ["--m", str(source)],
                     ["--manifest", str(source), "--manifest", str(source)]):
            with self.subTest(args=args):
                self.assertEqual(0, self.parity("check-react-rn-skill-manifest", args).returncode)

    def test_unicode_cli_errors_and_numeric_values_match_without_python(self):
        values = ("한글", "😀", "x'한글", "x\"한글'", "\u00a0", "\u200b", "\ue000", "\U000f0000",
                  "\u2028", "\u0085", "\u0378", "\U0001fae0")
        cases = [["--remote-check=" + value] for value in values]
        cases += [["--manifest", value, "--help"] for value in
                  ("-١", "-１２", "-.٢", "-𐒠", "-١\n", "-²", "-한글")]
        for args in cases:
            with self.subTest(args=args):
                expected = self.call("check-react-rn-skill-manifest", args, backend="python")
                self.assertIn(expected.returncode, (0, 2))
                actual = self.call("check-react-rn-skill-manifest", args, PATH=str(self.path))
                self.assertEqual(result(expected), result(actual))

    def test_nested_unicode_manifest_values_match_without_python(self):
        source = PROJECT / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        original = json.loads(source.read_text())
        for index, value in enumerate((["한글", "😀", "\u200b", "\ue000"],
                                       {"이름'": ["\"값", "\u00a0", "\U000f0000"]})):
            payload = copy.deepcopy(original)
            payload["skills"][0]["path"] = value
            path = self.base / f"unicode-{index}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False))
            self.assertEqual(1, self.parity("check-react-rn-skill-manifest", ["--manifest", str(path)]).returncode)

    def test_json_numbers_and_duplicate_key_order_match_without_python(self):
        source = PROJECT / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        payload = json.loads(source.read_text())
        payload["skills"][0]["path"] = "NUMERIC_SENTINEL"
        template = json.dumps(payload)
        values = ("-0", "-0.0", str(2 ** 128), str(-(2 ** 200)), "9" * 1000,
                  "NaN", "Infinity", "-Infinity", "1e400", "-1e400", "1e-400",
                  "[-0, -0.0, NaN, Infinity, 18446744073709551616]",
                  '{"z":1,"a":2,"z":18446744073709551616}')
        for index, value in enumerate(values):
            with self.subTest(value=value[:80]):
                path = self.base / f"number-{index}.json"
                path.write_text(template.replace('"NUMERIC_SENTINEL"', value))
                self.assertEqual(1, self.parity("check-react-rn-skill-manifest", ["--manifest", str(path)]).returncode)

    def test_invalid_syntax_and_lone_surrogate_preserve_reference_fallback(self):
        for index, value in enumerate(("01", "+1", "1.", "1e", "-NaN", "+Infinity",
                                        "[1,]", '{"a":1,}', '"\\ud800"')):
            with self.subTest(value=value):
                path = self.base / f"bad-number-{index}.json"
                path.write_text('{"schema_version":' + value + '}')
                args = ["--manifest", str(path)]
                expected = self.call("check-react-rn-skill-manifest", args, backend="python")
                self.assertEqual(result(expected), result(self.call("check-react-rn-skill-manifest", args)))
                native = self.call("check-react-rn-skill-manifest", args, PATH=str(self.path))
                self.assertEqual(127, native.returncode)
                self.assertEqual(b"", native.stdout)

    def test_numeric_truthiness_preserves_installable_counts(self):
        source = PROJECT / "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        payload = json.loads(source.read_text())
        payload["skills"][0]["installable"] = "NUMERIC_SENTINEL"
        template = json.dumps(payload)
        for index, value in enumerate(("-0", "-0.0", "NaN", "Infinity", "18446744073709551616")):
            with self.subTest(value=value):
                path = self.base / f"truth-{index}.json"
                path.write_text(template.replace('"NUMERIC_SENTINEL"', value))
                self.parity("check-react-rn-skill-manifest", ["--manifest", str(path)])

    def test_explicit_remote_check_uses_only_a_fake_git(self):
        fake = self.path / "git"
        fake.unlink()
        fake.write_text("#!/bin/sh\nprintf 'called\\n' >> \"$FAKE_GIT_LOG\"\nprintf '%s\\tHEAD\\n' 1111111111111111111111111111111111111111\n")
        fake.chmod(0o755)
        # Remote checks decline before effects. Verify one reference execution,
        # with fake Git only, and no effects at all when Python is unavailable.
        import os
        log = self.base / "git-calls"
        overrides = dict(PATH=str(self.path) + os.pathsep + os.environ.get("PATH", ""),
                         FAKE_GIT_LOG=str(log))
        expected = self.call("check-react-rn-skill-manifest", ["--remote-check"], backend="python",
                             **overrides)
        reference_calls = log.read_bytes()
        self.assertTrue(reference_calls)
        log.write_bytes(b"")
        actual = self.call("check-react-rn-skill-manifest", ["--remote-check"], **overrides)
        self.assertIn(expected.returncode, (0, 1), expected.stderr)
        self.assertEqual(result(expected), result(actual))
        self.assertEqual(reference_calls, log.read_bytes())
        log.write_bytes(b"")
        absent = self.call("check-react-rn-skill-manifest", ["--remote-check"],
                           PATH=str(self.path), FAKE_GIT_LOG=str(log))
        self.assertEqual(127, absent.returncode)
        self.assertEqual(b"", log.read_bytes())


if __name__ == "__main__":
    unittest.main()
