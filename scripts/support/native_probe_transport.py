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
    def request(
        protocol: str, operation: str, payload: dict, *, verified_launcher: Path | None = None,
    ) -> dict | None:
        if protocol not in {"--completion-probe", "--registry-read-probe", "--overhead-probe", "--cards-probe", "--doc-transcript-probe", "--memory-probe", "--setup-probe", "--workflow-query-probe", "--decision-cache-probe"}:
            return None
        if verified_launcher is not None and (protocol, operation) != ("--completion-probe", "doctor-launcher"):
            return None
        write_failure = {
            ("--completion-probe", "live-web-edit-append"): "native live-web edit append outcome could not be determined",
            ("--completion-probe", "live-web-edit-record"): "native live-web edit record outcome could not be determined",
            ("--completion-probe", "live-web-edit-hook"): "native live-web edit hook outcome could not be determined",
            ("--completion-probe", "path-claim-write"): "native path claim write outcome could not be determined",
            ("--completion-probe", "path-claim-write-batch"): "native path claim batch outcome could not be determined",
            ("--completion-probe", "path-claim-release"): "native path claim release outcome could not be determined",
            ("--completion-probe", "path-claim-release-selected"): "native path claim release outcome could not be determined",
            ("--completion-probe", "path-claim-expire"): "native path claim expiry outcome could not be determined",
            ("--completion-probe", "path-claim-expire-batch"): "native path claim expiry outcome could not be determined",
            ("--completion-probe", "lesson-compaction-apply"): "native lesson compaction outcome could not be determined",
            ("--completion-probe", "lesson-compaction-mark-stale"): "native lesson stale marking outcome could not be determined",
            ("--completion-probe", "lesson-compaction-write-batch"): "native lesson compaction batch outcome could not be determined",
            ("--completion-probe", "capsule-refresh"): "native execution capsule refresh outcome could not be determined",
            ("--completion-probe", "capsule-replace"): "native execution capsule replacement outcome could not be determined",
            ("--completion-probe", "pending-publication-replace"): "native receipt replacement outcome could not be determined",
            ("--doc-transcript-probe", "write-marker"): "native delivery marker outcome could not be determined",
            ("--doc-transcript-probe", "agy-redelivery"): "native redelivery outcome could not be determined",
            ("--doc-transcript-probe", "agy-prepared-delivery"): "native prepared delivery outcome could not be determined",
            ("--decision-cache-probe", "write-cached-file"): "native decision cache write outcome could not be determined",
        }.get((protocol, operation))
        done = NativeProbe._invoke(protocol, operation, payload, subprocess.PIPE,
                                  write_failure=write_failure, verified_launcher=verified_launcher)
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
                write_failure: str | None = None,
                verified_launcher: Path | None = None) -> subprocess.CompletedProcess | None:
        if os.environ.get("MORU_LAUNCHER_BACKEND") == "python":
            return None
        if verified_launcher is None and not NativeProbe.available():
            return None
        entry = Path.home() / ".moru/bin/moru-hook"
        executable = verified_launcher if verified_launcher is not None else entry.with_name("moru-hook-native")
        try:
            raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
        except (ValueError, TypeError):
            return None
        if len(raw) > 1024 * 1024:
            return None
        env = {**os.environ, "MORU_HOME": str(Path(__file__).resolve().parents[2])}
        if protocol == "--decision-cache-probe":
            env.pop("OPENROUTER_API_KEY", None)
        try:
            done = subprocess.run([str(executable), str(entry), protocol, operation],
                                  input=raw, stdout=stdout, stderr=subprocess.PIPE, timeout=10,
                                  env=env)
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
