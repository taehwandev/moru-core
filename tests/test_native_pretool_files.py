"""File-query eligibility, real policy parity and adversarial fallback proof."""
import json
from pathlib import Path
import tempfile
import unittest

from native_pretool_support import invoke, prepare, request, result


class NativePretoolFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-file-queries-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.launcher, self.project = prepare(self.base)
        (self.project / "notes.txt").write_text("TODO synthetic\n")
        (self.project / "src").mkdir()
        (self.project / "src/code.py").write_text("TODO = 1\n")
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def run_query(self, alias, command, *, native_only=False, **fields):
        return invoke(self.launcher, self.base, self.project, alias,
                      request(self.project, command, **fields),
                      **({"PATH": str(self.empty)} if native_only else {}))

    def test_supported_file_forms_match_python_without_starting_it(self):
        external = self.base / "external.txt"
        external.write_text("synthetic\n")
        (self.project / "linked.txt").symlink_to(external)
        commands = ["rg --files", "rg --files src", "rg --files . src", "rg -n TODO",
                    "rg -n TODO notes.txt", "rg -n TODO src/code.py", "cat notes.txt",
                    "cat -n notes.txt src/code.py", "head notes.txt", "head -n 20 notes.txt",
                    "head -n 0 notes.txt", "head -n 1000000 notes.txt", "cat\tnotes.txt",
                    "cat ./notes.txt", "cat linked.txt", "cat " + str(external)]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual((0, b"", b""), result(baseline))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command, native_only=True)))

    def test_shell_options_and_unsupported_neighbors_require_python(self):
        neighbors = ["rg --pre evil TODO", "rg --pre=evil TODO", "rg -n --pre=evil notes.txt",
                     "rg -n TODO --pre evil", "rg --files --pre=evil", "rg --files --hidden",
                     "cat", "cat -u notes.txt", "head -n -1 notes.txt", "head -c 10 notes.txt",
                     "rg -n -foo notes.txt", "rg -n TODO --output=written", "sed -i x notes.txt",
                     "cat missing", "cat src/../notes.txt", "cat 한글.txt",
                     "CAT notes.txt", "/bin/cat notes.txt", "env cat notes.txt"]
        for base in ("rg --files", "rg -n TODO notes.txt", "cat notes.txt", "head -n 20 notes.txt"):
            neighbors.extend(base + tail for tail in ("; touch written", " && touch written", " | cat",
                " > written", " 2>written", "$(touch written)", "`touch written`", "\n", "\r", " # comment"))
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in neighbors:
                with self.subTest(alias=alias, command=command):
                    done = self.run_query(alias, command, native_only=True)
                    self.assertEqual(127, done.returncode)
            for command in neighbors:
                baseline = invoke(self.launcher, self.base, self.project, alias,
                                  request(self.project, command), backend="python")
                self.assertEqual(result(baseline), result(self.run_query(alias, command)))
        self.assertFalse((self.project / "written").exists())

    def test_tail_wc_and_bounded_sed_match_python_without_it(self):
        (self.project / "한글 메모.txt").write_text("synthetic\n")
        commands = ["tail notes.txt", "tail -n 0 notes.txt", "tail -n 1000000 notes.txt",
                    "tail -n 20 '한글 메모.txt'", "wc notes.txt", "wc -l notes.txt src/code.py",
                    "wc -w notes.txt", "wc -c notes.txt", "wc -m '한글 메모.txt'",
                    "sed -n '1,120p' notes.txt", 'sed -n "42p" notes.txt',
                    "sed -n 1,10p notes.txt", "sed -n '1,20p' '한글 메모.txt'"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual((0, b"", b""), result(baseline))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command, native_only=True)))

    def test_literal_ls_forms_match_python_without_it(self):
        folder = self.project / "소스 폴더"
        folder.mkdir()
        commands = ["ls", "ls -la", "ls -al", "ls -lh notes.txt", "ls -lah '소스 폴더'",
                    "ls -a . src", "ls -l notes.txt src/code.py"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual((0, b"", b""), result(baseline))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command, native_only=True)))

    def test_ls_uncertainty_keeps_python_and_local_alias_checks(self):
        commands = ["ls -R", "ls -l -a", "ls --color=always", "ls missing", "ls ../",
                    "ls -la > written", "ls -la; touch written", "ls $(touch written)"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)
            (self.project / "ls").write_text("synthetic local alias")
            self.assertEqual(127, self.run_query(alias, "ls -la", native_only=True).returncode)
            (self.project / "ls").unlink()
        self.assertFalse((self.project / "written").exists())

    def test_printing_query_unsafe_neighbors_keep_python_authority(self):
        commands = ["tail -f notes.txt", "tail -n +1 notes.txt", "tail -n 1000001 notes.txt",
                    "wc --files0-from=list", "wc -l -w notes.txt", "sed -i '1p' notes.txt",
                    "sed -n '1,5p;w written' notes.txt", "sed -n '1,5w written' notes.txt",
                    "sed -n '1,5e' notes.txt", "sed -n '$p' notes.txt", "sed -n '0p' notes.txt",
                    "sed -n '5,1p' notes.txt", "sed -n '1,1000001p' notes.txt",
                    "sed -n '1,5p' -i notes.txt", "sed -n '1,5p' missing"]
        commands += [base + suffix for base in ("tail notes.txt", "wc -l notes.txt", "sed -n '1,5p' notes.txt")
                     for suffix in ("; touch written", " > written", " | cat", "$(touch written)")]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)
        self.assertFalse((self.project / "written").exists())

    def test_literal_quotes_unicode_and_spaces_match_python_without_it(self):
        (self.project / "한글.txt").write_text("TODO synthetic\n")
        folder = self.project / "소스 폴더"
        folder.mkdir()
        (folder / "한글 메모.txt").write_text("TODO synthetic\n")
        commands = ["cat 'notes.txt'", 'cat "notes.txt"', "cat 한글.txt", "cat '한글.txt'",
                    "cat '소스 폴더/한글 메모.txt'", 'cat "소스 폴더/한글 메모.txt"',
                    "cat -n 'notes.txt' 한글.txt", "head -n 20 '소스 폴더/한글 메모.txt'",
                    'head "소스 폴더/한글 메모.txt"', "rg --files '소스 폴더'",
                    'rg -n TODO "소스 폴더/한글 메모.txt"', "cat '" + str(folder / "한글 메모.txt") + "'",
                    "\tcat\t'소스 폴더/한글 메모.txt'\t"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual((0, b"", b""), result(baseline))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(result(baseline), result(self.run_query(alias, command, native_only=True)))

    def test_uncertain_quoting_expansions_and_unicode_controls_fall_back(self):
        commands = ["cat 'notes.txt", 'cat "notes.txt', "cat no'tes.txt'", "cat 'notes'.txt",
                    "'cat' notes.txt", "cat ''", "cat '../notes.txt'", "cat '-n' notes.txt",
                    'cat "$HOME/notes.txt"', "cat '$(touch written)'", "cat `touch written`",
                    "cat notes\\ file.txt", 'cat "notes\\\".txt"', "cat 'notes\n.txt'",
                    "cat 'notes\t.txt'", "cat 한글\u2028.txt", "cat 'notes.txt'\r",
                    "cat 'notes.txt'; touch written", "cat 'notes.txt' > written",
                    "cat 'notes.txt' | cat", "cat 'notes.txt' # comment", "rg '-n' TODO notes.txt"]
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            for command in commands:
                with self.subTest(alias=alias, command=command):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)
        self.assertFalse((self.project / "written").exists())

    def test_quoted_paths_keep_transcript_workdir_and_filesystem_checks(self):
        command = "cat 'notes.txt'"
        other = self.base / "other quoted 한글"
        other.mkdir()
        (other / "notes.txt").write_text("synthetic\n")
        transcript = self.base / "literal-transcript.jsonl"
        arguments = json.dumps({"cmd": command, "workdir": str(other)})
        transcript.write_text(json.dumps({"payload": {"type": "function_call", "arguments": arguments}}) + "\n")
        fields = {"transcript_path": str(transcript)}
        baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate",
                          request(self.project, command, **fields), backend="python")
        self.assertEqual((0, b"", b""), result(baseline))
        self.assertEqual(result(baseline), result(self.run_query("codex-pretool-gate", command,
                                                               native_only=True, **fields)))
        (other / "notes.txt").unlink()
        (other / "notes.txt").symlink_to("notes.txt")
        baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate",
                          request(self.project, command, **fields), backend="python")
        self.assertEqual(result(baseline), result(self.run_query("codex-pretool-gate", command, **fields)))
        self.assertEqual(127, self.run_query("codex-pretool-gate", command, native_only=True, **fields).returncode)

    def test_operand_and_executable_symlink_loops_require_python(self):
        for name, command in (("loop", "cat loop"), ("cat", "cat notes.txt"),
                              ("TODO", "rg -n TODO notes.txt")):
            path = self.project / name
            path.symlink_to(name)
            try:
                for alias in ("claude-pretool-gate", "codex-pretool-gate"):
                    baseline = invoke(self.launcher, self.base, self.project, alias,
                                      request(self.project, command), backend="python")
                    self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                    self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)
            finally:
                path.unlink()

    def test_codex_checks_file_paths_at_transcript_workdirs(self):
        other = self.base / "other"
        other.mkdir()
        (other / "notes.txt").write_text("synthetic\n")
        transcript = self.base / "transcript.jsonl"
        for kind in ("function_call", "custom_tool_call"):
            record = ({"type": kind, "arguments": json.dumps({"cmd": "cat notes.txt", "workdir": str(other)})}
                      if kind == "function_call" else {"type": kind, "input":
                      'await tools.exec_command({cmd:"cat notes.txt",workdir:"' + str(other) + '"})'})
            transcript.write_text(json.dumps({"payload": record}) + "\n")
            fields = {"transcript_path": str(transcript)}
            self.assertEqual((0, b"", b""), result(self.run_query("codex-pretool-gate", "cat notes.txt", native_only=True, **fields)))
            (other / "notes.txt").unlink()
            (other / "notes.txt").symlink_to("notes.txt")
            self.assertEqual(127, self.run_query("codex-pretool-gate", "cat notes.txt", native_only=True, **fields).returncode)
            baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate",
                              request(self.project, "cat notes.txt", **fields), backend="python")
            self.assertEqual(result(baseline), result(self.run_query("codex-pretool-gate", "cat notes.txt", **fields)))
            (other / "notes.txt").unlink()
            (other / "notes.txt").write_text("synthetic\n")

    def test_literal_paths_keep_environment_override_fallback(self):
        (self.project / "한글 notes.txt").write_text("synthetic\n")
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            command = "cat '한글 notes.txt'"
            baseline = invoke(self.launcher, self.base, self.project, alias,
                              request(self.project, command), backend="python")
            self.assertEqual(result(baseline), result(self.run_query(alias, command)))
            self.assertEqual(result(baseline), result(self.run_query(alias, command, native_only=True)))
            for override in ({"PYTHONPATH": "synthetic"}, {"MORU_STATE_HOME": "~__missing_user_9a315__/state"}):
                done = invoke(self.launcher, self.base, self.project, alias,
                              request(self.project, command), PATH=str(self.empty), **override)
                self.assertEqual(127, done.returncode)

    def test_local_query_executables_preserve_launcher_policy(self):
        (self.project / "verify").write_text("synthetic\n")
        for name in ("cat", "head"):
            local = self.project / name
            local.symlink_to(self.launcher)
            try:
                for alias in ("claude-pretool-gate", "codex-pretool-gate"):
                    with self.subTest(name=name, alias=alias):
                        command = name + " verify"
                        baseline = invoke(self.launcher, self.base, self.project, alias,
                                          request(self.project, command), backend="python")
                        self.assertTrue(baseline.stdout, "fixture must exercise the launcher policy")
                        self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                        self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)
            finally:
                local.unlink()

    def test_custom_workdir_errors_keep_python_diagnostics(self):
        transcript = self.base / "too-long.jsonl"
        for command in ("cat notes.txt", "rg --files", "pwd", "git status --short"):
            with self.subTest(command=command):
                code = 'await tools.exec_command({cmd:"' + command + '",workdir:"/' + "x" * 300 + '"})'
                transcript.write_text(json.dumps({"payload": {"type": "custom_tool_call", "input": code}}) + "\n")
                fields = {"transcript_path": str(transcript)}
                baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate",
                                  request(self.project, command, **fields), backend="python")
                # pathlib 3.14+ suppresses OS errors in is_dir(); retain the
                # observed baseline rather than require a version-specific warning.
                self.assertEqual(result(baseline), result(self.run_query("codex-pretool-gate", command, **fields)))
                self.assertEqual(127, self.run_query("codex-pretool-gate", command, native_only=True, **fields).returncode)

    def test_custom_quotes_cannot_hide_uncertain_workdirs(self):
        other = self.base / "other-quoted"
        other.mkdir()
        (other / "notes.txt").symlink_to("notes.txt")
        transcript = self.base / "quoted.jsonl"
        affixes = [('/* " */ ', ''), ('/* " */ ', ' /* " */'),
                   ('const a = \'"\'; ', ' const b = \'"\';'), ('const a = `"`; ', '')]
        for before, after in affixes:
            with self.subTest(before=before, after=after):
                code = before + 'await tools.exec_command({cmd:"cat notes.txt",workdir:"' + str(other) + '"})' + after
                transcript.write_text(json.dumps({"payload": {"type": "custom_tool_call", "input": code}}) + "\n")
                fields = {"transcript_path": str(transcript)}
                baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate",
                                  request(self.project, "cat notes.txt", **fields), backend="python")
                self.assertEqual(result(baseline), result(self.run_query("codex-pretool-gate", "cat notes.txt", **fields)))
                self.assertEqual(127, self.run_query("codex-pretool-gate", "cat notes.txt", native_only=True, **fields).returncode)

    def test_token_limit_and_dangling_operands(self):
        (self.project / "dangling").symlink_to("absent-target")
        admitted = "cat " + " ".join(["notes.txt"] * 19)
        rejected = (admitted + " notes.txt", "cat dangling", "cat -n", "head -n 20", "cat -", "cat notes.txt\x7f")
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            self.assertEqual((0, b"", b""), result(self.run_query(alias, admitted, native_only=True)))
            for command in rejected:
                baseline = invoke(self.launcher, self.base, self.project, alias,
                                  request(self.project, command), backend="python")
                self.assertEqual(result(baseline), result(self.run_query(alias, command)))
                self.assertEqual(127, self.run_query(alias, command, native_only=True).returncode)

    def test_launcher_shadow_in_process_cwd_with_different_payload_cwd(self):
        other_base = self.base / "other-payload"
        other_base.mkdir()
        _other_launcher, other = prepare(other_base)
        (other / "verify").write_text("synthetic\n")
        (self.project / "cat").symlink_to(self.launcher)
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            with self.subTest(alias=alias):
                payload = request(other, "cat verify")
                baseline = invoke(self.launcher, self.base, self.project, alias, payload, backend="python")
                native = invoke(self.launcher, self.base, self.project, alias, payload)
                self.assertTrue(baseline.stdout)
                self.assertEqual(result(baseline), result(native))

    def test_local_launcher_in_parent_directory_does_not_change_query(self):
        nested = self.project / "nested"
        nested.mkdir()
        (nested / "verify").write_text("synthetic\n")
        (self.project / "cat").symlink_to(self.launcher)
        for alias in ("claude-pretool-gate", "codex-pretool-gate"):
            payload = request(nested, "cat verify")
            baseline = invoke(self.launcher, self.base, nested, alias, payload, backend="python")
            native = invoke(self.launcher, self.base, nested, alias, payload, PATH=str(self.empty))
            self.assertEqual((0, b"", b""), result(baseline))
            self.assertEqual(result(baseline), result(native))

    def test_relative_transcript_workdirs_keep_payload_cwd(self):
        other = self.project / "relative"
        other.mkdir()
        (other / "notes.txt").symlink_to("notes.txt")
        transcript = self.base / "relative.jsonl"
        for kind in ("function_call", "custom_tool_call"):
            record = ({"type": kind, "arguments": json.dumps({"cmd": "cat notes.txt", "workdir": "relative"})}
                      if kind == "function_call" else {"type": kind, "input":
                      'await tools.exec_command({cmd:"cat notes.txt",workdir:"relative"})'})
            transcript.write_text(json.dumps({"payload": record}) + "\n")
            payload = request(self.project, "cat notes.txt", transcript_path=str(transcript))
            baseline = invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload, backend="python")
            native = invoke(self.launcher, self.base, self.project, "codex-pretool-gate", payload, PATH=str(self.empty))
            self.assertEqual((0, b"", b""), result(baseline))
            self.assertEqual(result(baseline), result(native))
