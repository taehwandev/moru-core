"""Optional native memory ranking; the original owner keeps all store authority.

Owner: NativeMemory. Allowed: stdlib/NativeProbe. Forbidden: ranking, store
reads/writes, providers. Callers/tests: project-memory recall, native oracles.
"""
from datetime import date
from pathlib import Path
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemory:
    @staticmethod
    def recall(scope, today, records, request, summary, paths):
        if (type(scope) is not str or type(today) is not date or type(records) is not list
                or type(request) is not str or type(summary) is not str
                or type(paths) not in (tuple, list)
                or any(type(path) not in (str, type(Path())) for path in paths)
                or any(type(record) is not dict for record in records)):
            return None
        # Reject customized/malformed values before serialization can execute them.
        if not NativeMemory._ordinary(records):
            return None
        payload = {"unicode":unicodedata.unidata_version, "scope":scope,
                   "today":today.isoformat(), "records":records,
                   "context":" ".join((request,summary,*map(str,paths)))}
        try:
            result = NativeProbe.request("--memory-probe", "recall", payload)
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) != {"indices"}:
            return None
        indices = result["indices"]
        if (type(indices) is not list or any(type(i) is not int or not 0 <= i < len(records) for i in indices)
                or len(indices) != len(set(indices))):
            return None
        return [records[i] for i in indices]

    @staticmethod
    def _ordinary(value, depth=0):
        if depth > 80:
            return False
        if value is None or type(value) in (str,bool,int,float):
            return True
        if type(value) is list:
            return all(NativeMemory._ordinary(item, depth+1) for item in value)
        if type(value) is dict:
            return all(type(key) is str and NativeMemory._ordinary(item, depth+1) for key,item in value.items())
        return False
