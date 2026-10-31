"""Isolated generated pretool entrypoints; no live sessions or transcripts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from native_launcher_support import install

PROJECT = Path(__file__).resolve().parents[1]


def environment(base, source=PROJECT):
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("MORU_", "GIT_", "CODEX_", "CLAUDE_", "AGY_", "ANTIGRAVITY_", "SPILL_", "PYTHON", "_PYTHON"))}
    env.update(HOME=str(base / "home"), MORU_HOME=str(source), MORU_STATE_HOME=str(base / "state"),
               MORU_LAUNCHER_BACKEND="auto", MORU_HOOK_SOFT_FAIL="0", PYTHONUTF8="1",
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return env


def prepare(base, source=PROJECT):
    home = base / "home"
    project = base / "project space 한글"
    home.mkdir()
    project.mkdir()
    (project / ".moru").mkdir()
    (project / "AGENTS.md").write_text("uses moru-hook\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True,
                   capture_output=True, env=environment(base, source), timeout=5)
    with patch.dict(os.environ, environment(base, source), clear=True):
        install(home, source)
    return home / ".moru/bin/moru-hook", project


def request(project, command="git status --short", **fields):
    return {"tool_name": "Bash", "cwd": str(project), "session_id": "synthetic-pretool",
            "tool_input": {"command": command}, **fields}


def encode(payload):
    return json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, dict) else payload


def invoke(launcher, base, project, alias, payload, *, backend="auto", source=PROJECT, **overrides):
    env = environment(base, source)
    env.update(MORU_LAUNCHER_BACKEND=backend, **overrides)
    return subprocess.run([str(launcher), alias], input=encode(payload), capture_output=True,
                          env=env, cwd=project, timeout=8)


def result(done):
    return done.returncode, done.stdout, done.stderr
