"""Owned synthetic state and isolated environments for startup checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from agent_ipc import events_path
from agent_run_registry import registry_path
from agent_scheduler import scheduler_path
from support.global_state import project_state_dir_target

PROJECT = Path(__file__).resolve().parents[1]


def environment(base, source=PROJECT):
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("MORU_", "GIT_", "CODEX_", "CLAUDE_", "ANTIGRAVITY_", "AGY_"))}
    env.update(HOME=str(base / "home"), MORU_HOME=str(source),
               MORU_STATE_HOME=str(base / "home/.moru"), MORU_HOOK_SOFT_FAIL="0",
               MORU_LAUNCHER_BACKEND="auto", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return env


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def prepare(base):
    (base / "home").mkdir()
    project = base / "project"
    project.mkdir()
    env = environment(base)
    subprocess.run(["git", "init", "-q", str(project)], env=env, check=True, capture_output=True)
    with patch.dict(os.environ, env, clear=True):
        write_json(registry_path(project), {"runs": [{"state": "running"}, {"state": "completed"}]})
        write_json(scheduler_path(project), {"tasks": [{"state": "queued"}, {"state": "done"}]})
        write_json(events_path(project), {"events": [{"event_type": "task"}]})
        active = project_state_dir_target(project) / "runs" / ("a" * 32) / "preflight.json"
    write_json(active, {"agent_run_id": "a" * 32, "work": {"id": "b" * 32},
        "route": {"command": "small-change", "gates": ["tests", "review hook", "retrospective check"],
                  "required_docs": ["common/skills/agent-operating-skill/SKILL.md"]}})
    return project, active
