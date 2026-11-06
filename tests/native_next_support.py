"""Synthetic next-advisor state and real generated launcher calls."""
import hashlib
import json
from pathlib import Path
import subprocess

from native_pretool_support import PROJECT, environment, prepare


def prepare_next(base, source=PROJECT):
    launcher, project = prepare(base, source)
    quiet_project(project)
    done = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                          cwd=project, env=environment(base, source), capture_output=True, check=True)
    if done.stdout:
        raise AssertionError("quiet-next fixture must have no changed files")
    return launcher, project


def quiet_project(project):
    (project / ".moru/.gitignore").write_text("/*\n")
    with (project / ".git/info/exclude").open("a") as stream:
        stream.write("\nAGENTS.md\n")


def seed(project, state="completed"):
    local = project / ".moru"
    local.mkdir(exist_ok=True)
    for name in (".state.lock.lock", ".run-registry.json.lock"):
        (local / name).touch()
    run_id = "a" * 32
    path = local / "runs" / run_id / "preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"agent_run_id": run_id, "work": {"id": "b" * 32},
        "runtime_session": {"runtime": "codex", "session_id": "synthetic-next"},
        "route": {"command": "small-change", "gates": ["tests", "review hook", "retrospective check"],
                  "required_docs": ["common/skills/agent-operating-skill/SKILL.md"]}}))
    key = hashlib.sha256(path.relative_to(project).as_posix().encode()).hexdigest()
    (local / "run-registry.json").write_text(json.dumps({"schema_version": 1, "runs": [
        {"run_id": run_id, "state": state, "evidence_name": "preflight.json", "evidence_key": key}]}))
    return path


def invoke_next(launcher, base, project, args=None, *, backend="auto", source=PROJECT, **overrides):
    env = environment(base, source)
    env.update(MORU_LAUNCHER_BACKEND=backend, **overrides)
    return subprocess.run([str(launcher), "next", *(args if args is not None else
        ["--project", str(project), "--format", "json"])], stdin=subprocess.DEVNULL, capture_output=True,
        cwd=project, env=env, timeout=15)
