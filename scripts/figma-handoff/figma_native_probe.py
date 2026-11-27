"""Optional source- and interpreter-bound bridge for the offline Figma validator.

Owner: local Figma validation probes. Allowed: stdlib and the adjacent checkout's
native transport. Forbidden: writes, network and Figma provider operations.
"""
from __future__ import annotations

import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys


def _summary_text(summary):
    # ensure_ascii makes each output character exactly one transport byte.
    limit = 1024 * 1024
    output = io.StringIO()
    visits_left = 32000

    def append(text):
        if output.tell() + len(text) > limit:
            return False
        output.write(text)
        return True

    def write_string(value):
        # Even an unescaped string needs two quotes. Encode in fixed chunks so
        # an escape-heavy input cannot allocate its full expansion before rejection.
        if len(value) + 2 > limit - output.tell():
            return False
        output.write('"')
        for start in range(0, len(value), 4096):
            escaped = json.dumps(value[start:start + 4096], ensure_ascii=True)
            if not append(escaped[1:-1]):
                return False
        return append('"')

    def write(value, depth):
        nonlocal visits_left
        visits_left -= 1
        if depth > 48 or visits_left < 0:
            return False
        kind = type(value)
        if kind is str:
            return write_string(value)
        if value is None or kind is bool or kind is float or kind is int:
            if kind is float and not math.isfinite(value):
                return False
            if kind is int and value.bit_length() > 1024:
                return False
            return append(json.dumps(value, allow_nan=False))
        if kind is not list and kind is not dict:
            return False
        if len(value) > visits_left or not append("[" if kind is list else "{"):
            return False
        entries = value.items() if kind is dict else value
        for index, item in enumerate(entries):
            if index and not append(","):
                return False
            if kind is dict:
                key, item = item
                if type(key) is not str or not write(key, depth + 1) or not append(":"):
                    return False
            if not write(item, depth + 1):
                return False
        return append("]" if kind is list else "}")

    try:
        return output.getvalue() if write(summary, 0) else None
    except (ValueError, RuntimeError, TypeError, KeyError):
        return None


def request(operation, value, source_file):
    if os.environ.get("MORU_LAUNCHER_BACKEND") == "python":
        return None
    root = Path(source_file).resolve().parent.parent.parent
    transport = root / "scripts/support/native_probe_transport.py"
    if not transport.is_file() or transport.resolve() != transport:
        return None
    spec = importlib.util.spec_from_file_location("_moru_figma_probe_transport", transport)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError:
        return None
    if not module.NativeProbe.available():
        return None
    if operation in ("figma-summary-schema", "figma-smoke-analysis", "figma-smoke-frames", "figma-smoke-verdict",
                     "figma-smoke-result", "figma-smoke-file-result", "figma-target", "figma-plan", "figma-bundle-manifest"):
        text = _summary_text(value)
        if text is None:
            return None
        payload = {"text": text}
    elif operation == "figma-validate-cli":
        payload = {"path": value}
    else:
        return None
    digits = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else -1
    payload.update(source_root=str(root),
                   python_profile=f"{sys.implementation.name}:{sys.hexversion}:{sys.getrecursionlimit()}:{digits}")
    return module.NativeProbe.request("--completion-probe", operation, payload)
