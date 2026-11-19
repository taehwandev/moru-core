"""Bounded private native JSON transport, with no policy or fallback algorithms.

Owner: NativeProbe. Allowed: stdlib and caller-owned output streams. Forbidden:
opening state/config files, installers, model calls and decision rules. Callers/tests: completion and registry adapters;
test_native_completion and test_native_registry_read verify real protocols.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import BinaryIO


class NativeProbe:
    @staticmethod
    def available() -> bool:
        return (os.environ.get("MORU_LAUNCHER_BACKEND") != "python"
                and (Path.home() / ".moru/bin/moru-hook-native").is_file())

    @staticmethod
    def request(protocol: str, operation: str, payload: dict) -> dict | None:
        if protocol not in {"--completion-probe", "--registry-read-probe", "--overhead-probe", "--cards-probe", "--doc-transcript-probe", "--memory-probe", "--setup-probe"}:
            return None
        write_failure = {
            ("--completion-probe", "pending-publication-replace"): "native receipt replacement outcome could not be determined",
            ("--doc-transcript-probe", "write-marker"): "native delivery marker outcome could not be determined",
            ("--doc-transcript-probe", "agy-redelivery"): "native redelivery outcome could not be determined",
            ("--doc-transcript-probe", "agy-prepared-delivery"): "native prepared delivery outcome could not be determined",
        }.get((protocol, operation))
        done = NativeProbe._invoke(protocol, operation, payload, subprocess.PIPE, write_failure=write_failure)
        if done is None:
            return None
        try:
            if len(done.stdout) <= 1024 * 1024:
                value = json.loads(done.stdout)
                if (isinstance(value, dict) and set(value) == {"schema_version", "result"}
                        and type(value["schema_version"]) is int and value["schema_version"] == 1
                        and isinstance(value["result"], dict)):
                    return value["result"]
        except (ValueError, TypeError):
            pass
        if write_failure:
            raise OSError(write_failure)
        return None

    @staticmethod
    def encode_publication_receipt(payload: dict, output: BinaryIO) -> bool:
        return NativeProbe._invoke("--completion-probe", "pending-publication-encode", payload, output) is not None

    @staticmethod
    def _invoke(protocol: str, operation: str, payload: dict, stdout, *,
                write_failure: str | None = None) -> subprocess.CompletedProcess | None:
        if not NativeProbe.available():
            return None
        entry = Path.home() / ".moru/bin/moru-hook"
        try:
            raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
        except (ValueError, TypeError):
            return None
        if len(raw) > 1024 * 1024:
            return None
        try:
            done = subprocess.run([str(entry.with_name("moru-hook-native")), str(entry), protocol, operation],
                                  input=raw, stdout=stdout, stderr=subprocess.PIPE, timeout=10,
                                  env={**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])})
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            if write_failure:
                raise OSError(write_failure) from None
            return None
        if done.returncode == 0 and not done.stderr:
            return done
        if write_failure and (done.returncode, done.stdout, done.stderr) != (125, b"", b""):
            raise OSError(write_failure)
        return None
