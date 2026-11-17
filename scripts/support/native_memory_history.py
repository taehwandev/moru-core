"""Typed history-index transport; preserve original record objects and values.

Owner: NativeMemoryHistory. Allowed: stdlib/NativeProbe. Forbidden: traversal/field decisions,
store reads/writes/providers. Caller: project-memory history. Tests: native history.
"""
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemoryHistory:
    @staticmethod
    def select(record_id, records, *, fields=None):
        if type(record_id) is not str or type(records) is not list or not records:
            return None
        if fields is not None and (type(fields) is not tuple
                or any(type(key) is not str for key in fields) or len(set(fields)) != len(fields)):
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
            if fields is not None:
                links[-1]["keys"] = list(record)
        packet = {"unicode":unicodedata.unidata_version,"record_id":record_id,"records":links}
        if fields is not None:
            packet["fields"] = list(fields)
        try:
            result = NativeProbe.request("--memory-probe", "history", packet)
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != ({"indices"} if fields is None else {"indices","fields"}):
            return None
        indices = result["indices"]
        if (type(indices) is not list or not 1 <= len(indices) <= 20
                or any(type(i) is not int or not 0 <= i < len(records) for i in indices)
                or len(indices) != len(set(indices))):
            return None
        if len({records[i]["id"] for i in indices}) != len(indices):
            return None
        if fields is not None:
            return NativeMemoryHistory._project(result["fields"], [records[i] for i in indices], fields)
        return [records[i] for i in indices]

    @staticmethod
    def _project(projection, records, fields):
        if type(projection) is not list or len(projection) != len(records):
            return None
        result = []
        for row, positions in zip(records, projection):
            if (type(positions) is not list
                    or any(type(i) is not int or not 0 <= i < len(fields) or fields[i] not in row for i in positions)
                    or any(a >= b for a,b in zip(positions,positions[1:]))):
                return None
            result.append({fields[i]:row[fields[i]] for i in positions})
        return result


_SELECT_BINDING = (NativeMemoryHistory.select, NativeMemoryHistory.select.__code__,
    NativeMemoryHistory.select.__defaults__, dict(NativeMemoryHistory.select.__kwdefaults__ or {}))
