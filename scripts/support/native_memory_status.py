"""Native source-status transport; preserve caller-owned cache and exceptions.

Owner: NativeMemoryStatus. Allowed: stdlib/NativeMemory/NativeProbe.
Forbidden: hashing/ranking/store writes/providers. Caller: project-memory status.
Verification: test_native_memory_status and transported memory probes.
"""
from pathlib import Path
import unicodedata

from support.native_memory import NativeMemory
from support.native_probe_transport import NativeProbe


class NativeMemoryStatus:
    @staticmethod
    def evaluate(project, files, blobs):
        if (type(project) is not type(Path()) or type(files) is not list or not 1 <= len(files) <= 4
                or type(blobs) is not dict
                or any(type(key) is not str for key in blobs)
                or any(type(f) is not dict or set(f) != {"path", "blob"}
                       or type(f["path"]) is not str or type(f["blob"]) is not str for f in files)):
            return None
        paths = {f["path"] for f in files}
        cached = {path: blobs[path] for path in paths if path in blobs}
        # A cache-only record needs no process or filesystem admission. Keep
        # the existing in-process loop instead of adding a native round trip.
        if len(cached) == len(paths):
            return None
        if any(type(value) is not str for value in cached.values()):
            return None
        try:
            if not NativeMemory._source_profile():
                return None
            root = project.resolve()
            # A symlinked/relative project can resolve differently between
            # source-loop iterations. Preserve that admission in the caller.
            if root != project:
                return None
            result = NativeProbe.request("--memory-probe", "source-status",
                {"unicode":unicodedata.unidata_version,"root":str(root),
                 "files":files,"blobs":cached,"stdin_eof":True,"encoding":"utf-8"})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict or set(result) not in ({"blobs", "result"}, {"blobs", "decode_error"}):
            return None
        added = result["blobs"]
        pending = list(dict.fromkeys(f["path"] for f in files if f["path"] not in cached))
        if (type(added) is not dict or not set(added) <= paths - set(cached)
                or list(added) != pending[:len(added)]
                or any(type(v) is not str or (v and (len(v) not in (40,64)
                       or any(c not in "0123456789abcdef" for c in v))) for v in added.values())):
            return None
        if "decode_error" in result:
            raw = result["decode_error"]
            if (len(added) == len(pending) or type(raw) is not list
                    or not all(type(b) is int and 0 <= b <= 255 for b in raw)):
                return None
            try:
                bytes(raw).decode("utf-8")
            except UnicodeDecodeError as error:
                blobs.update(added)
                raise error
            return None
        status = result["result"]
        if status is not None and (len(added) != len(pending)
                                  or not NativeMemoryStatus._valid(status, [f["path"] for f in files])):
            return None
        blobs.update(added)
        return status

    @staticmethod
    def _valid(status, paths):
        if type(status) is not dict:
            return False
        state = status.get("source_status")
        if state == "unchanged":
            return set(status) == {"source_status"}
        if not (state in ("changed", "unavailable")
                and set(status) == {"source_status", "unverified_sources", "warning"}
                and status["warning"] == f"Source evidence {state} — verify before use"
                and type(status["unverified_sources"]) is list
                and 1 <= len(status["unverified_sources"]) <= len(paths)):
            return False
        ordered = iter(paths)
        return all(type(path) is str and any(path == candidate for candidate in ordered)
                   for path in status["unverified_sources"])
