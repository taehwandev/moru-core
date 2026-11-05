"""Actual callback parity for literal search and Git read-query ingress."""
import tempfile
import unittest
from pathlib import Path

from native_pretool_support import invoke, prepare, request, result


class NativeQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-query-forms-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare(self.base)
        (self.project / "notes.txt").write_text("synthetic\n")
        (self.project / "src").mkdir()
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def check_native(self, command):
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            payload = request(self.project, command)
            expected = invoke(self.launcher, self.base, self.project, alias, payload, backend="python")
            self.assertEqual((0, b"", b""), result(expected), command)
            actual = invoke(self.launcher, self.base, self.project, alias, payload, PATH=str(self.empty))
            self.assertEqual(result(expected), result(actual), command)

    def check_fallback(self, command):
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            payload = request(self.project, command)
            expected = invoke(self.launcher, self.base, self.project, alias, payload, backend="python")
            actual = invoke(self.launcher, self.base, self.project, alias, payload)
            self.assertEqual(result(expected), result(actual), command)
            self.assertEqual(127, invoke(self.launcher, self.base, self.project, alias,
                payload, PATH=str(self.empty)).returncode, command)

    def test_rg_regex_and_glob_forms_need_no_python(self):
        for command in ("rg -n 'foo|bar' notes.txt", "rg -n '^def [a-z_]+' notes.txt",
                        "rg --files -g '*.py' src", "rg --files --glob='*.rs' src",
                        "rg -n -g '*.py' 'def |class ' src", "rg -n 'foo|bar' src --glob '*.rs'",
                        "rg -n 'foo|bar' -- src"):
            with self.subTest(command=command):
                self.check_native(command)

    def test_rg_unsafe_neighbors_keep_canonical_python(self):
        for command in ("rg -n foo|touch written", "rg -n 'foo'bar notes.txt",
                        "rg -n \"$PATTERN\" notes.txt", "rg -n foo notes.txt --pre=evil",
                        "rg --files -g --pre=evil", "rg --files --glob='--pre=evil'",
                        "rg -n '`touch written`' notes.txt", "rg -n foo notes.txt > written",
                        "rg --files -g '*.py' && touch written", "rg --files --hidden",
                        "rg -n foo ../notes.txt"):
            with self.subTest(command=command):
                self.check_fallback(command)
        self.assertFalse((self.project / "written").exists())

    def test_git_literal_paths_formats_and_revisions_need_no_python(self):
        quoted = self.project / "한글 폴더"
        quoted.mkdir()
        for command in (f"git -C '{quoted}' status --short",
                        'git log -3 --format=\'%h %s\'',
                        'git log --pretty="format:%h %s" -3',
                        "git diff HEAD~1 HEAD --stat", "git diff HEAD^2 abcdef0 --numstat",
                        "git diff 123abcd abcdef0 --name-only", "git log --oneline -1000"):
            with self.subTest(command=command):
                self.check_native(command)

    def test_git_unsafe_neighbors_keep_canonical_python(self):
        for command in ("git log --format='%h' --output=written",
                        "git log --pretty=oneline --exec=evil", "git log -0 --oneline",
                        "git log -1001 --oneline", "git log -3 -4 --oneline",
                        "git log --format='%h' --pretty=oneline",
                        "git log --format=\"$(touch written)\"",
                        "git log --format='%h'word", "git diff HEAD~1001 HEAD --stat",
                        "git diff HEAD~0 HEAD --stat", "git diff branch HEAD --stat",
                        "git diff HEAD~1 HEAD --ext-diff", "git -C '$HOME' status --short",
                        "git -c core.pager=evil log --oneline", "git status '--short'",
                        "git diff HEAD~1 HEAD --stat > written"):
            with self.subTest(command=command):
                self.check_fallback(command)
        self.assertFalse((self.project / "written").exists())


if __name__ == "__main__":
    unittest.main()
