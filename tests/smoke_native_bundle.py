#!/usr/bin/env python3
"""Verify a transported bundle in a fresh root/home with no compiler or Python PATH."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from unittest.mock import patch

from native_pretool_support import PROJECT, environment
from support.native_bundle import install_bundle
from support.stable_launcher import ensure_stable_launcher
from support.native_source_inputs import pretool_contract
from runtime_snapshot_normalize import normalize_output


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
        native = entry.with_name("moru-hook-native")
        def completion(operation, payload):
            done = subprocess.run([str(native), str(entry), "--completion-probe", operation],
                input=json.dumps(payload).encode(), capture_output=True, env=env, cwd=project, timeout=8)
            assert (done.returncode, done.stderr) == (0, b""), done
            envelope = json.loads(done.stdout)
            assert envelope["schema_version"] == 1
            return envelope["result"]
        warnings = completion("quality", {"records": [{"gate": "tests", "status": "SUCCESS",
            "fields": {"check": "echo done", "result": "1 test passed"}}]})
        assert warnings["warnings"] == [{"gate": "tests", "rule": "fixed_output_check"}], warnings
        checks += 1
        requirement = {"revision": 1, "items": [{"id": "r1", "outcome": "Deliver notes", "owner": "lead",
            "gate": "tests", "artifacts": ["notes.txt"]}]}
        assert not completion("requirements", {"current": requirement})["failures"]
        checks += 1
        covered = completion("coverage", {"current": requirement, "project": str(project), "allowed_gates": ["tests"],
            "gates": [{"gate": "tests", "status": "SUCCESS"}]})
        assert not covered["failures"] and len(covered["observations"][0]["artifacts"]["notes.txt"]) == 64, covered
        checks += 1
        progress = {"work": {"remaining_work": [{"checkpoint": "tests", "action": "Verify notes"}], "blockers": []}, "gates": []}
        for _ in range(3): progress["previous"] = completion("progress", progress)
        assert progress["previous"]["stalled"]
        checks += 1
        workspace = base / "discovery-workspace"
        for name in ("first 한글", "second"):
            folder = workspace / name
            folder.mkdir(parents=True)
            (folder / "AGENTS.md").touch()
        nested = workspace / "first 한글/nested"
        nested.mkdir()
        for format in ("text", "json"):
            done = subprocess.run([str(entry), "project-discover", "--request", "진행", "--cwd", str(nested),
                "--format", format], capture_output=True, env=env, cwd=project, timeout=8)
            assert done.returncode == 0 and not done.stderr, done
            if format == "json":
                assert json.loads(done.stdout)["selected_project"]["path"] == str(nested.parent)
            else:
                assert done.stdout.decode() == f"status: selected\nproject: {nested.parent}\ninstruction_files:\n- AGENTS.md\n"
            checks += 1
        for depth, status, code in ((1, "ambiguous", 2), (0, "not_found", 3)):
            done = subprocess.run([str(entry), "project-discover", "--request", "진행", "--cwd", str(workspace),
                "--search-root", str(workspace), "--max-depth", str(depth), "--format", "json"],
                capture_output=True, env=env, cwd=project, timeout=8)
            assert done.returncode == code and not done.stderr, done
            assert json.loads(done.stdout)["status"] == status
            checks += 1
        registry = base / "discovery-registry.json"
        target = workspace / "second"
        registry.write_text(json.dumps({"projects": [{"root": "$SMOKE_REGISTRY_TARGET", "aliases": ["launch", "launch"]}]}))
        registered_env = {**env, "SMOKE_REGISTRY_TARGET": str(target)}
        for format in ("text", "json"):
            done = subprocess.run([str(entry), "project-discover", "--request", "launch", "--cwd", str(project),
                "--registry", str(registry), "--format", format], capture_output=True,
                env=registered_env, cwd=project, timeout=8)
            assert done.returncode == 0 and not done.stderr, done
            if format == "json":
                assert json.loads(done.stdout)["selected_project"]["path"] == str(target)
            else:
                assert done.stdout.decode() == f"status: selected\nproject: {target}\ninstruction_files:\n- AGENTS.md\n"
            checks += 1
        done = subprocess.run([str(entry), "project-discover", "--request", "launch", "--cwd", str(target),
            "--registry", str(registry), "--search-root", str(workspace), "--format", "json"],
            capture_output=True, env=registered_env, cwd=project, timeout=8)
        assert done.returncode == 0 and not done.stderr, done
        chosen = json.loads(done.stdout)["selected_project"]
        assert chosen["aliases"] == ["launch"] and chosen["sources"] == ["registry", "cwd", "search_root"]
        checks += 1
        registry.write_text(json.dumps({"projects": [{"root": str(workspace / name), "aliases": ["launch"]}
                                                       for name in ("first 한글", "second")]}))
        done = subprocess.run([str(entry), "project-discover", "--request", "launch", "--cwd", str(project),
            "--registry", str(registry), "--format", "json"], capture_output=True, env=env, cwd=project, timeout=8)
        assert done.returncode == 2 and not done.stderr and json.loads(done.stdout)["status"] == "ambiguous", done
        checks += 1
        registry.write_text(json.dumps({"workspace_groups": [{"name": "company", "members": [
            {"role": "app", "root": str(workspace / "first 한글")},
            {"role": "web", "root": "$SMOKE_REGISTRY_TARGET"}]}]}))
        for request, status, code in (("company", "ambiguous", 2), ("company web", "selected", 0)):
            args = [str(entry), "project-discover", "--request", request, "--cwd", str(workspace),
                "--registry", str(registry), "--format", "json"]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "SMOKE_REGISTRY_TARGET": str(target), "MORU_LAUNCHER_BACKEND": "python"},
                cwd=project, timeout=8)
            done = subprocess.run(args, capture_output=True, env=registered_env, cwd=project, timeout=8)
            assert (reference.returncode, reference.stderr) == (code, b""), reference
            assert (done.returncode, done.stdout, done.stderr) == (reference.returncode, reference.stdout, reference.stderr), done
            value = json.loads(done.stdout)
            assert value["status"] == status and (value["selected_project"]["path"] == str(target)
                if code == 0 else value["selected_project"] is None), value
            checks += 1
        for request, code in ((str(target), 0), (f"({target}):line", 0)):
            args = [str(entry), "project-discover", "--request", request, "--cwd", str(workspace),
                "--registry", str(registry), "--format", "json"]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "SMOKE_REGISTRY_TARGET": str(target), "MORU_LAUNCHER_BACKEND": "python"},
                cwd=project, timeout=8)
            done = subprocess.run(args, capture_output=True, env=registered_env, cwd=project, timeout=8)
            assert (reference.returncode, reference.stderr) == (code, b""), reference
            assert (done.returncode, done.stdout, done.stderr) == (reference.returncode, reference.stdout, reference.stderr), done
            assert json.loads(done.stdout)["selected_project"]["path"] == str(target), done
            checks += 1
        for runtime in ("claude", "codex"):
            for command in ("git log -5 --oneline", "git ls-files", "rg --files", "cat notes.txt",
                            "head -n 20 notes.txt", "cat '한글 메모.txt'", 'rg -n TODO "한글 메모.txt"',
                            "tail -n 20 notes.txt", "wc -l notes.txt", "sed -n '1,20p' '한글 메모.txt'",
                            "ls -la", "git status --short --branch", "git remote -v"):
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
        common = subprocess.run(["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, env=normal, check=True).stdout.strip()
        repo_key = hashlib.sha256(common.encode()).hexdigest()[:24]
        for runtime in ("claude", "antigravity"):
            acked = Path(normal["MORU_STATE_HOME"]) / "agent-mailbox" / repo_key / "acked" / runtime
            acked.mkdir(parents=True, exist_ok=True)
            for index in range(2): (acked / f"{index:032x}.json").write_text("counted without parsing")
        for runtime in ("claude", "agy"):
            for flags in ([], ["--json"]):
                args = [str(entry), "agent-mailbox", "status", "--project", str(project), "--runtime", runtime, *flags]
                reference = subprocess.run(args, capture_output=True,
                    env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=project, timeout=8)
                done = subprocess.run(args, capture_output=True, env=no_python, cwd=project, timeout=8)
                assert (reference.returncode, reference.stderr) == (0, b""), reference
                assert (done.returncode, done.stdout, done.stderr) == (reference.returncode, reference.stdout, reference.stderr), done
                if flags: assert json.loads(done.stdout)["acked"] == 2, done
                else: assert b"acked=2" in done.stdout, done
                checks += 1
        missing_cards = subprocess.run([str(entry), "work-cards", "--project", str(project), "list"],
            capture_output=True, env=env, cwd=project, timeout=8)
        assert (missing_cards.returncode, missing_cards.stdout, missing_cards.stderr) == (0, b"[]\n", b"")
        checks += 1
        from agent_work_cards import _SCHEMA, SCHEMA_VERSION
        card_db = Path(normal["MORU_STATE_HOME"]) / "work-cards/cards.sqlite3"
        card_db.parent.mkdir(parents=True)
        with sqlite3.connect(card_db) as connection:
            connection.execute(_SCHEMA)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.executemany("INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                [(repo_key, key * 32, "한글 card", "implement", str(project), state, "created", stamp)
                 for key, state, stamp in (("a", "active", "new"), ("b", "done", "old"))])
        before_cards = card_db.read_bytes()
        for flags in ([], ["--all"]):
            args = [str(entry), "work-cards", "--project", str(project), "list", *flags]
            reference = subprocess.run(args, capture_output=True, env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=project, timeout=8)
            done = subprocess.run(args, capture_output=True, env=no_python, cwd=project, timeout=8)
            assert (reference.returncode, reference.stderr) == (0, b""), reference
            assert (done.returncode, done.stdout, done.stderr) == (reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        assert before_cards == card_db.read_bytes()
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
        status_project = base / "status-project"
        state = status_project / ".moru"
        state.mkdir(parents=True)
        for name, value in {"run-registry.json": {"runs": [{"state": "running"}]},
                            "scheduler.json": {"tasks": [{"state": "queued"}]},
                            "events.json": {"events": [{"event_type": "run.started"}]}}.items():
            (state / name).write_text(json.dumps(value))
        args = [str(entry), "agent-os-status", "--project", str(status_project)]
        missing = subprocess.run(args, capture_output=True, env=env, cwd=status_project, timeout=8)
        assert missing.returncode == 127 and not (state / ".state.lock.lock").exists(), missing
        checks += 1
        for validated in (False, True):
            argv = [*args, *(["--validate"] if validated else [])]
            reference = subprocess.run(argv, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=status_project, timeout=8)
            done = subprocess.run(argv, capture_output=True, env=env, cwd=status_project, timeout=8)
            assert reference.returncode == done.returncode == 0 and not reference.stderr and not done.stderr
            kind = "validated_status" if validated else "status"
            assert normalize_output(reference.stdout, kind) == normalize_output(done.stdout, kind)
            checks += 1
        print(f"PASS: {checks} transported checks; lookup/status/pretool with empty PATH, mailbox/Stop/next with Git-only PATH")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    smoke(parser.parse_args().bundle)
