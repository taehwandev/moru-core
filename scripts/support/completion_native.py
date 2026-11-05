"""Bounded transport to native completion policy; contains no decision rules.

Owner: private native protocol. Allowed: stdlib. Forbidden: execution of checks,
state writes, installation, fallback algorithms, caches and model calls.
"""
from __future__ import annotations

from support.native_probe_transport import NativeProbe


def completion_available() -> bool:
    return NativeProbe.available()


def completion_native(operation: str, payload: dict) -> dict | None:
    return NativeProbe.request("--completion-probe", operation, payload)
