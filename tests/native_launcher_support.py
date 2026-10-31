"""Owned temporary homes, fixture roots and actual native launcher invocations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

from checkout_identity_support import PROJECT, environment
from support.stable_launcher import ensure_stable_launcher

NATIVE = PROJECT / ".moru/native/bin/moru-native-launcher"


def install(home, root=PROJECT, dry_run=False):
    with patch("support.stable_launcher.Path.home", return_value=Path(home)):
        return ensure_stable_launcher(root, dry_run)


def run_launcher(launcher, home, *args, data=b"", backend="auto", metadata="auto",
                 soft="0", path=None, cwd=None, **overrides):
    env = environment(metadata, path)
    env.update(HOME=str(home), MORU_HOME=str(PROJECT), MORU_LAUNCHER_BACKEND=backend,
               MORU_HOOK_SOFT_FAIL=soft)
    env.update(overrides)
    return subprocess.run([str(launcher), *args], input=data, capture_output=True,
                          env=env, cwd=cwd, timeout=8)


def fixture_root(path, body):
    path = Path(path)
    (path / "scripts").mkdir(parents=True, exist_ok=True)
    (path / "AGENTS.md").write_text("fixture\n")
    (path / "index.md").write_text("fixture\n")
    (path / "scripts/workflow.py").write_text(body)
    return path


def copied_build_root(path):
    path = Path(path)
    receipt = json.loads((PROJECT / ".moru/native/build.json").read_text())
    for relative in receipt["source_sha256"]:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / relative, target)
    state = path / ".moru/native"
    (state / "bin").mkdir(parents=True)
    shutil.copy2(NATIVE, state / "bin" / NATIVE.name)
    (state / "build.json").write_text(json.dumps(receipt))
    return path
