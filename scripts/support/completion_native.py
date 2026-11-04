"""Bounded transport to native completion policy; contains no decision rules.

Owner: private native protocol. Allowed: stdlib. Forbidden: execution of checks,
state writes, installation, fallback algorithms, caches and model calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def completion_available() -> bool:
    return (os.environ.get("MORU_LAUNCHER_BACKEND") != "python"
            and (Path.home() / ".moru/bin/moru-hook-native").is_file())


def completion_native(operation: str, payload: dict) -> dict | None:
    if not completion_available():
        return None
    entry = Path.home() / ".moru/bin/moru-hook"
    binary = entry.with_name("moru-hook-native")
    try:
        raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
        if len(raw) > 1024 * 1024:
            return None
        result = subprocess.run([str(binary), str(entry), "--completion-probe", operation],
            input=raw, capture_output=True, timeout=10,
            env={**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])})
        if result.returncode or result.stderr or len(result.stdout) > 1024 * 1024:
            return None
        value = json.loads(result.stdout)
        if set(value) != {"schema_version", "result"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            return None
        return value["result"] if isinstance(value["result"], dict) else None
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None
