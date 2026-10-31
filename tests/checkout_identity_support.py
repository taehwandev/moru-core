"""Real Git fixtures and clean process environments for the checkout runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
WRAPPER = PROJECT / "scripts" / "moru-checkout-identity"
BINARY = PROJECT / ".moru" / "native" / "bin" / "moru-checkout-identity"
PYTHON = [sys.executable, "-B", str(PROJECT / "scripts" / "checkout_identity.py")]
LIMIT = 1024 * 1024


def environment(backend="auto", path=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(MORU_CHECKOUT_IDENTITY_BACKEND=backend, GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", LC_ALL="C", LANG="C")
    if path is not None:
        env["PATH"] = str(path)
    return env


def git(*args):
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True, env=environment())


def request(root):
    return (json.dumps({"schema_version": 1, "root": str(root)}) + "\n").encode()


def invoke(command, payload=b"", *, backend="auto", path=None, timeout=12):
    return subprocess.run(command, input=payload, capture_output=True,
                          env=environment(backend, path), timeout=timeout)


def rows(result):
    if result.returncode or result.stderr:
        raise AssertionError(f"exit={result.returncode} stderr={result.stderr[:500]!r}")
    return [json.loads(line) for line in result.stdout.splitlines()]


class CheckoutFixtures:
    def __init__(self, base):
        self.base = Path(base).resolve()
        self.main = self.base / "main"
        git("init", "-q", "-b", "main", self.main)
        git("-C", self.main, "-c", "user.name=fixture", "-c", "user.email=t@example.invalid",
            "commit", "-q", "--allow-empty", "-m", "fixture")
        self.linked = self.base / "linked"
        self.detached = self.base / "detached"
        self.relative = self.base / "relative"
        git("-C", self.main, "worktree", "add", "-q", "-b", "task/linked", self.linked)
        git("-C", self.main, "worktree", "add", "-q", "--detach", self.detached)
        git("-C", self.main, "worktree", "add", "-q", "-b", "task/relative", self.relative)
        marker = self.relative / ".git"
        target = Path(marker.read_text().split("gitdir:", 1)[1].strip())
        marker.write_text("gitdir: " + os.path.relpath(target, self.relative) + "\n")
        bare = self.base / "bare"
        git("init", "-q", "--bare", bare)
        nested = self.main / "nested"
        empty = self.base / "empty"
        malformed = self.base / "malformed"
        for path in (nested, empty, malformed):
            path.mkdir()
        (malformed / ".git").write_text("bad metadata\n")
        unicode = self.base / "unicode 한글"
        git("init", "-q", "-b", "기능/검색", unicode)
        symlink = self.base / "symlink"
        symlink.symlink_to(self.main, target_is_directory=True)
        self.roots = [self.main, self.linked, self.detached, self.relative, bare, nested,
                      empty, malformed, self.base / "missing", unicode, symlink]
