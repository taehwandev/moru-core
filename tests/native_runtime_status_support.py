"""Prepared synthetic status state and real generated entrypoint calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from native_pretool_support import PROJECT, environment, prepare
from runtime_snapshot_normalize import normalize_output


def seed(project):
    for name, value in {
        "run-registry.json": {"runs": [{"state": "running"}, {"state": "paused"}, {"state": "completed"}]},
        "scheduler.json": {"tasks": [{"state": "queued"}, {"state": "completed"}]},
        "events.json": {"events": [{"event_type": "run.started"}, None]},
    }.items():
        (project / ".moru" / name).write_text(json.dumps(value))


def prepared(base, source=PROJECT):
    entry, project = prepare(base, source)
    seed(project)
    done = invoke(entry, base, project, backend="python", source=source)
    if done.returncode or done.stderr:
        raise RuntimeError("status fixture preparation failed")
    return entry, project


def invoke(entry, base, project, args=None, *, backend="auto", source=PROJECT, **overrides):
    env = environment(base, source)
    env.update(MORU_LAUNCHER_BACKEND=backend, **overrides)
    return subprocess.run([str(entry), "agent-os-status", *(args if args is not None else
        ["--project", str(project)])], env=env, cwd=project, capture_output=True, timeout=8)


def comparable(done, validated=False):
    if done.returncode or done.stderr:
        return done.returncode, done.stdout, done.stderr
    return done.returncode, normalize_output(done.stdout, "validated_status" if validated else "status"), done.stderr


def state_hashes(project):
    return {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (project / ".moru").rglob("*") if p.is_file()}


def install_snapshot(base, home, source):
    """Use each frozen version's installer, including its original shell header."""
    env = environment(base, source)
    env.update(HOME=str(home))
    code = ("import sys; from pathlib import Path; "
            "sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts')); "
            "from support.stable_launcher import ensure_stable_launcher; "
            "ensure_stable_launcher(Path(sys.argv[1]), dry_run=False)")
    subprocess.run([sys.executable, "-B", "-c", code, str(source)],
                   env=env, capture_output=True, check=True, timeout=10)
    return home / ".moru/bin/moru-hook", env
