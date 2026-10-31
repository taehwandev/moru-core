#!/usr/bin/env python3
"""Build the checkout runtime locally, using installed tools and cached crates.

Owner: offline artifact build/publication inside ignored project state.
Allowed: stdlib, Cargo, rustc. Forbidden: downloads, global install/config writes.
Callers/tests: developers and test_build_native_runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT / "native" / "checkout-identity"
STATE = PROJECT / ".moru" / "native"
NAME = "moru-checkout-identity"


def build() -> dict:
    if os.name != "posix":
        raise RuntimeError("this migration stage supports POSIX hosts only")
    if not shutil.which("cargo") or not shutil.which("rustc"):
        raise RuntimeError("build needs an installed Rust toolchain; no tools are installed automatically")
    state = STATE
    state.mkdir(parents=True, exist_ok=True)
    target = state / "cargo-target"
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    argv = ["cargo", "build", "--release", "--locked", "--offline",
            "--manifest-path", str(PACKAGE / "Cargo.toml")]
    with (state / "build.log").open("wb") as log:
        subprocess.run(argv, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    source = target / "release" / NAME
    subprocess.run([str(source)], input=b"", capture_output=True, check=True, timeout=5)
    destination = state / "bin" / NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".checkout-", delete=False) as file:
            temporary = Path(file.name)
        shutil.copyfile(source, temporary)
        temporary.chmod(0o755)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    version = subprocess.check_output(["rustc", "--version"], text=True).strip()
    sources = [PACKAGE / "Cargo.toml", PACKAGE / "Cargo.lock", *sorted((PACKAGE / "src").glob("*.rs"))]
    result = {"binary": str(destination), "bytes": destination.stat().st_size,
              "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "rustc": version,
              "source_sha256": {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources}}
    (state / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
