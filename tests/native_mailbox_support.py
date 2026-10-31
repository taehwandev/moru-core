"""Synthetic generated mailbox callbacks and reversible local state snapshots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

from native_pretool_support import PROJECT, encode, environment, prepare, result


def invoke(launcher, base, project, runtime="claude", action="deliver", *, backend="auto",
           payload=None, args=None, **overrides):
    env = environment(base)
    env.update(MORU_LAUNCHER_BACKEND=backend, **overrides)
    payload = {"cwd": str(project), "session_id": "synthetic-mailbox"} if payload is None else payload
    args = ["mailbox-hook", action, "--runtime", runtime] if args is None else args
    return subprocess.run([str(launcher), *args], input=encode(payload), capture_output=True,
                          cwd=project, env=env, timeout=8)


def warm(launcher, base, project, runtime="claude"):
    first = invoke(launcher, base, project, runtime, backend="python")
    assert first.returncode == 0 and b"Current shared continuation guidance" in first.stdout, result(first)
    assert result(invoke(launcher, base, project, runtime, backend="python")) == (0, b"", b"")


def reference(base, project):
    from agent_mailbox_reference import ReferenceMailboxStore
    with patch.dict(os.environ, environment(base), clear=True):
        return ReferenceMailboxStore(project)


def snapshot(base, project):
    data = {}
    for root in (project / ".moru", base / "state"):
        paths = [root, *root.rglob("*")] if root.exists() else []
        for path in paths:
            relative = str(path.relative_to(base))
            data[relative] = ("link", os.readlink(path)) if path.is_symlink() else (
                ("dir", None) if path.is_dir() else ("file", path.read_bytes()))
    return data


def restore(base, project, data):
    for root in (project / ".moru", base / "state"):
        if root.is_symlink(): root.unlink()
        elif root.exists(): shutil.rmtree(root)
    for relative, (kind, content) in sorted(data.items(), key=lambda row: len(Path(row[0]).parts)):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "dir": path.mkdir(exist_ok=True)
        elif kind == "link": path.symlink_to(content)
        else: path.write_bytes(content)


def stable(data):
    """Only generated receipt/lease clock values vary across serial executions."""
    out = dict(data)
    for path, (kind, content) in data.items():
        if kind != "file" or not path.endswith(".json"): continue
        try: value = json.loads(content)
        except (ValueError, UnicodeError): continue
        if isinstance(value, dict):
            for key in ("consumed_at", "leased_at", "expires_at"):
                if key in value: value[key] = "<clock>"
            out[path] = (kind, json.dumps(value, sort_keys=True))
    return out
