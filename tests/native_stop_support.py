"""Actual Stop callbacks using synthetic completed state and isolated user stores."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from native_pretool_support import PROJECT, encode, environment, prepare, result
from native_mailbox_support import warm


def invoke(launcher, base, project, runtime="claude", *, payload=None, backend="auto", extra=(), **overrides):
    env = environment(base)
    env.update(MORU_LAUNCHER_BACKEND=backend, **overrides)
    payload = {"cwd": str(project), "session_id": "synthetic-stop"} if payload is None else payload
    return subprocess.run([str(launcher), runtime + "-stop-gate", *extra], input=encode(payload),
                          capture_output=True, cwd=project, env=env, timeout=8)


def prepare_stop(base, source=PROJECT):
    launcher, project = prepare(base, source)
    seed_stop(launcher, base, project, source)
    return launcher, project


def seed_stop(launcher, base, project, source=PROJECT):
    from agent_run_registry import register_run, transition_run
    with patch.dict(os.environ, environment(base, source), clear=True):
        # A completed registry models ordinary repeated Stop after a task.
        evidence = project / ".moru/preflight.json"
        register_run(project, evidence, {"command": "task", "gates": []}, {"request": "synthetic fixture"})
        transition_run(project, evidence, "completed")
    for runtime in ("claude", "codex"):
        warm(launcher, base, project, runtime)


def markers(project, session="synthetic-stop", *, closed=True):
    directory = project / ".moru/claude-pretool-gate"
    directory.mkdir(parents=True, exist_ok=True)
    edited = directory / (session + ".edited")
    edited.write_text("")
    os.utime(edited, ns=(100000000000, 100000000000))
    if closed:
        finished = directory / (session + ".finished")
        finished.write_text("")
        os.utime(finished, ns=(200000000000, 200000000000))


def active_work(base):
    from test_agent_run_interruption import Run
    from agent_continuation_checkpoint import write_continuation_checkpoint
    directory = base / "active-case"
    directory.mkdir()
    with patch.dict(os.environ, environment(base), clear=True):
        run = Run(str(directory), "codex", packet=True, writable=True)
        write_continuation_checkpoint(project=run.project, rules=run.project,
            run_id=run.run["run_id"], binding_path=run.evidence, kind="initial", phase="acting",
            work={"objective": "Complete the approved synthetic delivery",
                  "remaining_work": [{"checkpoint": "delivery", "action": "Deliver remaining fixture outputs"}]})
    return {"cwd": str(run.project), "session_id": "bound-session"}


def stable_state(data):
    def scrub(value):
        if isinstance(value, dict):
            return {key: ("<clock>" if key in ("updated_at", "consumed_at", "leased_at", "expires_at")
                          else scrub(item)) for key, item in value.items()}
        if isinstance(value, list): return [scrub(item) for item in value]
        return value
    out = dict(data)
    for path, (kind, content) in data.items():
        if kind != "file" or not path.endswith(".json"): continue
        try: out[path] = (kind, json.dumps(scrub(json.loads(content)), sort_keys=True))
        except (ValueError, UnicodeError): pass
    return out
