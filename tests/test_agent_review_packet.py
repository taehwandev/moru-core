"""Tests for scripts/agent_review_packet.py using a real temporary Git repository."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agent_review_packet import ReviewPacket, _main  # noqa: E402

SECRET = "supersecretvalue"
DATE = "2000-01-01T00:00:00+0000"
GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_AUTHOR_DATE": DATE,
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_COMMITTER_DATE": DATE,
}
APP = '''from pathlib import Path

Path(__file__).with_name("EXECUTED").write_text("ran")


def helper(value):
    return value + 1


def unrelated():
    return "untouched"


class Service:
    def scale(self, value):
        return value * 2

    def run(self, value):
        return helper(value)

    def idle(self):
        return "idle"
'''
FIXTURE = 'class Fixture:\n    name = "fixture-marker"\n\n    def make(self):\n        return self.name\n'
CONTEXTS = ["fixtures.py:Fixture", "fixtures.py:Missing", "app.py:unrelated"]
CHECKS = [{"check": "unit tests", "result": "passed"}]


def git(root, *args):
    done = subprocess.run(["git", *args], cwd=root, env=GIT_ENV, check=True, capture_output=True, text=True)
    return done.stdout.strip()


class ReviewPacketTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text(f"TOKEN = '{SECRET}'\n", encoding="utf-8")
        git(self.root, "init", "-q")
        self.write("app.py", APP)
        self.write("fixtures.py", FIXTURE)
        self.write("notes.txt", "first\n")
        self.write("big.py", "def big():\n    return 0\n")
        self.write(".gitignore", ".env\nignored.txt\n")
        git(self.root, "add", "app.py", "fixtures.py", "notes.txt", "big.py", ".gitignore")
        git(self.root, "commit", "-q", "-m", "base")
        self.write(".env", f"TOKEN={SECRET}\n")
        self.write("ignored.txt", SECRET)
        self.write("untracked.py", f"X = '{SECRET}'\n")
        os.symlink(self.root / "app.py", self.root / "link.py")
        os.symlink(outside, self.root / "out")
        self.write("app.py", APP.replace("return helper(value)", "return self.scale(helper(value))"))
        self.write("notes.txt", "first\nsecond\n")

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8")

    def test_changed_method_with_called_helpers_and_text_diff(self):
        packet = ReviewPacket.build(self.root, ["app.py", "notes.txt"])
        found = {(item["symbol"], item["role"]) for item in packet["definitions"]}
        self.assertEqual(found, {("Service.run", "changed"), ("Service.scale", "helper"), ("helper", "helper")})
        run = next(item for item in packet["definitions"] if item["symbol"] == "Service.run")
        source = (self.root / "app.py").read_text(encoding="utf-8").split("\n")
        self.assertEqual(run["path"], "app.py")
        self.assertEqual(run["lines"], source[run["start_line"] - 1:run["end_line"]])
        self.assertEqual([item["path"] for item in packet["diffs"]], ["app.py", "notes.txt"])
        self.assertIn("+second", packet["diffs"][1]["lines"])
        self.assertIn({"kind": "definition", "path": "notes.txt", "reason": "unsupported_language"}, packet["omissions"])
        self.assertEqual(packet["head"], git(self.root, "rev-parse", "HEAD"))
        entry = packet["files"][0]
        self.assertEqual(entry["status"], "modified")
        self.assertEqual(entry["sha256"], hashlib.sha256((self.root / "app.py").read_bytes()).hexdigest())
        self.assertTrue(packet["context_only"] and packet["no_execution"])

    def test_source_sentinel_is_never_executed(self):
        ReviewPacket.render(ReviewPacket.build(self.root, ["app.py"], contexts=["app.py:helper"]))
        self.assertFalse((self.root / "EXECUTED").exists())

    def test_changed_duplicate_setter_reports_unindexed_context(self):
        before = 'class C:\n    @property\n    def x(self):\n        return 1\n    @x.setter\n    def x(self, value):\n        self.value = value\n'
        self.write('setter.py', before)
        git(self.root, 'add', 'setter.py')
        git(self.root, 'commit', '-qm', 'setter base')
        self.write('setter.py', before.replace('self.value = value', 'self.value = int(value)'))
        packet = ReviewPacket.build(self.root, ['setter.py'])
        self.assertIn({'kind': 'definition', 'path': 'setter.py', 'reason': 'outside_indexed_definition'}, packet['omissions'])
        self.assertTrue(packet['diffs'])

    def test_large_line_count_has_an_explicit_budget_omission(self):
        self.write('big.py', 'x = 1\n' * 5000)
        packet = ReviewPacket.build(self.root, ['big.py'])
        self.assertIn({'kind': 'source', 'path': 'big.py', 'reason': 'source_line_budget'}, packet['omissions'])
        self.assertEqual([], packet['definitions'])

    def test_section_count_is_bounded_with_explicit_omissions(self):
        self.write('big.py', ''.join(f'def item{i}():\n    return {i}\n\n' for i in range(150)))
        packet = ReviewPacket.build(self.root, ['big.py'], contexts=['fixtures.py:Fixture'], max_bytes=500000)
        self.assertLessEqual(len(packet['definitions']) + len(packet['diffs']), 128)
        self.assertTrue(any(item['reason'] == 'section_count_budget' for item in packet['omissions']))
        self.assertEqual(['Fixture'], [item['symbol'] for item in packet['contexts']])

    def test_explicit_class_context_and_missing_symbol(self):
        packet = ReviewPacket.build(self.root, ["app.py"], contexts=CONTEXTS)
        found = {item["symbol"]: item for item in packet["contexts"]}
        self.assertEqual(set(found), {"Fixture", "unrelated"})
        self.assertIn('    name = "fixture-marker"', found["Fixture"]["lines"])
        self.assertEqual((found["Fixture"]["start_line"], found["Fixture"]["end_line"]), (1, 5))
        missing = {"kind": "context", "path": "fixtures.py", "reason": "symbol_not_found", "symbol": "Missing"}
        self.assertIn(missing, packet["omissions"])
        roles = [(item["path"], item["role"]) for item in packet["files"]]
        self.assertEqual(roles, [("app.py", "selected"), ("fixtures.py", "context")])

    def test_same_inputs_give_identical_bytes(self):
        first = ReviewPacket.build(self.root, ["app.py", "notes.txt"], contexts=CONTEXTS, checks=CHECKS)
        second = ReviewPacket.build(self.root, ["app.py", "notes.txt"], contexts=CONTEXTS, checks=CHECKS)
        text = ReviewPacket.render(first)
        self.assertEqual(text.encode("utf-8"), ReviewPacket.render(second).encode("utf-8"))
        self.assertEqual(first["packet_sha256"], second["packet_sha256"])
        self.assertEqual(json.loads(text), first)
        self.assertNotIn(str(self.base), text)
        self.assertEqual(first["checks"]["items"], CHECKS)
        self.assertIn("not_executed", first["checks"]["provenance"])

    def test_unsafe_paths_are_rejected_without_content_leak(self):
        unsafe = (".env", "ignored.txt", "link.py", "out/secret.py", "../outside/secret.py", str(self.root / "app.py"),
                  ".git/config", "untracked.py", "sub/../app.py")
        for bad in unsafe:
            with self.subTest(path=bad):
                with self.assertRaises(ValueError) as caught:
                    ReviewPacket.build(self.root, [bad])
                self.assertNotIn(SECRET, str(caught.exception))
        for bad in (".env:Token", "app.py", "out/secret.py:TOKEN"):
            with self.subTest(context=bad):
                with self.assertRaises(ValueError) as caught:
                    ReviewPacket.build(self.root, ["app.py"], contexts=[bad])
                self.assertNotIn(SECRET, str(caught.exception))

    def test_staged_new_file_is_supported(self):
        self.write("new.py", "def fresh():\n    return 'new-marker'\n")
        git(self.root, "add", "new.py")
        packet = ReviewPacket.build(self.root, ["new.py"])
        self.assertEqual(packet["files"][0]["status"], "added")
        self.assertIsNone(packet["files"][0]["head_sha256"])
        self.assertEqual([], packet['definitions'])
        self.assertTrue(any(item.get('symbol') == 'fresh' and item['reason'] == 'covered_by_diff' for item in packet['omissions']))
        self.assertIn("+def fresh():", packet["diffs"][0]["lines"])

    def test_deleted_tracked_file_and_global_ignores(self):
        git(self.root, 'rm', '-qf', 'notes.txt')
        self.assertEqual('deleted', ReviewPacket.build(self.root, ['notes.txt'])['files'][0]['status'])
        excludes = self.base / 'excludes'
        excludes.write_text('app.py\n')
        config = self.base / 'gitconfig'
        config.write_text('[core]\n excludesFile = ' + str(excludes) + '\n')
        with patch.dict('agent_review_packet._GIT_ENV', {'GIT_CONFIG_GLOBAL': str(config)}):
            with self.assertRaisesRegex(ValueError, 'ignored'):
                ReviewPacket.build(self.root, ['app.py'])

    def test_cli_does_not_overwrite_existing_output(self):
        target = self.base / 'existing.json'
        target.write_text('preserved')
        with contextlib.redirect_stderr(io.StringIO()):
            code = _main(['--project', str(self.root), '--path', 'app.py', '--output', str(target)])
        self.assertEqual(2, code)
        self.assertEqual('preserved', target.read_text())

    def test_oversize_sections_are_omitted_with_reasons(self):
        body = "".join(f"    x{number} = 'payload-marker-{number}'\n" for number in range(400))
        self.write("big.py", "def big():\n" + body + "    return 0\n")
        self.write("huge.txt", "y" * (300 * 1024))
        git(self.root, "add", "huge.txt")
        packet = ReviewPacket.build(self.root, ["big.py", "huge.txt"], max_bytes=4096)
        text = ReviewPacket.render(packet)
        self.assertLessEqual(len(text.encode("utf-8")), 4096)
        self.assertNotIn("payload-marker", text)
        self.assertEqual((packet["diffs"], packet["definitions"]), ([], []))
        reasons = {(item["kind"], item["path"], item["reason"]) for item in packet["omissions"]}
        expected = {("diff", "big.py", "exceeds_max_bytes"), ("definition", "big.py", "exceeds_max_bytes"),
                    ("source", "huge.txt", "oversize")}
        self.assertLessEqual(expected, reasons)
        with self.assertRaises(ValueError):
            ReviewPacket.build(self.root, ["big.py"], max_bytes=64)

    def test_malformed_checks_are_rejected(self):
        malformed = ("unit passed", [["unit", "passed"]], [{"check": "unit"}], [{"check": "unit", "result": ""}],
                     [{"check": "unit", "result": "ok", "verified": True}], [{"check": 1, "result": "ok"}],
                     [{"check": "unit", "result": SECRET + "\n"}])
        for bad in malformed:
            with self.subTest(checks=repr(bad)[:40]):
                with self.assertRaises(ValueError) as caught:
                    ReviewPacket.build(self.root, ["app.py"], checks=bad)
                self.assertNotIn(SECRET, str(caught.exception))

    def test_render_respects_total_size_bound(self):
        for limit in (6000, 12000, 32768):
            with self.subTest(limit=limit):
                packet = ReviewPacket.build(self.root, ["app.py", "notes.txt"], contexts=CONTEXTS, checks=CHECKS,
                                            max_bytes=limit)
                self.assertLessEqual(len(ReviewPacket.render(packet).encode("utf-8")), limit)
                self.assertEqual(packet["max_bytes"], limit)

    def test_cli_writes_only_the_explicit_output(self):
        output, bad_output, checks_file = self.base / "packet.json", self.base / "bad.json", self.base / "checks.json"
        checks_file.write_text(json.dumps(CHECKS), encoding="utf-8")
        errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            code = _main(["--project", str(self.root), "--path", "app.py", "--context", "fixtures.py:Fixture",
                          "--checks-file", str(checks_file), "--max-bytes", "8192", "--output", str(output)])
            failed = _main(["--project", str(self.root), "--path", ".env", "--output", str(bad_output)])
        expected = ReviewPacket.build(self.root, ["app.py"], contexts=["fixtures.py:Fixture"], checks=CHECKS, max_bytes=8192)
        self.assertEqual(code, 0)
        self.assertEqual(output.read_text(encoding="utf-8"), ReviewPacket.render(expected))
        self.assertEqual(failed, 2)
        self.assertFalse(bad_output.exists())
        self.assertNotIn(SECRET, errors.getvalue())


if __name__ == "__main__":
    unittest.main()
