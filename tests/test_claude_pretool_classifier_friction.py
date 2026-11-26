"""Regression and negative-control tests for C2 PreToolUse classifier friction fixes."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import claude_bash_syntax as bash_syntax  # noqa: E402
import claude_pretool_auto_start as auto  # noqa: E402
from claude_bash_http import curl_effect  # noqa: E402
from claude_bash_readonly import bash_command_kind, bash_invocation  # noqa: E402
from claude_command_effect import command_effect  # noqa: E402
from claude_pretool_publication import open_run_publication_hold, publication_hold  # noqa: E402
from support.global_state import STATE_HOME_ENV  # noqa: E402
from test_claude_pretool_gate import (  # noqa: E402
    _decision_of,
    _opt_in_project,
    _reason,
    _write_preflight,
    gate,
)


def _effect(command: str, cwd: Path = Path("/tmp")) -> tuple[str, str]:
    _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, cwd)
    return command_effect(tokens, simple, bash_command_kind(tokens, simple, cwd))


def _decide(payload: dict) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = gate.decide(payload)
    return code, buffer.getvalue()


def _init_protected_repo_with_worktree(base: Path) -> tuple[Path, Path]:
    main = _opt_in_project(base)
    (main / ".gitignore").write_text(".moru/\n", encoding="utf-8")
    (main / "src").mkdir()
    (main / "src" / "x.js").write_text("export const x = 1;\n", encoding="utf-8")
    policy = main / gate.WORKTREE_POLICY_PATH
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "require_linked_worktree": True,
                "require_workflow_entry": True,
                "protected_branches": ["main"],
            }
        ),
        encoding="utf-8",
    )
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "."],
        [
            "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid",
            "commit", "-qm", "fixture",
        ],
    ):
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True)
    wt = base / "wt-task"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-qb", "task", str(wt)],
        check=True,
        capture_output=True,
    )
    (wt / ".moru").mkdir(exist_ok=True)
    return main, wt


class ReadClassifierFrictionTests(unittest.TestCase):
    def test_admits_real_read_commands_from_evidence(self) -> None:
        structure_check = ROOT / "scripts" / "agent-structure-check.py"
        workflow_cli = ROOT / "scripts" / "workflow.py"
        status_cli = ROOT / "scripts" / "agent-os-status.py"
        with tempfile.TemporaryDirectory() as clean_home, patch.dict(
            os.environ,
            {
                "HOME": clean_home,
                "CURL_HOME": "",
                "XDG_CONFIG_HOME": "",
                "http_proxy": "",
                "HTTP_PROXY": "",
                "https_proxy": "",
                "HTTPS_PROXY": "",
                "all_proxy": "",
                "ALL_PROXY": "",
            },
        ):
            for command in (
                "ls; ffprobe -v quiet -hide_banner -select_streams v:0 -show_entries stream=width,height -of default=noprint_wrappers=1 /tmp/clip.mp4",
                "ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/clip.mp4",
                "ffmpeg -hide_banner -i /tmp/clip.mp4",
                "ffmpeg -v error -i /tmp/clip.mp4 -f null -",
                "curl -sI 127.0.0.1:8080/health",
                "curl -sI http://127.0.0.1:5173/",
                "curl -s http://localhost:3000/status",
                "sed -n '1,50p;51q' src/x.js",
                "sed -nE '/export/p' src/x.js",
                "rg --files",
                "git -C /tmp/repo diff --stat",
                "cat /tmp/SKILL.md",
                "# inspect skill\ncat /tmp/SKILL.md",
                "head -n 20 src/x.js",
                "tail -n 20 src/x.js",
                "python3 -I -m json.tool package.json",
                f"{structure_check} --project /tmp/wt",
                f"{structure_check} --json",
                f"{structure_check} --project /tmp/wt --json",
                f"python3 {structure_check} --project /tmp/wt",
                f"python3 {structure_check} --json",
                f"python3 {structure_check} --project /tmp/wt --json",
                f"python3 {workflow_cli} validate",
                f"python3 {workflow_cli} route --project {ROOT} --request x",
                f"python3 {status_cli} --validate",
            ):
                with self.subTest(command=command):
                    self.assertEqual("read_only", _effect(command)[0], command)

    def test_b1_python_isolated_c_bypasses_are_mutating_and_blocked(self) -> None:
        repros = (
            "python3 -I -c \"import pathlib; pathlib.os.execv('/bin/sh',['sh','-c','touch /tmp/pwn'])\"",
            "python3 -I -c \"import glob; glob.os.posix_spawn('/bin/sh',['sh','-c','git push origin main'],{})\"",
            "python3 -I -c \"import sys; sys.modules['os'].execl('/bin/sh','sh','-c','touch x')\"",
            "python3 -I -c \"import tarfile; tarfile.shutil.rmtree('x')\"",
            "python3 -I -c \"import pathlib; f=pathlib.Path('/proj/a.py').open('w'); print('pwned', file=f)\"",
            "python3 -I -c \"open('x', **{'mode':'w'}).close()\"",
            "python3 -I -c \"import io; io.FileIO('x','w')\"",
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            main, wt = _init_protected_repo_with_worktree(Path(tmp))
            for idx, command in enumerate(repros):
                with self.subTest(command=command):
                    _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, main)
                    self.assertEqual("mutating", bash_command_kind(tokens, simple, main), command)
                    self.assertNotEqual("read_only", _effect(command, main)[0], command)
                    # Compound invocation in main checkout without start must be denied.
                    _, out_main = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(main),
                            "session_id": f"b1-main-{idx}",
                            "tool_input": {"command": f"{command} && true"},
                        }
                    )
                    self.assertEqual("deny", _decision_of(out_main), (command, out_main))
                    # Unstarted worktree invocation in codex runtime must be denied.
                    _, out_wt = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(wt),
                            "session_id": f"b1-wt-{idx}",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual("deny", _decision_of(out_wt), (command, out_wt))

    def test_b2_forged_moru_checkout_and_unchecked_args_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake"
            fake.mkdir()
            (fake / "agent-hook.py").write_text("", encoding="utf-8")
            (fake / "claude_pretool_gate.py").write_text("", encoding="utf-8")
            fake_wf = fake / "workflow.py"
            fake_wf.write_text("#!/usr/bin/env python3\nprint('pwn')\n", encoding="utf-8")
            fake_wf.chmod(0o755)
            fake_setup = fake / "setup-agent-hooks.py"
            fake_setup.write_text("print('pwn')\n", encoding="utf-8")
            # Note: fake/agent-os-status.py is intentionally absent!
            for command in (
                f"python3 {fake_wf} validate",
                f"python3 {fake_wf} route",
                f"{fake_wf} validate",
                f"python3 {fake / 'agent-os-status.py'}",
                f"python3 {fake / 'agent-structure-check.py'}",
                f"python3 {fake_setup}",
                f"python3 {ROOT / 'scripts' / 'workflow.py'} validate --fix",
                f"python3 {ROOT / 'scripts' / 'agent-os-status.py'} --write",
                f"python3 {ROOT / 'scripts' / 'agent-structure-check.py'} --write",
            ):
                with self.subTest(command=command):
                    _, tokens, simple = bash_invocation({"tool_input": {"command": command}}, Path(tmp))
                    self.assertEqual("mutating", bash_command_kind(tokens, simple, Path(tmp)), command)

    def test_n1_linked_worktree_in_tmp_with_modified_workflow_is_mutating(self) -> None:
        """End-to-end N1 repro: a real linked worktree under /private/tmp with modified workflow.py."""
        import shutil
        import claude_bash_moru_scripts as moru_scripts
        import claude_bash_readonly

        evil_wt = Path(f"/private/tmp/moru-n1-evil-wt-{os.getpid()}")
        shutil.rmtree(evil_wt, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            main_repo = Path(tmp).resolve() / "moru-main"
            (main_repo / "scripts").mkdir(parents=True)
            (main_repo / "scripts" / "workflow.py").write_text(
                "#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8"
            )
            for args in (
                ["init", "-q", "-b", "main"],
                ["add", "."],
                [
                    "-c", "user.name=Test",
                    "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "init",
                ],
            ):
                subprocess.run(["git", "-C", str(main_repo), *args], check=True, capture_output=True)
            try:
                subprocess.run(
                    ["git", "-C", str(main_repo), "worktree", "add", "-qb", "rv-evil", str(evil_wt)],
                    check=True,
                    capture_output=True,
                )
                # Overwrite workflow.py inside the linked worktree under /private/tmp.
                evil_wf = evil_wt / "scripts" / "workflow.py"
                evil_wf.write_text("import os; os.system('touch /tmp/pwned')\n", encoding="utf-8")
                pointer = Path(tmp) / "moru-root"
                pointer.write_text(f"{main_repo}\n", encoding="utf-8")
                # Even if main_repo is pointed to (and treated as non-temp), the linked
                # worktree under /private/tmp MUST NOT be trusted.
                real_is_temp = moru_scripts._is_under_temp_root

                def only_main_non_temp(path: Path) -> bool:
                    resolved = path.resolve()
                    if resolved == main_repo or resolved == (main_repo / "scripts").resolve():
                        return False
                    return real_is_temp(resolved)

                with patch.object(
                    claude_bash_readonly, "stable_root_pointer_path", return_value=pointer
                ), patch.object(
                    moru_scripts, "_is_under_temp_root", side_effect=only_main_non_temp
                ):
                    trusted = moru_scripts.trusted_moru_scripts_dirs(pointer)
                    self.assertNotIn((evil_wt / "scripts").resolve(), trusted)
                    cmd = f"python3 {evil_wf} validate"
                    _, tokens, simple = bash_invocation({"tool_input": {"command": cmd}}, evil_wt)
                    self.assertEqual("mutating", bash_command_kind(tokens, simple, evil_wt))
                    self.assertNotEqual("read_only", _effect(cmd, evil_wt)[0])

                # Also verify a pointer directly naming a /private/tmp checkout is never trusted.
                tmp_pointer = Path(tmp) / "tmp-moru-root"
                tmp_pointer.write_text(f"{evil_wt.resolve()}\n", encoding="utf-8")
                with patch.object(
                    claude_bash_readonly, "stable_root_pointer_path", return_value=tmp_pointer
                ):
                    self.assertNotIn(
                        (evil_wt / "scripts").resolve(),
                        moru_scripts.trusted_moru_scripts_dirs(tmp_pointer),
                    )
                    cmd = f"python3 {evil_wf} validate"
                    _, tokens, simple = bash_invocation({"tool_input": {"command": cmd}}, evil_wt)
                    self.assertEqual("mutating", bash_command_kind(tokens, simple, evil_wt))
            finally:
                subprocess.run(
                    ["git", "-C", str(main_repo), "worktree", "remove", "--force", str(evil_wt)],
                    check=False,
                    capture_output=True,
                )
                shutil.rmtree(evil_wt, ignore_errors=True)

    def test_m1_and_n4_curl_loopback_rejects_proxy_env_and_all_curlrc_paths(self) -> None:
        clean_env_base = {
            "CURL_HOME": "",
            "XDG_CONFIG_HOME": "",
            "http_proxy": "",
            "HTTP_PROXY": "",
            "https_proxy": "",
            "HTTPS_PROXY": "",
            "all_proxy": "",
            "ALL_PROXY": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            clean_home = Path(tmp) / "clean-home"
            clean_home.mkdir()
            with patch.dict(os.environ, {"HOME": str(clean_home), **clean_env_base}):
                # Positive: clean loopback GET without proxy or curlrc.
                self.assertEqual("read_only", curl_effect(["-sI", "http://127.0.0.1:8080/"])[0])
                # Negative: -x / --proxy rejected on loopback without -q.
                self.assertEqual("unknown", curl_effect(["-x", "http://evil:8080", "http://127.0.0.1:8080/"])[0])
                self.assertEqual("unknown", curl_effect(["--proxy", "http://evil:8080", "http://localhost:3000/"])[0])
                self.assertEqual("unknown", curl_effect(["--proxy=http://evil:8080", "http://localhost:3000/"])[0])
            # N4 negative: proxy environment variables require -q first.
            for env_var in ("http_proxy", "HTTP_PROXY", "ALL_PROXY"):
                with self.subTest(env_var=env_var), patch.dict(
                    os.environ, {"HOME": str(clean_home), **clean_env_base, env_var: "http://evil:8080"}
                ):
                    self.assertEqual("unknown", curl_effect(["-sI", "http://127.0.0.1:8080/"])[0])
                    self.assertEqual("read_only", curl_effect(["-q", "-sI", "http://127.0.0.1:8080/"])[0])
            # N4 negative: $XDG_CONFIG_HOME/curlrc (no dot) requires -q first.
            xdg_dir = Path(tmp) / "xdg"
            xdg_dir.mkdir()
            (xdg_dir / "curlrc").write_text("output = /tmp/pwned\n", encoding="utf-8")
            with patch.dict(
                os.environ, {"HOME": str(clean_home), **clean_env_base, "XDG_CONFIG_HOME": str(xdg_dir)}
            ):
                self.assertEqual("unknown", curl_effect(["-sI", "http://127.0.0.1:8080/"])[0])
                self.assertEqual("read_only", curl_effect(["-q", "-sI", "http://127.0.0.1:8080/"])[0])
            # N4 negative: ~/.config/curlrc (no dot) requires -q first.
            (clean_home / ".config").mkdir()
            (clean_home / ".config" / "curlrc").write_text("output = /tmp/pwned\n", encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(clean_home), **clean_env_base}):
                self.assertEqual("unknown", curl_effect(["-sI", "http://127.0.0.1:8080/"])[0])
                self.assertEqual("read_only", curl_effect(["-q", "-sI", "http://127.0.0.1:8080/"])[0])
            (clean_home / ".config" / "curlrc").unlink()
            # Negative: implicit ~/.curlrc disables loopback shortcut unless -q is first.
            curlrc = clean_home / ".curlrc"
            curlrc.write_text("output = /tmp/pwned\n", encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(clean_home), **clean_env_base}):
                self.assertEqual("unknown", curl_effect(["-sI", "http://127.0.0.1:8080/"])[0])
                self.assertEqual("read_only", curl_effect(["-q", "-sI", "http://127.0.0.1:8080/"])[0])

    def test_m2_heredoc_terminator_matches_bash_exact_line(self) -> None:
        trailing_space = "cat > x.txt <<'EOF'\nEOF2\nEOF \ngit push"
        self.assertEqual(trailing_space, bash_syntax.without_passive_heredocs(trailing_space))
        self.assertEqual("publishes", publication_hold(trailing_space))
        trailing_tab = "cat > x.txt <<'EOF'\nhi\nEOF\t\ngit push"
        self.assertEqual(trailing_tab, bash_syntax.without_passive_heredocs(trailing_tab))
        leading_space_strip = "cat > x.txt <<-'EOF'\nhi\n  EOF"
        self.assertEqual(leading_space_strip, bash_syntax.without_passive_heredocs(leading_space_strip))
        # Positive: leading tab with <<- matches bash exactly.
        leading_tab_strip = "cat > x.txt <<-'EOF'\nhi\n\tEOF"
        self.assertEqual("cat > x.txt", bash_syntax.without_passive_heredocs(leading_tab_strip))

    def test_negative_controls_reject_writes_and_unsafe_variants(self) -> None:
        for command in (
            "ffmpeg -i /tmp/in.mp4 /tmp/out.mp4",
            "ffmpeg -i /tmp/in.mp4 -f mp4 /tmp/out.mp4",
            "curl -X POST http://127.0.0.1:8080/api",
            "curl -d '{}' http://localhost:3000/api",
            "curl -o saved.html http://127.0.0.1:8080/",
            "curl https://example.test/",
            "sed -i 's/a/b/' src/x.js",
            "python3 -I -c \"open('x.txt', 'w').write('bad')\"",
            "python3 -I -c \"import pathlib; pathlib.Path('x.txt').write_text('bad')\"",
            "python3 -I -c \"import subprocess; subprocess.run(['git', 'push'])\"",
            "python3 -I -c \"import os; os.system('rm -rf .')\"",
            "python3 -I -c \"().__class__.__mro__[1].__subclasses__()\"",
            "python3 -c \"import json; print(1)\"",
        ):
            with self.subTest(command=command):
                self.assertNotEqual("read_only", _effect(command)[0], command)

    def test_moru_structure_check_is_not_blocked_as_main_checkout_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            _, wt = _init_protected_repo_with_worktree(Path(tmp))
            script = ROOT / "scripts" / "agent-structure-check.py"
            payload = {
                "tool_name": "Bash",
                "cwd": str(wt),
                "session_id": "sol-review",
                "tool_input": {"command": f"{script} --project {wt}"},
            }
            _, out = _decide(payload)
            self.assertNotEqual("deny", _decision_of(out), out)


class HeredocAndPublicationFrictionTests(unittest.TestCase):
    def test_heredoc_file_write_inside_owned_worktree_is_allowed_with_open_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            _, wt = _init_protected_repo_with_worktree(Path(tmp))
            _write_preflight(wt, "codex-h1", runtime="codex")
            cmd = (
                "cat > src/x.js <<'EOF'\n"
                "const items = [];\n"
                "items.push('tag');\n"
                "export const count = items.length;\n"
                "EOF\n"
            )
            self.assertEqual("", open_run_publication_hold(cmd, root=wt, cwd=wt))
            _, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(wt),
                    "session_id": "codex-h1",
                    "tool_input": {"command": cmd},
                }
            )
            self.assertNotEqual("deny", _decision_of(out), out)

    def test_heredoc_moru_checkpoint_is_runtime_control_not_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            _, wt = _init_protected_repo_with_worktree(Path(tmp))
            launcher = gate.stable_launcher_path()
            cmd = (
                f"{launcher} checkpoint --project {wt} --rules {ROOT} "
                "--checkpoint-kind decision --phase acting --work-stdin <<'EOF'\n"
                '{"objective": "Update scene"}\n'
                "EOF\n"
            )
            _, out = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(wt),
                    "session_id": "codex-h2",
                    "tool_input": {"command": cmd},
                }
            )
            self.assertNotEqual("deny", _decision_of(out), out)

    def test_negative_controls_block_heredoc_in_main_checkout_and_hidden_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            main, wt = _init_protected_repo_with_worktree(Path(tmp))
            _write_preflight(wt, "codex-h3", runtime="codex")
            # 1. Heredoc write in protected main checkout is still blocked.
            _, out_main = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(main),
                    "session_id": "codex-h3",
                    "tool_input": {"command": "cat > src/x.js <<'EOF'\nconst a = 1;\nEOF\n"},
                }
            )
            self.assertEqual("deny", _decision_of(out_main), out_main)
            # 2. Heredoc write escaping owned worktree into main checkout is still blocked.
            _, out_escape = _decide(
                {
                    "tool_name": "Bash",
                    "cwd": str(wt),
                    "session_id": "codex-h3",
                    "tool_input": {
                        "command": f"cat > {main}/src/x.js <<'EOF'\nconst a = 1;\nEOF\n"
                    },
                }
            )
            self.assertEqual("deny", _decision_of(out_escape), out_escape)
            # 3. Wrapped/heredoc commands truly hiding a publish are still blocked.
            for bad_publish in (
                "bash <<'EOF'\ngit push origin main\nEOF\n",
                "cat > src/x.js <<EOF\n$(git push origin main)\nEOF\n",
                'eval "git push origin main"',
                'env -S "git push origin main"',
                "gh pr create --title x --body y",
            ):
                with self.subTest(bad_publish=bad_publish):
                    _, out_pub = _decide(
                        {
                            "tool_name": "Bash",
                            "cwd": str(wt),
                            "session_id": "codex-h3",
                            "tool_input": {"command": bad_publish},
                        }
                    )
                    self.assertEqual("deny", _decision_of(out_pub), bad_publish)


class AutoStartAndScratchpadFrictionTests(unittest.TestCase):
    def test_auto_start_does_not_fire_on_reads_unknown_bash_or_non_git_writing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            _, wt = _init_protected_repo_with_worktree(Path(tmp))
            started = []

            def spy_start(*args, **kwargs):
                started.append(args)
                return "run-should-not-start"

            # Unclassified read/script command (`unknown` effect) must not auto-start local_write.
            with patch.object(auto, "start_run", spy_start):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    gate.decide_with_auto_start(
                        {
                            "tool_name": "Bash",
                            "cwd": str(wt),
                            "session_id": "audit-1",
                            "tool_input": {"command": "python3 tools/inspect_logs.py"},
                        }
                    )
            self.assertEqual([], started)

            # Non-git writing folder must not auto-start small-change.
            writing = Path(tmp) / "writing"
            (writing / "drafts").mkdir(parents=True)
            (writing / "AGENTS.md").write_text(
                "Writing workspace instructions\nuses moru-hook\n", encoding="utf-8"
            )
            auto.record_request(json.dumps({"session_id": "w1", "prompt": "초안 수정해줘"}))
            self.assertEqual(
                "",
                auto.start_run(writing, "w1", "claude", "Edit", "draft.md"),
            )

    def test_i1_runtime_scratchpad_requires_fixed_root_depth_and_no_project_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MORU_PRETOOL_RUNTIME": "codex", STATE_HOME_ENV: tmp + "/state"}
        ):
            main, _wt = _init_protected_repo_with_worktree(Path(tmp))
            # Positive: clean documented Claude scratchpad at exact depth under /private/tmp.
            clean_scratch_root = (Path("/tmp") / f"claude-{os.getpid()}{os.getuid()}").resolve()
            try:
                scratch = clean_scratch_root / "-proj" / "sess-1" / "scratchpad"
                scratch.mkdir(parents=True, exist_ok=True)
                target = scratch / "notes.md"
                self.assertTrue(bash_syntax.is_runtime_scratchpad(target))
                self.assertTrue(bash_syntax.scratch_write_target(str(target), None))
                _, out = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(main),
                        "session_id": "lead-1",
                        "tool_input": {"file_path": str(target), "content": "notes"},
                    }
                )
                self.assertNotEqual("deny", _decision_of(out), out)

                # Negative control 1: symlink inside scratchpad pointing into real repo is STILL blocked.
                escape_link = scratch / "escape.js"
                escape_link.symlink_to(main / "src" / "x.js")
                _, out_link = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(main),
                        "session_id": "lead-1",
                        "tool_input": {"file_path": str(escape_link), "content": "bad"},
                    }
                )
                self.assertEqual("deny", _decision_of(out_link), out_link)

                # Negative control 2: non-Git governed project under /tmp (with AGENTS.md / .moru)
                # MUST NOT lose governance even if nested under a claude-* scratchpad path.
                (scratch / "AGENTS.md").write_text("Moru Core governed project\nuses moru-hook\n", encoding="utf-8")
                (scratch / ".moru").mkdir()
                self.assertFalse(bash_syntax.is_runtime_scratchpad(target))
                self.assertFalse(bash_syntax.scratch_write_target(str(target), None))
                self.assertTrue(gate.opts_in(scratch))
                _, out_gov = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(scratch),
                        "session_id": "lead-2",
                        "tool_input": {"file_path": str(target), "content": "unstarted"},
                    }
                )
                self.assertEqual("deny", _decision_of(out_gov), out_gov)
            finally:
                import shutil

                shutil.rmtree(clean_scratch_root, ignore_errors=True)

            # Negative control 3: arbitrary dir named scratchpad under /private/tmp is NOT runtime scratchpad.
            self.assertFalse(bash_syntax.is_runtime_scratchpad(Path("/private/tmp/foo/scratchpad/x")))

            # Negative control 4: TMPDIR=<repo>/tmp must NEVER make <repo>/tmp/scratchpad/x.py scratch!
            repo_tmp = main / "tmp"
            (repo_tmp / "scratchpad").mkdir(parents=True)
            in_repo_target = repo_tmp / "scratchpad" / "x.py"
            with patch.dict(os.environ, {"TMPDIR": str(repo_tmp)}):
                self.assertFalse(bash_syntax.is_runtime_scratchpad(in_repo_target))
                self.assertFalse(bash_syntax.scratch_write_target(str(in_repo_target), None))
                _, out_tmpdir = _decide(
                    {
                        "tool_name": "Write",
                        "cwd": str(main),
                        "session_id": "lead-3",
                        "tool_input": {"file_path": str(in_repo_target), "content": "x = 1\n"},
                    }
                )
                self.assertEqual("deny", _decision_of(out_tmpdir), out_tmpdir)


if __name__ == "__main__":
    unittest.main()
