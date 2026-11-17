"""Owner: NativeMemoryContext, profile/transport and final JSON line encoding.
Allowed: stdlib, NativeMemory profile guard, NativeProbe. Forbidden: ranking,
projection/selection algorithms, store IO/writes/providers/authority.
Caller/tests: recall_lines and test_native_memory_context; verify real probes.
"""
from datetime import date
import json
from pathlib import Path
import re
import unicodedata

from support.native_memory import NativeMemory
from support.native_probe_transport import NativeProbe

_REQUIRED = ("id", "body", "source", "review_on")
_OPTIONAL = ("applies_when", "not_when")


class NativeMemoryContext:
    @staticmethod
    def render(scope, today, records, request, summary, paths, limits):
        if (type(scope) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{1,40}", scope) is None
                or type(today) is not date or type(records) is not list
                or type(request) is not str or type(summary) is not str
                or type(paths) not in (tuple, list)
                or any(type(p) not in (str, type(Path())) for p in paths)
                or type(limits) is not dict or set(limits) != {"items", "chars", "previous"}
                or any(type(n) is not int or n < 0 for n in limits.values())
                or limits["items"] > 256 or limits["chars"] > 1_000_000
                or not 1 <= limits["previous"] <= 1_000_000):
            return None, False
        for row in records:
            if (type(row) is not dict
                    or any(type(row.get(k)) is not str for k in (*_REQUIRED, "status", "scope"))
                    or any(k in row and type(row[k]) is not str for k in _OPTIONAL)
                    or ("source_files" in row and (type(row["source_files"]) is not list or row["source_files"]))):
                return None, False
        if not NativeMemory._ordinary(records):
            return None, False
        if not records:
            return [], False
        try:
            if not NativeProbe.available():
                return None, False
            result = NativeProbe.request("--memory-probe", "recall-context", {
                "unicode": unicodedata.unidata_version, "scope": scope, "today": today.isoformat(),
                "records": records, "context": " ".join((request, summary, *map(str, paths))),
                "limits": limits})
        except (OSError, ValueError, RuntimeError):
            return None, True
        if type(result) is not dict or set(result) != {"items"} or type(result["items"]) is not list:
            return None, True
        items = result["items"]
        if len(items) > limits["items"]:
            return None, True
        ids = {row["id"] for row in records}
        lines, size = [], 0
        for item in items:
            if (type(item) is not dict or any(k not in item for k in _REQUIRED)
                    or list(item) != [k for k in (*_REQUIRED, *_OPTIONAL, "previously") if k in item]
                    or any(type(v) is not str for v in item.values()) or item["id"] not in ids
                    or ("previously" in item and len(item["previously"]) > limits["previous"])):
                return None, True
            payload = json.dumps(item, ensure_ascii=False)
            size += len(payload)
            if size > limits["chars"]:
                return None, True
            lines.append("- " + payload)
        return lines, True
