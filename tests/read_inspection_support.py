"""Synthetic state and generated entrypoints for read-inspection measurement."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

from native_launcher_support import install
from native_pretool_support import encode, environment, prepare, request
from runtime_snapshot_normalize import normalize_output


def fixtures(base, roots):
    _entry, project = prepare(base, roots["reference"])
    (project / "notes.txt").write_text("TODO synthetic\n")
    (project / "한글 메모.txt").write_text("TODO synthetic\n")
    for name, payload in {
        "run-registry.json": {"runs": [{"state": "running"}, {"state": "paused"}, {"state": "completed"}]},
        "scheduler.json": {"tasks": [{"state": "queued"}, {"state": "completed"}]},
        "events.json": {"events": [{"event_type": "run.started"}, None]},
    }.items():
        (project / ".moru" / name).write_text(json.dumps(payload))
    git = subprocess.run(["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True, check=True)
    repo = hashlib.sha256(git.stdout.strip().encode()).hexdigest()[:24]
    entries, envs = {}, {}
    for variant, root in roots.items():
        home = base / ("home-" + variant)
        install(home, root)
        entries[variant] = home / ".moru/bin/moru-hook"
        envs[variant] = environment(base, root)
        envs[variant].update(HOME=str(home))
        store = base / ("full-" + variant) / "work-cards"
        store.mkdir(parents=True)
        with sqlite3.connect(store / "cards.sqlite3") as connection:
            connection.execute("CREATE TABLE cards (repo TEXT, work_id TEXT, summary TEXT, command TEXT, "
                "project TEXT, state TEXT, created_at TEXT, updated_at TEXT, run_id TEXT, runtime TEXT, session_id TEXT)")
            connection.execute("PRAGMA user_version=3")
            connection.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (repo, f"{n:032x}", f"synthetic card {n}", "build", str(project), "active" if n % 2 else "done",
                 "2026-10-31T00:00:00+00:00", f"2026-10-31T00:00:{n % 60:02}+00:00", "", "", "")
                for n in range(100)])
    empty = base / "empty-path"
    empty.mkdir()
    cases = [("claude_tail", ["claude-pretool-gate"], encode(request(project, "tail -n 20 notes.txt"))),
             ("codex_wc", ["codex-pretool-gate"], encode(request(project, "wc -l notes.txt"))),
             ("claude_sed", ["claude-pretool-gate"], encode(request(project, "sed -n '1,120p' '한글 메모.txt'"))),
             ("native_cat_control", ["claude-pretool-gate"], encode(request(project, "cat notes.txt"))),
             ("status", ["agent-os-status", "--project", str(project)], b""),
             ("validated_status", ["agent-os-status", "--project", str(project), "--validate"], b""),
             ("cards_empty", ["work-cards", "--project", str(project), "list"], b""),
             ("cards_full", ["work-cards", "--project", str(project), "list", "--all"], b"")]
    for name, args, data in cases:
        for variant in roots:
            env = case_environment(base, envs[variant], name, variant)
            done = subprocess.run([str(entries[variant]), *args], input=data, capture_output=True,
                                  env=env, cwd=project, timeout=10)
            comparable(done, name)
            if name in ("claude_tail", "codex_wc", "claude_sed", "native_cat_control") and variant == "candidate":
                proof = subprocess.run([str(entries[variant]), *args], input=data, capture_output=True,
                    env={**env, "PATH": str(empty)}, cwd=project, timeout=10)
                assert comparable(proof, name) == comparable(done, name)
    return project, entries, envs, cases


def case_environment(base, env, name, variant):
    if name.startswith("cards_"):
        kind = "full" if name == "cards_full" else "none"
        return {**env, "MORU_STATE_HOME": str(base / (kind + "-" + variant))}
    return env


def comparable(done, name):
    if done.returncode or done.stderr:
        raise RuntimeError(f"callback failed: {name}: {done.returncode}, {done.stderr!r}")
    if name in ("status", "validated_status"):
        return normalize_output(done.stdout, name)
    if name.startswith("cards_"):
        cards = json.loads(done.stdout)
        if not isinstance(cards, list) or len(cards) != (100 if name == "cards_full" else 0):
            raise RuntimeError("unexpected work-card fixture output")
    elif done.stdout:
        raise RuntimeError("quiet pretool emitted output")
    return done.stdout


def state_hashes(base, project):
    roots = [project / ".moru", *[base / (prefix + "-" + variant)
             for prefix in ("full", "none") for variant in ("reference", "candidate")]]
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in roots for p in root.rglob("*") if p.is_file()}


def cache_hashes(base):
    return {v: {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (base / ("cache-" + v)).rglob("*.pyc")}
            for v in ("reference", "candidate")}


def prepare_cache(base, entries, envs, cases, project):
    hits = {}
    for variant, entry in entries.items():
        prefix = str(base / ("cache-" + variant))
        envs[variant]["PYTHONPYCACHEPREFIX"] = prefix
        for name, args, data in cases:
            env = case_environment(base, envs[variant], name, variant)
            done = subprocess.run([str(entry), *args], input=data, capture_output=True, cwd=project,
                env={**env, "MORU_LAUNCHER_BACKEND": "python", "PYTHONDONTWRITEBYTECODE": "0"}, timeout=10)
            comparable(done, name)
            if name in ("status", "cards_full"):
                probe = subprocess.run([str(entry), *args], input=data, capture_output=True, cwd=project,
                    env={**env, "PYTHONVERBOSE": "1"}, timeout=10)
                owner = ("agent_observability" if name == "status" else
                         "agent_project_memory" if variant == "reference" else "agent_repository_key")
                hit = any(prefix in line and owner in line and ".pyc matches " in line
                          for line in probe.stderr.decode().splitlines())
                if probe.returncode or not hit:
                    raise RuntimeError(f"cache-hit proof failed: {variant}/{name}")
                hits[variant + "/" + name] = True
    if any(not files for files in cache_hashes(base).values()):
        raise RuntimeError("callback cache preparation produced no caches")
    return hits
