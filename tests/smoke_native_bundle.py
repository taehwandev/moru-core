#!/usr/bin/env python3
"""Verify a transported bundle in a fresh root/home with no compiler or Python PATH."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from startup_path_support import PROJECT, environment
from support.native_bundle import install_bundle
from support.stable_launcher import ensure_stable_launcher


def smoke(archive):
    with tempfile.TemporaryDirectory(prefix="native-consumer-") as tmp:
        base = Path(tmp).resolve()
        root = base / "transported root"
        shutil.copytree(PROJECT / "native/checkout-identity", root / "native/checkout-identity",
                        ignore=shutil.ignore_patterns("target"))
        (root / "scripts").mkdir()
        for marker in ("AGENTS.md", "index.md", "scripts/workflow.py"):
            (root / marker).write_text("# Source root marker\n")
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
        print("PASS: transported checkout and both statuslines; empty PATH has no Python, Rust or Cargo")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    smoke(parser.parse_args().bundle)
