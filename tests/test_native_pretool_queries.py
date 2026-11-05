"""Actual callback parity for literal search and Git read-query ingress."""
import json
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

    def check_native(self, command, **fields):
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            payload = request(self.project, command, **fields)
            expected = invoke(self.launcher, self.base, self.project, alias, payload, backend="python")
            self.assertEqual((0, b"", b""), result(expected), command)
            actual = invoke(self.launcher, self.base, self.project, alias, payload, PATH=str(self.empty))
            self.assertEqual(result(expected), result(actual), command)

    def check_fallback(self, command, **fields):
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            payload = request(self.project, command, **fields)
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

    def test_absolute_cd_queries_resolve_files_at_the_named_directory(self):
        target = self.project / "target && 한글"
        target.mkdir()
        (target / "only-there.txt").write_text("synthetic\n")
        for query in ("cat only-there.txt", "rg -n 'one|two' only-there.txt", "pwd",
                      "git status --short", "ls -la"):
            with self.subTest(query=query):
                self.check_native(f"cd '{target}' && {query}")
        self.check_native(f"cd\t'{target}'&&cat only-there.txt")

    def test_read_output_pipes_and_combined_scope_need_no_python(self):
        for query in ("rg -n 'one|two' notes.txt", "git log -3 --format='%h %s'",
                      "git diff HEAD~1 HEAD --stat", "cat notes.txt"):
            for suffix in ("head -n 20", "tail -n 0", "wc -l"):
                with self.subTest(query=query, suffix=suffix):
                    self.check_native(f"{query} | {suffix}")
        self.check_native(f"cd '{self.project}' && rg -n 'one && two|three' notes.txt | head -n 1000000")
        self.check_native("cat notes.txt|wc")

    def test_scope_and_pipe_unsafe_neighbors_keep_canonical_python(self):
        prefix = f"cd '{self.project}'"
        for command in ("cd src && cat notes.txt", "cd - && pwd", f"{prefix}; pwd",
                        f"{prefix} && {prefix} && pwd", f"{prefix} && touch written",
                        f"{prefix} && cat notes.txt > written", "cd /moru-missing-directory-8231 && pwd",
                        f"CDPATH=/tmp {prefix} && pwd", f"cd -- '{self.project}' && pwd",
                        "cat notes.txt || head -n 20", "cat notes.txt |& head -n 20",
                        "cat notes.txt | head -n -1", "cat notes.txt | head -n 1000001",
                        "cat notes.txt | tail -f", "cat notes.txt | wc --files0-from=notes.txt",
                        "cat notes.txt | head -n 20 notes.txt", "cat notes.txt | head -n 20 > written",
                        "cat notes.txt | head -n 20 | wc -l", "touch written | head -n 1",
                        "cat notes.txt | head -n 20 && touch written", "cat notes.txt | awk '{print}'"):
            with self.subTest(command=command):
                self.check_fallback(command)
        self.assertFalse((self.project / "written").exists())

    def test_scoped_producer_and_pipe_consumer_shadows_keep_python(self):
        target = self.project / "target"
        target.mkdir()
        (target / "note.txt").write_text("synthetic\n")
        for directory, executable, command in (
                (target, "cat", f"cd '{target}' && cat note.txt"),
                (target, "head", f"cd '{target}' && cat note.txt | head -n 1"),
                (self.project, "head", f"cd '{target}' && cat note.txt | head -n 1"),
                (target, "git", f"cd '{target}' && git status --short")):
            shadow = directory / executable
            shadow.write_text("synthetic shadow\n")
            try:
                self.check_fallback(command)
            finally:
                shadow.unlink()

    def test_absolute_scope_preserves_codex_transcript_failure_boundary(self):
        target = self.project / "scope"
        target.mkdir()
        (target / "only-there.txt").write_text("synthetic\n")
        command = f"cd '{target}' && cat only-there.txt | head -n 2"
        transcript = self.base / "synthetic.jsonl"
        record = {"type": "function_call", "arguments": json.dumps({"cmd": command, "workdir": str(self.project)})}
        transcript.write_text(json.dumps({"payload": record}) + "\n")
        self.check_native(command, transcript_path=str(transcript))
        record["arguments"] = "not-json"
        transcript.write_text(json.dumps({"payload": record}) + "\n")
        payload = request(self.project, command, transcript_path=str(transcript))
        alias = "codex-pretool-gate"
        self.assertEqual(result(invoke(self.launcher, self.base, self.project, alias, payload, backend="python")),
                         result(invoke(self.launcher, self.base, self.project, alias, payload)))
        self.assertEqual(127, invoke(self.launcher, self.base, self.project, alias, payload,
                                   PATH=str(self.empty)).returncode)

    def test_codex_pipe_consumers_use_transcript_workdir_for_shadow_checks(self):
        target = self.project / "transcript-target"
        target.mkdir()
        (target / "notes.txt").write_text("synthetic\n")
        transcript = self.base / "synthetic.jsonl"
        for command in ("cat notes.txt | head -n 2", "git status --short | head -n 2"):
            record = {"type": "function_call", "arguments": json.dumps({"cmd": command, "workdir": str(target)})}
            transcript.write_text(json.dumps({"payload": record}) + "\n")
            self.check_native(command, transcript_path=str(transcript))
            shadow = target / "head"
            shadow.write_text("synthetic shadow\n")
            try:
                alias = "codex-pretool-gate"
                payload = request(self.project, command, transcript_path=str(transcript))
                self.assertEqual(result(invoke(self.launcher, self.base, self.project, alias, payload, backend="python")),
                                 result(invoke(self.launcher, self.base, self.project, alias, payload)))
                self.assertEqual(127, invoke(self.launcher, self.base, self.project, alias, payload,
                                           PATH=str(self.empty)).returncode)
            finally:
                shadow.unlink()


if __name__ == "__main__":
    unittest.main()
