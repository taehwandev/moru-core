"""Bounded private native JSON transport, with no policy or fallback algorithms.

Owner: NativeProbe. Allowed: stdlib. Forbidden: state/config writes, installers,
model calls and decision rules. Callers/tests: completion and registry adapters;
test_native_completion and test_native_registry_read verify real protocols.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


class NativeProbe:
    @staticmethod
    def available() -> bool:
        return (os.environ.get("MORU_LAUNCHER_BACKEND") != "python"
                and (Path.home() / ".moru/bin/moru-hook-native").is_file())

    @staticmethod
    def request(protocol: str, operation: str, payload: dict) -> dict | None:
        if protocol not in {"--completion-probe", "--registry-read-probe", "--overhead-probe", "--cards-probe", "--doc-transcript-probe", "--memory-probe"} or not NativeProbe.available():
            return None
        entry = Path.home() / ".moru/bin/moru-hook"
        try:
            raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
            if len(raw) > 1024 * 1024:
                return None
            done = subprocess.run([str(entry.with_name("moru-hook-native")), str(entry), protocol, operation],
                input=raw, capture_output=True, timeout=10,
                env={**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])})
            if done.returncode or done.stderr or len(done.stdout) > 1024 * 1024:
                return None
            value = json.loads(done.stdout)
            if (not isinstance(value, dict) or set(value) != {"schema_version", "result"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1):
                return None
            return value["result"] if isinstance(value["result"], dict) else None
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            return None
