"""Source-bound report aggregation, with pure Python rollback on a declined call.

Owner: NativeOverheadReport. Allowed imports: stdlib, NativeProbe. Forbidden:
file parsing, provider calls, state or source writes. Callers/tests:
moru_overhead_report; native report parity, refusal and transported checks.
"""
from __future__ import annotations

import collections
import math

from support.native_probe_transport import NativeProbe


def _json_tree(value, depth=0):
    if depth > 120:
        return False
    if type(value) in (str, int, float, bool, type(None)):
        return True
    if type(value) is list:
        return all(_json_tree(v, depth+1) for v in value)
    if type(value) is dict:
        return all(type(k) is str and _json_tree(v, depth+1) for k, v in value.items())
    return False


def _format_report(report, style):
    if style not in ("json", "markdown") or not NativeProbe.available() or not _json_tree(report):
        return None
    value = NativeProbe.request("--overhead-probe", "format", {"report": report, "format": style})
    return (value["text"] if type(value) is dict and set(value) == {"text"}
            and type(value["text"]) is str else None)


class NativeOverheadReport:
    render = staticmethod(_format_report)
    NUMERIC = (
        "assistant_turns", "user_prompts", "tool_calls", "lifecycle_total", "policy_notes",
        "hook_denials", "moru_hook_denials", "stop_hook_blocks", "guidance_reads", "guidance_bash_reads",
        "tok_total", "tok_output", "tok_cache_read", "tok_cache_create",
        "moru_injected_tokens_est", "moru_injected_events",
    )

    @staticmethod
    def _rows(sessions, *, core=False):
        if type(sessions) is not list:
            return None
        rows = []
        for session in sessions:
            if type(session) is not dict:
                return None
            row = {}
            for key in (*NativeOverheadReport.NUMERIC, "tok_input"):
                value = session.get(key)
                if type(value) is not int:
                    return None
                row[key] = value
            for key in ("tools", "lifecycle_calls"):
                value = session.get(key)
                if not NativeOverheadReport._counter(value):
                    return None
                row[key] = dict(value)
            if core:
                if type(session.get("moru_core")) is not bool:
                    return None
                row["moru_core"] = session["moru_core"]
            rows.append(row)
        return rows

    @staticmethod
    def _counter(value):
        return (type(value) in (dict, collections.Counter)
                and all(type(k) is str and type(v) is int for k, v in value.items()))

    @staticmethod
    def _summary(value):
        if type(value) is not dict or type(value.get("n")) is not int or value["n"] < 0:
            return False
        if not value["n"]:
            return set(value) == {"n"}
        return (set(value) == {"n", "median", "p90", "mean", "sum"}
                and all((type(value[k]) is int and abs(value[k]) <= 1 << 53)
                        or (type(value[k]) is float and math.isfinite(value[k]))
                        for k in ("median", "p90", "mean", "sum")))

    @staticmethod
    def _aggregate(value, count):
        names = {"sessions", "tool_calls_by_name_total", "lifecycle_calls_by_subcommand_total",
                 "sessions_with_lifecycle_calls", *NativeOverheadReport.NUMERIC}
        shares = {"lifecycle_share_of_tool_calls_pct", "guidance_read_share_of_reads_pct",
                  "injected_tokens_vs_new_input_pct"} if count else set()
        return (type(value) is dict and set(value) == names | shares
                and type(value["sessions"]) is int and value["sessions"] == count
                and type(value["sessions_with_lifecycle_calls"]) is int
                and 0 <= value["sessions_with_lifecycle_calls"] <= count
                and all(NativeOverheadReport._summary(value[k]) and value[k]["n"] == count
                        for k in NativeOverheadReport.NUMERIC)
                and all(NativeOverheadReport._counter(value[k]) for k in
                        ("tool_calls_by_name_total", "lifecycle_calls_by_subcommand_total"))
                and all(type(value[k]) is float and math.isfinite(value[k]) for k in shares))

    @staticmethod
    def aggregate(sessions):
        rows = NativeOverheadReport._rows(sessions)
        if rows is None:
            return None
        result = NativeProbe.request("--overhead-probe", "aggregate", {"sessions": rows})
        return result if NativeOverheadReport._aggregate(result, len(rows)) else None

    @staticmethod
    def analyze(sessions, hooks):
        rows = NativeOverheadReport._rows(sessions, core=True)
        if (rows is None or type(hooks) not in (dict, collections.defaultdict)
                or any(type(k) is not str or type(v) is not list
                       or any(type(x) not in (int, float, type(None)) for x in v)
                       for k, v in hooks.items())):
            return None
        result = NativeProbe.request("--overhead-probe", "analyze", {"sessions": rows, "hook_latency": hooks})
        if type(result) is not dict or set(result) != {
                "all", "moru_core", "other_projects", "moru_hook_latency_ms_from_transcripts"}:
            return None
        core = sum(row["moru_core"] for row in rows)
        for key, count in (("all", len(rows)), ("moru_core", core), ("other_projects", len(rows)-core)):
            if not NativeOverheadReport._aggregate(result[key], count):
                return None
        latency = result["moru_hook_latency_ms_from_transcripts"]
        if (type(latency) is not dict or set(latency) != set(hooks)
                or any(not NativeOverheadReport._summary(v) for v in latency.values())):
            return None
        return result

    @staticmethod
    def timings(path):
        if type(path) is not str:
            return None
        result = NativeProbe.request("--overhead-probe", "timings", {"path": path})
        if (type(result) is not dict or set(result) != {"records", "per_hook_ms", "status"}
                or type(result["records"]) is not int or result["records"] < 0
                or type(result["per_hook_ms"]) is not dict
                or any(type(k) is not str or not NativeOverheadReport._summary(v)
                       for k, v in result["per_hook_ms"].items())
                or not NativeOverheadReport._counter(result["status"])
                or sum(result["status"].values()) != result["records"]
                or sum(v["n"] for v in result["per_hook_ms"].values()) != result["records"]):
            return None
        return result
