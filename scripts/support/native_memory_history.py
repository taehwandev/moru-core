"""Typed history-index transport; preserve original record objects and values.

Owner: NativeMemoryHistory. Allowed: stdlib/NativeProbe. Forbidden: traversal,
store reads/writes/providers. Caller: project-memory history. Tests: native history.
"""
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemoryHistory:
    @staticmethod
    def select(record_id, records):
        if type(record_id) is not str or type(records) is not list or not records:
            return None
        links = []
        for record in records:
            if (type(record) is not dict or any(type(key) is not str for key in record)
                    or type(record.get("id")) is not str
                    or any(record.get(key) is not None and type(record[key]) is not str
                           for key in ("replaces", "replaced_by"))):
                return None
            links.append({"id":record["id"], "replaces":record.get("replaces"),
                          "replaced_by":record.get("replaced_by")})
        try:
            result = NativeProbe.request("--memory-probe", "history",
                {"unicode":unicodedata.unidata_version,"record_id":record_id,"records":links})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != {"indices"}:
            return None
        indices = result["indices"]
        if (type(indices) is not list or not 1 <= len(indices) <= 20
                or any(type(i) is not int or not 0 <= i < len(records) for i in indices)
                or len(indices) != len(set(indices))):
            return None
        if len({records[i]["id"] for i in indices}) != len(indices):
            return None
        return [records[i] for i in indices]
