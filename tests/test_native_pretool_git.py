"""Closed Git inspection queries preserve Python policy and ambiguous contexts."""
import json
from pathlib import Path
import tempfile
import unittest

from native_pretool_support import invoke, prepare, request, result


class NativeGitQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-git-query-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def run_query(self, alias, command, **kwargs):
        return invoke(self.launcher, self.base, self.project, alias, request(self.project, command), **kwargs)

    def test_supported_inspection_forms_are_native_and_match_python(self):
        commands = ["git ls-files", "git ls-files --cached", "git ls-files --stage",
                    "git status --short --branch", "git status --branch --porcelain=v1", "git remote -v",
                    "git ls-files --others --exclude-standard", "git log --oneline",
                    "git log -1 --oneline", "git log --oneline -1000", "git show --stat",
                    "git show --name-only", "git show --stat abcdef0", "git show --name-only " + "a" * 64,
                    "git tag --list", "git tag --list --sort=-version:refname",
                    "git diff --name-status", "git diff --cached --name-status"]
        target = self.base / "ascii-target"
        target.mkdir()
        commands += ["git -C " + str(target) + " log -5 --oneline",
                     "git -C " + str(target) + " ls-files"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    reference = self.run_query(alias, command, backend="python")
                    self.assertEqual((0, b"", b""), result(reference))
                    self.assertEqual(result(reference), result(self.run_query(alias, command)))
                    self.assertEqual(result(reference), result(self.run_query(alias, command, PATH=str(self.empty))))

    def test_plain_cached_and_path_limited_diffs_are_native_and_match_python(self):
        commands=["git diff","git diff --cached","git diff --cached --exit-code",
            "git diff -- README.md","git diff --cached -- README.md src/lib.rs",
            "git diff --cached --stat -- .","git diff --name-status -- '소스 폴더/파일.rs'",
            "git diff --cached -- README.md | head -n 10",
            "git -C '"+str(self.project)+"' diff --cached -- README.md"]
        for option in ("--stat","--check","--name-only","--name-status","--numstat","--exit-code"):
            commands.extend(("git diff "+option+" -- README.md","git diff --cached "+option+" -- src"))
        for alias in ("claude-pretool-gate","codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias,command=command):
                    expected=result(self.run_query(alias,command,backend="python"))
                    self.assertEqual((0,b"",b""),expected)
                    self.assertEqual(expected,result(self.run_query(alias,command,PATH=str(self.empty))))

    def test_diff_unsafe_flags_pathspecs_and_shell_neighbors_replay_python(self):
        commands=["git diff --output=written","git diff --out=written","git diff --ext-dif",
            "git diff --textconv -- README.md","git diff -- --output=written",
            "git diff --cached --cached","git diff --", "git diff -- ../README.md",
            "git diff -- ':(top,literal)README.md'","git diff -- '*.rs'","git diff -- 'a|b.rs'",
            "git diff --cached -- README.md > written","git diff -- README.md; touch written",
            "git diff -- README.md && touch written","git diff -- README.md # note",
            "git diff -- \"$FILE\"","git diff -- README.md\n","git diff -- README.md | cat"]
        for alias in ("claude-pretool-gate","codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias,command=command):
                    self.assertEqual(127,self.run_query(alias,command,PATH=str(self.empty)).returncode)
                    self.assertEqual(result(self.run_query(alias,command,backend="python")),
                                     result(self.run_query(alias,command)))
        self.assertFalse((self.project/"written").exists())

    def test_diff_transcript_context_and_path_errors_match_original(self):
        command="git diff --cached -- README.md"
        transcript=self.base/"synthetic-diff.jsonl"
        transcript.write_text(json.dumps({"payload":{"type":"function_call","arguments":
            json.dumps({"cmd":command,"workdir":str(self.project)})}})+"\n")
        payload=request(self.project,command,transcript_path=str(transcript))
        self.assertEqual((0,b"",b""),result(invoke(self.launcher,self.base,self.project,
            "codex-pretool-gate",payload,PATH=str(self.empty))))
        transcript.write_text(json.dumps({"payload":{"type":"custom_tool_call","input":
            'await tools.exec_command({cmd:"git diff --cached -- README.md",workdir:"/'+"x"*300+'"})'}})+"\n")
        expected=invoke(self.launcher,self.base,self.project,"codex-pretool-gate",payload,backend="python")
        self.assertEqual(result(expected),result(invoke(self.launcher,self.base,self.project,"codex-pretool-gate",payload)))
        self.assertEqual(127,invoke(self.launcher,self.base,self.project,"codex-pretool-gate",payload,PATH=str(self.empty)).returncode)
        loop=self.project/"loop.rs"; loop.symlink_to("loop.rs")
        for alias in ("claude-pretool-gate","codex-pretool-gate"):
            self.assertEqual(result(self.run_query(alias,"git diff -- loop.rs",backend="python")),
                             result(self.run_query(alias,"git diff -- loop.rs")))

    def test_unsafe_and_unsupported_neighbors_replay_the_real_policy(self):
        commands = ["git log -0 --oneline", "git log -1001 --oneline", "git log -4294967296 --oneline",
                    "git remote -v add origin nowhere", "git remote update",
                    "git status --short --branch --ignored",
                    "git show --stat main", "git show --stat " + "a" * 65,
                    "git tag", "git tag --list --delete main", "git ls-files --error-unmatch missing"]
        for base in ("git log -5 --oneline", "git show --stat", "git ls-files", "git tag --list"):
            commands.extend(base + tail for tail in (" --output=written", " --out=written", " --ext-diff",
                " --textconv", " --exec=touch", " > written", "; touch written", " | cat", "\n"))
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    self.assertEqual(127, self.run_query(alias, command, PATH=str(self.empty)).returncode)
                    self.assertEqual(result(self.run_query(alias, command, backend="python")),
                                     result(self.run_query(alias, command)))
        self.assertFalse((self.project / "written").exists())

    def test_local_git_entries_in_either_context_require_python(self):
        for kind in ("file", "launcher", "loop"):
            path = self.project / "git"
            if kind == "file": path.write_text("synthetic")
            else: path.symlink_to(self.launcher if kind == "launcher" else "git")
            try:
                for alias in ("claude-pretool-gate", "codex-pretool-gate"):
                    for command in ("git log -5 --oneline", "git status --short", "git diff", "git diff --cached -- README.md"):
                        self.assertEqual(127, self.run_query(alias, command, PATH=str(self.empty)).returncode)
                        self.assertEqual(result(self.run_query(alias, command, backend="python")),
                                         result(self.run_query(alias, command)))
            finally: path.unlink()

    def test_codex_transcript_context_keeps_native_and_error_replay(self):
        transcript = self.base / "synthetic.jsonl"
        command = "git log -5 --oneline"
        transcript.write_text(json.dumps({"payload": {"type": "function_call", "arguments":
            json.dumps({"cmd": command, "workdir": str(self.project)})}}) + "\n")
        payload = request(self.project, command, transcript_path=str(transcript))
        done = invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload, PATH=str(self.empty))
        self.assertEqual((0, b"", b""), result(done))
        transcript.write_text(json.dumps({"payload": {"type": "custom_tool_call", "input":
            'await tools.exec_command({cmd:"git log -5 --oneline",workdir:"/' + "x" * 300 + '"})'}}) + "\n")
        reference = invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload, backend="python")
        self.assertEqual(result(reference), result(invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload)))
        self.assertEqual(127, invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload,
                                    PATH=str(self.empty)).returncode)

    def test_nonoption_symlink_errors_keep_python_diagnostics(self):
        for name, command in (("abcdef0", "git show --stat abcdef0"), ("log", "git log -5 --oneline")):
            path = self.project / name
            path.symlink_to(name)
            try:
                for alias in ("claude-pretool-gate", "codex-pretool-gate"):
                    self.assertEqual(result(self.run_query(alias, command, backend="python")),
                                     result(self.run_query(alias, command)))
            finally: path.unlink()

    def test_git_alias_in_different_process_or_payload_cwd_requires_python(self):
        other = self.base / "different-cwd"
        other.mkdir()
        for directory in (self.project, other):
            link = directory / "git"
            link.symlink_to(self.launcher)
            try:
                for alias in ("claude-pretool-gate", "codex-pretool-gate"):
                    payload = request(other, "git log -5 --oneline")
                    expected = invoke(self.launcher, self.base, self.project, alias, payload, backend="python")
                    self.assertEqual(result(expected), result(invoke(self.launcher, self.base, self.project, alias, payload)))
                    self.assertEqual(127, invoke(self.launcher, self.base, self.project, alias, payload,
                                                PATH=str(self.empty)).returncode)
            finally: link.unlink()
