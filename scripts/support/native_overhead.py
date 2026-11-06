"""Atomic adapter for the private native transcript session tally.

Owner: NativeOverhead. Allowed imports: stdlib and NativeProbe. Forbidden:
transcript parsing, provider calls, state writes, installers. Callers/tests:
claude_transcript_overhead; native overhead parity and refusal tests.
"""
from __future__ import annotations

import collections
import datetime as dt

from support.native_probe_transport import NativeProbe


class NativeOverhead:
    @staticmethod
    def measure(path, roots, shared, window):
        if (type(path) is not str or type(roots) is not list
                or any(type(root) is not str for root in roots)
                or type(shared) is not dict or set(shared) != {"notes", "denials", "hook_latency"}
                or any(type(shared[key]) is not collections.Counter for key in ("notes", "denials"))
                or type(shared["hook_latency"]) is not collections.defaultdict
                or shared["hook_latency"].default_factory is not list
                or any(type(v) is not list for v in shared["hook_latency"].values())
                or any(type(k) is not str or type(v) is not int
                       for name in ("notes", "denials") for k, v in shared[name].items())
                or type(window) is not tuple or len(window) != 2):
            return None
        stamps = []
        for value in window:
            if value is not None and (type(value) is not dt.datetime
                    or (value.tzinfo is not None and type(value.tzinfo) is not dt.timezone)):
                return None
            stamps.append(value.isoformat() if value is not None else None)
        value = NativeProbe.request("--overhead-probe", "session",
                                    {"path": path, "roots": roots, "window": stamps})
        validated = NativeOverhead._validate(value)
        if validated is None:
            return None
        row, delta = validated
        # Validation precedes every mutation. Declined results are replayed by
        # the caller against the original counters, never a partly merged state.
        for name in ("notes", "denials"):
            shared[name].update(delta[name])
        for key, values in delta["hook_latency"].items():
            shared["hook_latency"][key].extend(values)
        return row

    @staticmethod
    def _validate(value):
        from claude_transcript_overhead import COUNTERS
        if type(value) is not dict or set(value) != {"row", "shared"}:
            return None
        row, delta = value["row"], value["shared"]
        keys = set(COUNTERS) | {"file", "project_dir", "cwd", "first_ts", "last_ts", "tools",
                               "lifecycle_calls", "tok_total", "moru_injected_tokens_est", "moru_core"}
        if type(row) is not dict or set(row) != keys or type(delta) is not dict:
            return None
        if set(delta) != {"notes", "denials", "hook_latency"}:
            return None
        if (any(type(row[k]) is not int for k in (*COUNTERS, "tok_total", "moru_injected_tokens_est"))
                or any(type(row[k]) is not str for k in ("file", "project_dir"))
                or (row["cwd"] is not None and type(row["cwd"]) is not str)
                or type(row["moru_core"]) is not bool):
            return None
        for mapping in (row["tools"], row["lifecycle_calls"], delta["notes"], delta["denials"]):
            if type(mapping) is not dict or any(type(k) is not str or type(v) is not int for k, v in mapping.items()):
                return None
        if type(delta["hook_latency"]) is not dict or any(
                type(k) is not str or type(v) is not list or any(type(n) not in (int, float) for n in v)
                for k, v in delta["hook_latency"].items()):
            return None
        row = row.copy()
        for key in ("first_ts", "last_ts"):
            if row[key] is not None:
                if type(row[key]) is not str:
                    return None
                try:
                    row[key] = dt.datetime.fromisoformat(row[key])
                except ValueError:
                    return None
        for key in ("tools", "lifecycle_calls"):
            row[key] = collections.Counter(row[key])
        return row, delta
