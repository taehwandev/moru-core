"""Optional native ingress installation; no build or network at setup time.

Owner: verified local launcher artifact. Allowed: stdlib and ignored build
receipt. Forbidden: compiling/downloading, policy changes, global state on import.
Callers/tests: stable_launcher / test_native_stable_launcher.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from support.native_source_inputs import source_inputs


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_plan(root: Path, launcher: Path) -> dict | None:
    package = root / "native" / "checkout-identity"
    state = root / ".moru" / "native"
    try:
        receipt = json.loads((state / "build.json").read_text())
        files = source_inputs(root)
        expected = {str(p.relative_to(root)) for p in files}
        hashes = receipt["source_sha256"]
        if set(hashes) != expected or any(_digest(root / p) != hashes[p] for p in expected):
            return None
        source = state / "bin" / "moru-native-launcher"
        digest = receipt["launcher"]["sha256"]
        if not source.is_file() or not os.access(source, os.X_OK) or _digest(source) != digest:
            return None
        return {"source": source, "destination": launcher.parent / "moru-hook-native", "sha256": digest}
    except (OSError, ValueError, KeyError, TypeError, ImportError, SyntaxError, AttributeError):
        return None


def installed_matches(plan: dict) -> bool:
    target = plan["destination"]
    try:
        return (not target.is_symlink() and target.is_file() and os.access(target, os.X_OK)
                and _digest(target) == plan["sha256"])
    except OSError:
        return False


def install_native(plan: dict) -> None:
    target = plan["destination"]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".moru-native-", delete=False) as file:
            temporary = Path(file.name)
        shutil.copyfile(plan["source"], temporary)
        if _digest(temporary) != plan["sha256"]:
            raise RuntimeError("native launcher changed during installation")
        temporary.chmod(0o755)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def native_launcher_header() -> str:
    # Also a valid Python string literal: explicit `python3 moru-hook` keeps
    # its original in-process path without interpreting any shell statements.
    return '''#!/bin/sh
""":"
case "$0" in
    */*) launcher_dir=${0%/*} ;;
    *) launcher_dir=. ;;
esac
native="$launcher_dir/moru-hook-native"
case "${MORU_LAUNCHER_BACKEND:-auto}" in
    auto|rust)
        if [ "${MORU_LAUNCHER_BACKEND:-auto}" = auto ]; then
            case "${1-}" in
                checkout-identity|claude-statusline|agy-statusline|claude-pretool-gate|codex-pretool-gate) ;;
                *) exec python3 "$0" "$@" ;;
            esac
        fi
        if [ -f "$native" ] && [ -x "$native" ]; then
            exec "$native" "$0" "$@"
        fi
        if [ "${MORU_LAUNCHER_BACKEND:-auto}" = rust ]; then
            printf '%s\\n' 'native launcher missing; select python to roll back' >&2
            exit 127
        fi
        ;;
    python) ;;
    *) printf '%s\\n' 'invalid MORU_LAUNCHER_BACKEND' >&2; exit 2 ;;
esac
exec python3 "$0" "$@"
":"""
'''
