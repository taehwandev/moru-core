#!/usr/bin/env python3
"""Verify a transported bundle in a fresh root/home with no compiler or Python PATH."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from smoke_native_card_resume import check_card_resume
from smoke_native_doc_transcript import check_doc_transcript


def _lossless_report_formats(native, entry, report, env, project):
    from moru_overhead_report import render_markdown

    report = json.loads(json.dumps(report))
    report["all"]["sessions"] = 10**100
    report["all"]["assistant_turns"] = {"n": 1, "median": float("nan"), "p90": float("inf")}
    report["all"]["lifecycle_calls_by_subcommand_total"] = {"한😀": 10**100}
    with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
        expected = {"json": json.dumps(report, ensure_ascii=False, indent=2),
                    "markdown": render_markdown(report)}
    for style, text in expected.items():
        done = subprocess.run([str(native), str(entry), "--overhead-probe", "format"],
            input=json.dumps({"report_json": json.dumps(report), "format": style}, allow_nan=False).encode(),
            capture_output=True, env=env, cwd=project, timeout=8)
        assert (done.returncode, done.stderr) == (0, b""), done
        assert json.loads(done.stdout)["result"]["text"] == text, done.stdout
    return len(expected)


def _typed_card_snapshot(native, entry, database, project, normal, no_python):
    from agent_work_cards import list_cards
    from agent_repository_key import repository_key
    from support.native_cards import _rows

    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE cards ADD COLUMN metric REAL")
        connection.execute("ALTER TABLE cards ADD COLUMN payload BLOB")
        connection.execute("UPDATE cards SET metric=?, payload=?", (float("inf"), bytes(range(256))))
    before = database.read_bytes()
    for all in (False, True):
        with patch.dict(os.environ, {**normal, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = list_cards(project, include_settled=all)
            repo = repository_key(project)
        done = subprocess.run([str(native), str(entry), "--cards-probe", "list"],
            input=json.dumps({"repo": repo, "include_settled": all}).encode(),
            capture_output=True, env=no_python, cwd=project, timeout=8)
        assert (done.returncode, done.stderr) == (0, b""), done
        actual = _rows(json.loads(done.stdout)["result"])
        assert actual == expected and actual is not None, done.stdout
        assert [list(row) for row in actual] == [list(row) for row in expected], done.stdout
    assert before == database.read_bytes()
    return 2


def _card_context(native, entry, base, project, repo, normal, empty):
    from agent_work_cards import _SCHEMA, open_card_lines

    state = base / "recall-state"
    database = state / "work-cards/cards.sqlite3"
    database.parent.mkdir(parents=True)
    location = base / "recall-project"
    (location / ".moru").mkdir(parents=True)
    registry = location / ".moru/run-registry.json"
    registry.write_text(json.dumps({"runs": [{"run_id": key*32, "state": status}
        for key, status in (("a", "running"), ("b", "completed"), ("c", "cancelled"))]}))
    with sqlite3.connect(database) as connection:
        connection.execute(_SCHEMA)
        connection.execute("PRAGMA user_version=3")
        connection.executemany("INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)",
            [(repo, key*32, "synthetic recall 한😀", "implement", str(location), "now", stamp)
             for key, stamp in (("a", "3"), ("b", "2"), ("c", "1"))])
    env = {**normal, "MORU_STATE_HOME": str(state)}
    before = database.read_bytes(), registry.read_bytes()
    with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
        expected = open_card_lines(project, "f"*32)
    done = subprocess.run([str(native), str(entry), "--cards-probe", "context"],
        input=json.dumps({"repo": repo, "current_work_id": "f"*32}).encode(),
        capture_output=True, env={**env, "PATH": str(empty)}, cwd=project, timeout=8)
    assert (done.returncode, done.stderr) == (0, b""), done
    assert json.loads(done.stdout)["result"] == {"lines": expected,
        "stale": [["b"*32, "done"], ["c"*32, "cancelled"]]}, done.stdout
    assert before == (database.read_bytes(), registry.read_bytes())
    return 1


def _card_writes(native, entry, base, project, repo, normal, empty):
    from agent_work_cards import _SCHEMA

    state = base / "write-state"
    database = state / "work-cards/cards.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(_SCHEMA)
        connection.execute("PRAGMA user_version=3")
        connection.execute("INSERT INTO cards VALUES(?,?,?,?,?,'done',?,?,?,'','')",
            ("other", "c"*32, "expired", "test", str(project), "old", "0001", "c"*32))
    env = {**normal, "MORU_STATE_HOME": str(state), "PATH": str(empty)}
    def request(operation, values):
        done = subprocess.run([str(native), str(entry), "--cards-write-probe", operation],
            input=json.dumps({"values":values,"foreign_keys":False}).encode(),capture_output=True,env=env,cwd=project,timeout=8)
        assert (done.returncode, done.stderr) == (0, b""), done
        return json.loads(done.stdout)["result"]["changed"]
    first = "2026-11-08T01:02:03.123456+00:00"
    second = "2026-11-09T01:02:03+00:00"
    values = [repo, "a"*32, "synthetic 한😀", "implement", str(project), first, first, "b"*32, "codex", "opaque"]
    assert request("open", values) is True
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT work_id FROM cards").fetchall() == [("a"*32,)]
    assert request("settle", ["done", first, repo, "a"*32]) is True
    values[5:7] = [second, second]
    values[2] = "reactivated"
    assert request("open", values) is True
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state,created_at,updated_at,summary FROM cards").fetchone() == (
            "active", first, second, "reactivated")
    assert request("settle", ["cancelled", second, repo, "a"*32]) is True
    assert request("settle", ["done", second, repo, "a"*32]) is False
    return 5


def _card_bootstrap(native, entry, base, project, normal, empty):
    from contextlib import closing
    import agent_work_cards as cards

    for version in (None,1,2,99):
        states=[base/f"bootstrap-{version}-{suffix}" for suffix in ("native","python")]
        databases=[state/"work-cards/cards.sqlite3" for state in states]
        for database in databases:
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as connection:
                if version is not None:
                    schema=cards._SCHEMA
                    missing=("runtime","session_id") if version==2 else ("run_id","runtime","session_id")
                    for name in missing: schema=schema.replace(f"    {name} TEXT NOT NULL DEFAULT '',\n","")
                    connection.execute(schema)
                    connection.execute(f"PRAGMA user_version={version}")
        with patch.dict(os.environ,{**normal,"MORU_STATE_HOME":str(states[1]),"MORU_LAUNCHER_BACKEND":"python"},clear=True):
            try:
                with closing(cards._connect()): pass
                expected={"schema_version":1,"result":{"changed":True}}
            except ValueError:
                assert version==99
                expected={"schema_version":1,"unsupported_version":99}
        done=subprocess.run([str(native),str(entry),"--cards-write-probe","bootstrap"],
            input=b'{"values":[],"foreign_keys":false}',capture_output=True,cwd=project,timeout=8,
            env={**normal,"MORU_STATE_HOME":str(states[0]),"PATH":str(empty)})
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)==expected,done.stdout
        snapshots=[]
        for database in databases:
            with closing(sqlite3.connect(database)) as connection:
                snapshots.append((connection.execute("PRAGMA user_version").fetchone(),
                    connection.execute("PRAGMA journal_mode").fetchone(),
                    connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
                    connection.execute("PRAGMA table_info(cards)").fetchall()))
        assert snapshots[0]==snapshots[1],(version,snapshots)
    return 4


def smoke(archive):
    with tempfile.TemporaryDirectory(prefix="native-consumer-") as tmp:
        base = Path(tmp).resolve()
        root = base / "transported root"
        receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
        for relative in pretool_contract(PROJECT)[1]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        sources = set(receipt["source_sha256"]) | {
            "AGENTS.md", "index.md", "common/skills/agent-operating-skill/SKILL.md"}
        manifest_path = "common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"
        sources.add(manifest_path)
        sources.add("platforms/android/skills/android-external-skill-source-coverage/references/current-guidance.md")
        manifest = json.loads((PROJECT / manifest_path).read_text())
        for skill in manifest["skills"]:
            sources.update(skill.get("owners", []))
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
        for alias in ("claude-statusline", "agy-statusline"):
            done = subprocess.run([str(entry), alias, "--chain=printf chained"],
                                  input='{"rate_limits":{"session":{"percent":"٦_٥","window_minutes":"３００"}}}'.encode(),
                                  capture_output=True, env={**env, "NO_COLOR": "1"}, timeout=8)
            assert (done.returncode, done.stdout, done.stderr) == (
                0, "5h ██▊░░░░░  35%  chained".encode(), b""), done
            checks += 1
            done = subprocess.run([str(entry), alias, "--chain=printf chained"],
                                  input=b'{"model":{"display_name":{"b":[null,true],"a":18446744073709551616}},"unused":NaN}',
                                  capture_output=True, env={**env, "NO_COLOR": "1"}, timeout=8)
            assert (done.returncode, done.stdout, done.stderr) == (
                0, b"{'b': [None, True], 'a': 18446744073709551616}  chained", b""), done
            checks += 1
            done = subprocess.run([str(entry), alias, "--chain=printf chained"],
                                  input=b'{"model":"must not appear",}',
                                  capture_output=True, env=env, timeout=8)
            assert (done.returncode, done.stdout, done.stderr) == (0, b"chained", b""), done
            checks += 1
        native = entry.with_name("moru-hook-native")
        transcript = base / "synthetic-overhead.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "timestamp": "2026-10-10T00:00:00Z",
            "message": {"id": "m1", "usage": {"input_tokens": 5}, "content": []}}) + "\n")
        overhead = {"path": str(transcript), "roots": [], "window": [None, None]}
        done = subprocess.run([str(native), str(entry), "--overhead-probe", "session"],
            input=json.dumps(overhead).encode(), capture_output=True, env=env, cwd=project, timeout=8)
        assert (done.returncode, done.stderr) == (0, b""), done
        measured = json.loads(done.stdout)["result"]["row"]
        assert measured["assistant_turns"] == 1 and measured["tok_total"] == 5, measured
        checks += 1
        aggregate_row = {key: measured[key] for key in (
            "assistant_turns", "user_prompts", "tool_calls", "lifecycle_total", "policy_notes",
            "hook_denials", "moru_hook_denials", "stop_hook_blocks", "guidance_reads", "guidance_bash_reads",
            "tok_total", "tok_output", "tok_cache_read", "tok_cache_create",
            "moru_injected_tokens_est", "moru_injected_events", "tok_input", "tools", "lifecycle_calls", "moru_core")}
        done = subprocess.run([str(native),str(entry),"--overhead-probe","analyze"],
            input=json.dumps({"sessions":[aggregate_row],"hook_latency":{"hook":[1e16,1.0,-1e16]}}).encode(),
            capture_output=True,env=env,cwd=project,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        analysis = json.loads(done.stdout)["result"]
        assert analysis["all"]["tok_total"]["sum"]==5 and analysis["all"]["sessions"]==1,analysis
        assert analysis["moru_hook_latency_ms_from_transcripts"]["hook"]["mean"]==0.33,analysis
        checks += 1
        timing = base/"synthetic-timing.jsonl"
        timing.write_text('{"hook":"empty"}\n{"hook":"start","status":"ok","timings":{"hook_total":"١٢.٥"}}\n')
        done = subprocess.run([str(native),str(entry),"--overhead-probe","timings"],
            input=json.dumps({"path":str(timing)}).encode(),capture_output=True,env=env,cwd=project,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        timing_result=json.loads(done.stdout)["result"]
        assert timing_result["records"]==1 and timing_result["per_hook_ms"]["empty"]=={"n":0},timing_result
        assert timing_result["per_hook_ms"]["start"]["median"]==12.5,timing_result
        checks += 1
        report_projects=base/"report-projects/p"
        report_projects.mkdir(parents=True)
        shutil.copy2(transcript,report_projects/"session.jsonl")
        done=subprocess.run([str(entry),"overhead-report","--projects-dir",str(report_projects.parent),
            "--timings",str(timing),"--since","2026-10-01T00:00:00Z","--until","2026-11-08T00:00:00Z"],
            capture_output=True,env=env,cwd=project,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        report=json.loads(done.stdout)
        assert report["all"]["sessions"]==1 and report["all"]["tok_total"]["sum"]==5,report
        assert report["timings_jsonl"]["records"]==1,report
        checks += 1
        for style in ("json","markdown"):
            formatted=subprocess.run([str(native),str(entry),"--overhead-probe","format"],
                input=json.dumps({"report":report,"format":style}).encode(),capture_output=True,
                env=env,cwd=project,timeout=8)
            assert (formatted.returncode,formatted.stderr)==(0,b""),formatted
            text=json.loads(formatted.stdout)["result"]["text"]
            if style=="json":
                assert text+"\n"==done.stdout.decode(),text
            else:
                assert text.startswith("# Moru workflow overhead\n") and "| assistant turns | 1.0 | 1.0 | 1 |" in text,text
            checks += 1
        checks += _lossless_report_formats(native, entry, report, env, project)
        overhead["path"] = "/dev/stdin"
        done = subprocess.run([str(native), str(entry), "--overhead-probe", "session"],
            input=json.dumps(overhead).encode(), capture_output=True, env=env, cwd=project, timeout=8)
        assert (done.returncode, done.stdout, done.stderr) == (125, b"", b""), done
        checks += 1
        state = base / "prepared-registry"
        state.mkdir()
        for name in (".state.lock.lock", ".run-registry.json.lock"):
            (state / name).touch()
        row = {"run_id": "synthetic", "state": "running", "evidence_key": "key"}
        (state / "run-registry.json").write_text(json.dumps({"schema_version": 1, "runs": [row]}))
        before = {p.name: p.read_bytes() for p in state.iterdir()}
        for operation, expected in (("active", [{**row, "resume_generation": 0}]),
                ("bindings", [["key", {**row, "resume_generation": 0}]]), ("latest", "synthetic")):
            payload_read = {"state_dir": str(state), "states": ["running"], "legacy_key": "legacy",
                            "evidence_key": "key", "legacy_default": False, "evidence_name": "preflight.json"}
            done = subprocess.run([str(native), str(entry), "--registry-read-probe", operation],
                input=json.dumps(payload_read).encode(), capture_output=True, env=env, cwd=project, timeout=8)
            assert (done.returncode, done.stderr) == (0, b""), done
            assert json.loads(done.stdout)["result"]["value"] == expected, done
            checks += 1
        assert before == {p.name: p.read_bytes() for p in state.iterdir()}
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
                            "ls -la", "git status --short --branch", "git remote -v",
                            "rg -n 'TODO|FIXME' notes.txt", "rg --files --glob='*.py'",
                            "git log -3 --format='%h %s'", "git diff HEAD~1 HEAD --stat",
                            f"git -C '{project}' status --short",
                            f"cd '{project}' && cat notes.txt",
                            "rg -n 'TODO|FIXME' notes.txt | head -n 20",
                            f"cd '{project}' && git log -3 --format='%h %s' | wc -l",
                            "rg -n -A 3 -B1 TODO notes.txt", "git ls-files | rg 'txt|py'",
                            f"cd '{project}' && cat notes.txt | rg -C2 TODO"):
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
        from test_figma_validate import _valid_summary, _valid_v4_summary
        invalid_figma = _valid_v4_summary()
        invalid_figma["assetCandidates"] = [{"id": "1:2"}]
        numeric_figma = _valid_summary()
        numeric_figma["components"] = [{"componentId": str(i), "usageCount": count}
                                       for i, count in enumerate((1e16, 1.0, 1.0))]
        figma_cases = [(_valid_summary(), 0), (_valid_v4_summary(), 0),
                       (invalid_figma, 1), ([], 1), (numeric_figma, 0)]
        for index, (summary, code) in enumerate(figma_cases):
            summary_path = base / f"figma-summary-{index}.json"
            summary_path.write_text(json.dumps(summary))
            args = [str(entry), "figma-validate", str(summary_path)]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, timeout=8)
            done = subprocess.run(args, capture_output=True, cwd=project,
                env={**no_python, "PATH": str(empty)}, timeout=8)
            assert reference.returncode == code, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        for path in (str(base / "missing-figma-summary"), str(base), "--help"):
            args = [str(entry), "figma-validate", path]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, timeout=8)
            done = subprocess.run(args, capture_output=True, cwd=project,
                env={**no_python, "PATH": str(empty)}, timeout=8)
            assert reference.returncode == 2, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        for index, content in enumerate((b"{", '["한글",]'.encode(), b'"\xed\xa0\x80"', b"\xef\xbb\xbf{}")):
            path = base / f"figma-invalid-{index}.json"
            path.write_bytes(content)
            args = [str(entry), "figma-validate", str(path)]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, timeout=8)
            done = subprocess.run(args, capture_output=True, cwd=project,
                env={**no_python, "PATH": str(empty)}, timeout=8)
            assert reference.returncode == 2, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        for alias in ("check-android-skill-manifest", "check-react-rn-skill-manifest"):
            args = [str(entry), alias]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, timeout=40)
            done = subprocess.run(args, capture_output=True, cwd=project,
                env=no_python, timeout=40)
            assert reference.returncode in (0, 1), reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            if alias == "check-react-rn-skill-manifest":
                assert done.returncode == 0, done
            checks += 1
        for flags in (["--help"], ["--manifest"], ["--remote-check=한글\u200b"],
                      ["--manifest", "-١", "--help"]):
            args = [str(entry), "check-react-rn-skill-manifest", *flags]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python", "COLUMNS": "80"}, timeout=8)
            done = subprocess.run(args, capture_output=True, cwd=project,
                env={**no_python, "COLUMNS": "80"}, timeout=8)
            assert reference.returncode in (0, 2), reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        numeric_manifest = json.loads(json.dumps(manifest))
        numeric_manifest["skills"][0]["path"] = "NUMERIC_SENTINEL"
        for index, number in enumerate(("18446744073709551616", "[-0,-0.0,NaN,Infinity]")):
            path = base / f"numeric-manifest-{index}.json"
            path.write_text(json.dumps(numeric_manifest).replace('"NUMERIC_SENTINEL"', number))
            args = [str(entry), "check-react-rn-skill-manifest", "--manifest", str(path)]
            reference = subprocess.run(args, capture_output=True, cwd=project,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, timeout=8)
            done = subprocess.run(args, capture_output=True, cwd=project, env=no_python, timeout=8)
            assert reference.returncode == 1, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
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
            connection.execute("PRAGMA journal_mode=WAL")
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
        for state in ("done", "cancelled"):
            with sqlite3.connect(card_db) as connection:
                connection.execute("UPDATE cards SET state='active' WHERE work_id=?", ("a" * 32,))
            done = subprocess.run([str(entry), "work-cards", "--project", str(project), "close", "a" * 32,
                                   "--state", state], capture_output=True, env=no_python, cwd=project, timeout=8)
            expected = (json.dumps({"state": state, "work_id": "a" * 32}, sort_keys=True) + "\n").encode()
            assert (done.returncode, done.stdout, done.stderr) == (0, expected, b""), done
            with sqlite3.connect(card_db) as connection:
                assert connection.execute("SELECT state FROM cards WHERE work_id=?", ("a" * 32,)).fetchone()[0] == state
                assert connection.execute("SELECT state FROM cards WHERE work_id=?", ("b" * 32,)).fetchone()[0] == "done"
            checks += 1
        done = subprocess.run([str(entry), "work-cards", "--project", str(project), "close", "a" * 32],
                              capture_output=True, env=no_python, cwd=project, timeout=8)
        assert (done.returncode, done.stdout, done.stderr) == (2, b"", b"work cards: no active card with that work id in this repository\n"), done
        checks += 1
        checks += _typed_card_snapshot(native, entry, card_db, project, normal, {**no_python, "PATH": str(empty)})
        checks += _card_context(native, entry, base, project, repo_key, normal, empty)
        checks += _card_writes(native, entry, base, project, repo_key, normal, empty)
        checks += _card_bootstrap(native, entry, base, project, normal, empty)
        checks += check_card_resume(entry, base, project, repo_key, normal)
        checks += check_doc_transcript(native, entry, base, project, {**normal,"PATH":str(empty)})
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
        active = advisor / "active-preflight.json"
        active.write_text(json.dumps({"agent_run_id": "portable-active", "work": {"id": "portable"},
            "route": {"command": "build", "gates": ["tests", "review hook", "retrospective check"],
                      "required_docs": ["common/skills/agent-operating-skill/SKILL.md"]}}))
        for output in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--evidence", str(active), "--format", output]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True, env=no_python, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        from agent_gate_evidence import _new_ledger
        active_ledger = _new_ledger(active, json.loads(active.read_text()))
        active_ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
            "fields": {"check": "portable", "result": "1 passed"}, "reuse_snapshot": {"schema_version": 1}}]
        active.with_name("active-preflight-gate-evidence.json").write_text(json.dumps(active_ledger))
        for output in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--evidence", str(active), "--format", output]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True, env=no_python, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        from agent_evidence_inputs import EvidenceInputs
        input_rules = base / "input-rules"
        input_rules.mkdir()
        subprocess.run(["git", "init", "-q", str(input_rules)], env=normal, check=True, capture_output=True)
        (input_rules / "guide.txt").write_text("synthetic rules")
        active_data = json.loads(active.read_text())
        active_data.update(project=str(advisor), rules=str(input_rules))
        active.write_text(json.dumps(active_data))
        with patch.dict(os.environ, normal, clear=True):
            snapshot = {"schema_version": 2, "project": str(advisor), "rules": str(input_rules),
                "input_paths": ["한글 note.py"], "states": {
                    "project": EvidenceInputs.capture(advisor, ["한글 note.py"]),
                    "rules": EvidenceInputs.capture(input_rules, [])}}
        active_ledger = _new_ledger(active, active_data)
        active_ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
            "fields": {"check": "portable", "result": "1 passed"}, "reuse_snapshot": snapshot}]
        active.with_name("active-preflight-gate-evidence.json").write_text(json.dumps(active_ledger))
        for changed in (False, True):
            if changed:
                (advisor / "한글 note.py").write_text("synthetic = 2\n")
            for output in ("json", "markdown"):
                args = [str(entry), "next", "--project", str(advisor), "--evidence", str(active), "--format", output]
                reference = subprocess.run(args, capture_output=True,
                    env={**normal, "MORU_LAUNCHER_BACKEND": "python"}, cwd=advisor, timeout=8)
                done = subprocess.run(args, capture_output=True, env=no_python, cwd=advisor, timeout=8)
                assert reference.returncode == 0 and not reference.stderr, reference
                if output == "json":
                    assert ("tests" in json.loads(reference.stdout)["remaining_gates"]) == changed
                assert (done.returncode, done.stdout, done.stderr) == (
                    reference.returncode, reference.stdout, reference.stderr), done
                checks += 1
        from native_next_support import seed
        session_evidence = seed(advisor, "running")
        (advisor / ".moru/.gitignore").write_text("/*\n")
        for output in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--format", output]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python", "CODEX_THREAD_ID": "synthetic-next"},
                cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True,
                env={**no_python, "CODEX_THREAD_ID": "synthetic-next"}, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            if output == "json":
                assert json.loads(reference.stdout)["evidence"] == str(session_evidence)
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        from agent_run_owner import process_owner
        owner = process_owner()
        assert owner.get("pid", 0) > 0, "transport fixture needs a real process owner"
        peer = session_evidence.parent.parent / ("c" * 32) / "preflight.json"
        peer.parent.mkdir()
        peer.write_text(session_evidence.read_text())
        registry_path = advisor / ".moru/run-registry.json"
        registry = json.loads(registry_path.read_text())
        registry["runs"][0]["owner"] = owner
        registry["runs"].append({"run_id": "c" * 32, "state": "running", "evidence_name": peer.name,
            "evidence_key": hashlib.sha256(peer.relative_to(advisor).as_posix().encode()).hexdigest()})
        registry_path.write_text(json.dumps(registry))
        for output in ("json", "markdown"):
            args = [str(entry), "next", "--project", str(advisor), "--format", output]
            reference = subprocess.run(args, capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python", "CODEX_THREAD_ID": "synthetic-next"},
                cwd=advisor, timeout=8)
            done = subprocess.run(args, capture_output=True,
                env={**no_python, "CODEX_THREAD_ID": "synthetic-next"}, cwd=advisor, timeout=8)
            assert reference.returncode == 0 and not reference.stderr, reference
            if output == "json":
                assert json.loads(reference.stdout)["evidence"] == str(session_evidence)
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        custom = advisor / ".moru/custom/deep/preflight.json"
        custom.parent.mkdir(parents=True)
        session_evidence.rename(custom)
        worker = advisor / ".moru/workers/opaque/preflight.json"
        worker.parent.mkdir(parents=True)
        worker.write_text(custom.read_text())
        registry["runs"] = [registry["runs"][0], {"run_id": "f" * 32, "state": "running",
            "evidence_name": worker.name,
            "evidence_key": hashlib.sha256(worker.relative_to(advisor).as_posix().encode()).hexdigest()}]
        registry["runs"][0]["evidence_key"] = hashlib.sha256(custom.relative_to(advisor).as_posix().encode()).hexdigest()
        registry_path.write_text(json.dumps(registry))
        for selected, scope in ((custom, {}), (worker, {"MORU_WORKER_EVIDENCE": str(worker)})):
            for output in ("json", "markdown"):
                args = [str(entry), "next", "--project", str(advisor), "--format", output]
                reference = subprocess.run(args, capture_output=True,
                    env={**normal, "MORU_LAUNCHER_BACKEND": "python", "CODEX_THREAD_ID": "synthetic-next", **scope},
                    cwd=advisor, timeout=8)
                done = subprocess.run(args, capture_output=True,
                    env={**no_python, "CODEX_THREAD_ID": "synthetic-next", **scope}, cwd=advisor, timeout=8)
                assert reference.returncode == 0 and not reference.stderr, reference
                if output == "json":
                    assert json.loads(reference.stdout)["evidence"] == str(selected)
                assert (done.returncode, done.stdout, done.stderr) == (
                    reference.returncode, reference.stdout, reference.stderr), done
                checks += 1
        relocated = base / "relocated-state"
        (advisor / ".moru").rename(relocated)
        (advisor / ".moru").symlink_to(relocated, target_is_directory=True)
        custom = relocated / "custom/deep/preflight.json"
        worker = relocated / "workers/opaque/preflight.json"
        registry_path = relocated / "run-registry.json"
        for row, path in zip(registry["runs"], (custom, worker)):
            row["evidence_key"] = hashlib.sha256(str(path).encode()).hexdigest()
        registry_path.write_text(json.dumps(registry))
        (relocated / "moru-root").write_text("synthetic marker")
        for active, scope in ((True, {}), (False, {"MORU_WORKER_EVIDENCE": str(worker)})):
            for output in ("json", "markdown"):
                args = [str(entry), "next", "--project", str(advisor), "--format", output]
                reference = subprocess.run(args, capture_output=True,
                    env={**normal, "MORU_LAUNCHER_BACKEND": "python", "CODEX_THREAD_ID": "synthetic-next", **scope},
                    cwd=advisor, timeout=8)
                done = subprocess.run(args, capture_output=True,
                    env={**no_python, "CODEX_THREAD_ID": "synthetic-next", **scope}, cwd=advisor, timeout=8)
                assert reference.returncode == 0 and not reference.stderr, reference
                if output == "json":
                    value = json.loads(reference.stdout)
                    assert value["status"] == ("active_run" if active else "no_active_run")
                    if active:
                        assert value["evidence"] == str(custom)
                assert (done.returncode, done.stdout, done.stderr) == (
                    reference.returncode, reference.stdout, reference.stderr), done
                checks += 1
        for args, columns in ((["--help"], "80"), (["--format=bad"], "80"),
                              (["--help"], "\u2003+٤_٠\u2003"),
                              (["--help"], "1"), (["--format=bad"], "9" * 100)):
            reference = subprocess.run([str(entry), "next", *args], capture_output=True,
                env={**normal, "MORU_LAUNCHER_BACKEND": "python", "COLUMNS": columns}, cwd=advisor, timeout=8)
            done = subprocess.run([str(entry), "next", *args], capture_output=True,
                env={**env, "PATH": str(empty), "COLUMNS": columns}, cwd=advisor, timeout=8)
            assert (done.returncode, done.stdout, done.stderr) == (
                reference.returncode, reference.stdout, reference.stderr), done
            checks += 1
        path_project = base / "next-path-project"
        path_project.mkdir()
        subprocess.run(["git", "init", "-q", str(path_project)], env=normal, check=True)
        path_evidence = seed(path_project, "running")
        (path_project / ".moru/.gitignore").write_text("/*\n")
        (path_project / "-odd;name.py").write_text("synthetic = 1\n")
        dotted = path_evidence.with_name("review.")
        dotted.write_bytes(path_evidence.read_bytes())
        from agent_gate_evidence import gate_evidence_path_for_preflight
        dotted_ledger = _new_ledger(dotted, json.loads(dotted.read_text()))
        dotted_ledger["entries"] = [{"gate": "tests", "status": "SUCCESS", "evidence": "",
            "fields": {"check": "portable", "result": "1 passed"}, "reuse_snapshot": {"schema_version": 1}}]
        gate_evidence_path_for_preflight(dotted).write_text(json.dumps(dotted_ledger))
        non_git = base / "next-non-git"
        non_git.mkdir()
        (non_git / "Cargo.toml").write_text("synthetic\n")
        for target, evidence in ((path_project, None), (path_project, dotted), (non_git, None)):
            for output in ("json", "markdown"):
                args = [str(entry), "next", "--project", str(target), "--format", output]
                if evidence:
                    args += ["--evidence", str(evidence)]
                home_alias = {"HOME": normal["HOME"] + "//."}
                reference = subprocess.run(args, capture_output=True,
                    env={**normal, **home_alias, "MORU_LAUNCHER_BACKEND": "python"}, cwd=target, timeout=15)
                done = subprocess.run(args, capture_output=True,
                    env={**no_python, **home_alias}, cwd=target, timeout=15)
                assert reference.returncode == 0 and (done.returncode, done.stdout, done.stderr) == (
                    reference.returncode, reference.stdout, reference.stderr), (reference, done)
                if evidence and output == "json":
                    assert json.loads(done.stdout)["remaining_gates"] == ["review hook", "retrospective check"]
                checks += 1
        from native_next_ps_support import dead_session_next
        ps_project = base / "ps-project"
        ps_project.mkdir()
        subprocess.run(["git", "init", "-q", str(ps_project)], env=normal, check=True)
        ps_evidence = seed(ps_project, "running")
        (ps_project / ".moru/.gitignore").write_text("/*\n")
        ps_peer = ps_evidence.parent.parent / ("c" * 32) / "preflight.json"
        ps_peer.parent.mkdir()
        ps_peer.write_text(ps_evidence.read_text())
        ps_registry = ps_project / ".moru/run-registry.json"
        payload = json.loads(ps_registry.read_text())
        payload["runs"].append({"run_id": "c" * 32, "state": "running", "evidence_name": ps_peer.name,
            "evidence_key": hashlib.sha256(ps_peer.relative_to(ps_project).as_posix().encode()).hexdigest(),
            "owner": {"pid": 123456789, "start_token": ""}})
        ps_registry.write_text(json.dumps(payload))
        report = dead_session_next(entry, ps_project, base, shutil.which("git"),
            'read parent; printf "%s\\n" "$parent"; exit 7', env=normal, input_bytes=b"123456789\n")
        for index in (0, 2):
            reference, done = report["calls"][index:index + 2]
            assert reference["returncode"] == 0 and reference == done, (reference, done)
            if index == 0:
                assert json.loads(reference["stdout"])["evidence"] == str(ps_peer)
            checks += 1
        assert report["argv"] == ["-o", "ppid=", "-p", str(report["sid"])] * 4
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
