#!/usr/bin/env python3
"""Verify a transported bundle in a fresh root/home with no compiler or Python PATH."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from native_pretool_support import PROJECT, environment
from support.native_bundle import install_bundle
from support.stable_launcher import ensure_stable_launcher
from support.native_source_inputs import pretool_contract


def smoke(archive):
    with tempfile.TemporaryDirectory(prefix="native-consumer-") as tmp:
        base = Path(tmp).resolve()
        root = base / "transported root"
        receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
        for relative in pretool_contract(PROJECT)[1]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        sources = set(receipt["source_sha256"]) | {
            "AGENTS.md", "index.md", "common/skills/agent-operating-skill/SKILL.md"}
        for relative in sources:
            assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / relative, target)
        install_bundle(root, archive)
        home = base / "home"
        with patch("support.stable_launcher.Path.home", return_value=home):
            ensure_stable_launcher(root, dry_run=False)
        entry = home / ".moru/bin/moru-hook"
        empty = base / "empty-path"
        empty.mkdir()
        env = environment(base, root)
        env["PATH"] = str(empty)
        repo = base / "repository"
        (repo / ".git/objects").mkdir(parents=True)
        (repo / ".git/HEAD").write_text("ref: refs/heads/synthetic\n")
        request = (json.dumps({"schema_version": 1, "root": str(repo)}) + "\n").encode()
        done = subprocess.run([str(entry), "checkout-identity"], input=request,
                              capture_output=True, env=env, timeout=8)
        expected = {"schema_version": 1, "ok": True, "common_dir": str(repo / ".git"), "branch": "synthetic"}
        assert done.returncode == 0 and not done.stderr, done.stderr
        assert json.loads(done.stdout) == expected, done.stdout
        outputs = []
        for alias in ("claude-statusline", "agy-statusline"):
            done = subprocess.run([str(entry), alias], input=b'{"model":"Moru smoke","cwd":"/synthetic"}',
                                  capture_output=True, env=env, timeout=8)
            assert done.returncode == 0 and not done.stderr and done.stdout, done
            outputs.append(done.stdout)
        assert outputs[0] == outputs[1]
        project = base / "callback-project"
        project.mkdir()
        (project / ".moru").mkdir()
        (project / "notes.txt").write_text("TODO synthetic\n")
        (project / "한글 메모.txt").write_text("TODO synthetic\n")
        normal = environment(base, root)
        subprocess.run(["git", "init", "-q", str(project)], env=normal, check=True, capture_output=True)
        payload = {"cwd": str(project), "session_id": "transported-smoke", "tool_name": "Bash"}
        checks = 3
        for runtime in ("claude", "codex"):
            for command in ("git log -5 --oneline", "git ls-files", "rg --files", "cat notes.txt",
                            "head -n 20 notes.txt", "cat '한글 메모.txt'", 'rg -n TODO "한글 메모.txt"',
                            "tail -n 20 notes.txt", "wc -l notes.txt", "sed -n '1,20p' '한글 메모.txt'"):
                data = {**payload, "tool_input": {"command": command}}
                done = subprocess.run([str(entry), runtime + "-pretool-gate"], input=json.dumps(data).encode(),
                    capture_output=True, env=env, cwd=project, timeout=8)
                assert (done.returncode, done.stdout, done.stderr) == (0, b"", b""), done
                checks += 1
            for _ in range(2):
                done = subprocess.run([str(entry), "mailbox-hook", "deliver", "--runtime", runtime],
                    input=json.dumps(payload).encode(), capture_output=True, env=normal, cwd=project, timeout=8)
                assert done.returncode == 0 and not done.stderr, done
            done = subprocess.run([str(entry), runtime + "-stop-gate"], input=json.dumps(payload).encode(),
                capture_output=True, env=normal, cwd=project, timeout=8)
            assert (done.returncode, done.stdout, done.stderr) == (0, b"", b""), done
        git_only = base / "git-only"
        git_only.mkdir()
        (git_only / "git").symlink_to(shutil.which("git"))
        no_python = {**normal, "PATH": str(git_only)}
        for runtime in ("claude", "codex"):
            for args in (["mailbox-hook", "deliver", "--runtime", runtime],
                         ["mailbox-hook", "ack", "--runtime", runtime], [runtime + "-stop-gate"]):
                done = subprocess.run([str(entry), *args], input=json.dumps(payload).encode(),
                    capture_output=True, env=no_python, cwd=project, timeout=8)
                assert (done.returncode, done.stdout, done.stderr) == (0, b"", b""), done
                checks += 1
        advisor = base / "next-project 한글"
        advisor.mkdir()
        subprocess.run(["git", "init", "-q", str(advisor)], env=normal, check=True, capture_output=True)
        for format in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--format", format]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True, env=no_python, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        assert not (advisor / ".moru").exists()
        (advisor / "한글 note.py").write_text("synthetic = 1\n")
        for format in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--format", format]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True, env=no_python, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        print(f"PASS: {checks} transported checks; lookup/status/pretool with empty PATH, mailbox/Stop/next with Git-only PATH")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    smoke(parser.parse_args().bundle)
