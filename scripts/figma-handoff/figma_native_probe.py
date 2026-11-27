"""Optional source- and interpreter-bound bridge for the offline Figma validator.

Owner: local Figma validation probes. Allowed: stdlib and the adjacent checkout's
native transport. Forbidden: writes, network and Figma provider operations.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import sys


def _summary_text(summary):
    # Bound both traversal (including cycles and shared subtrees) and temporary
    # encoding space before json.dumps. Unsupported Python objects stay local.
    visits_left = 32000
    chars_left = 512 * 1024

    def admitted(value, depth):
        nonlocal visits_left, chars_left
        visits_left -= 1
        if depth > 48 or visits_left < 0 or chars_left <= 0:
            return False
        kind = type(value)
        if kind is str:
            chars_left -= 12 * len(value) + 3  # worst case: a UTF-16 escape pair
        elif value is None or kind is bool or kind is float:
            if kind is float and not math.isfinite(value):
                return False
            chars_left -= 32
        elif kind is int:
            bits = value.bit_length()
            if bits > 1024:
                return False
            chars_left -= bits + 3
        elif kind is list or kind is dict:
            chars_left -= 2 + len(value)
            if chars_left < 0 or len(value) > visits_left:
                return False
            if kind is list:
                return all(admitted(item, depth + 1) for item in value)
            return all(type(key) is str and admitted(key, depth + 1) and admitted(item, depth + 1)
                       for key, item in value.items())
        else:
            return False
        return chars_left >= 0

    try:
        if admitted(summary, 0):
            return json.dumps(summary, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (ValueError, RuntimeError, TypeError):
        pass
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
    if operation in ("figma-summary-schema", "figma-smoke-analysis"):
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
