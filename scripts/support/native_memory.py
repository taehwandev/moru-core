"""Optional native memory reads/ranking; original owner keeps write authority.

Owner: NativeMemory. Allowed: stdlib/NativeProbe. Forbidden: ranking, store
reads/writes, providers. Callers/tests: project-memory recall, native oracles.
"""
from datetime import date
from pathlib import Path
import unicodedata

from support.native_probe_transport import NativeProbe


class NativeMemory:
    @staticmethod
    def _source_profile():
        # Git originally inherits fd 0. Never consume or replace live input;
        # admit only a proven EOF-equivalent descriptor and actual UTF-8 locale.
        import os
        if os.name != "posix":
            return False
        import array
        import fcntl
        import locale
        import select
        import stat
        import termios
        try:
            if locale.getpreferredencoding(False).lower().replace("-", "").replace("_", "") != "utf8":
                return False
            actual, null = os.fstat(0), os.stat(os.devnull)
            if stat.S_ISCHR(actual.st_mode) and actual.st_rdev == null.st_rdev:
                return True
            if not stat.S_ISFIFO(actual.st_mode) or actual.st_nlink != 0:
                return False
            available = array.array("i", [0])
            fcntl.ioctl(0, termios.FIONREAD, available, True)
            poll = select.poll()
            poll.register(0, select.POLLIN | select.POLLHUP)
            return available[0] == 0 and any(flags & select.POLLHUP for _, flags in poll.poll(0))
        except (OSError, ValueError, AttributeError):
            return False

    @staticmethod
    def blob(root, path, tracked):
        if type(root) is not type(Path()) or type(path) is not str or type(tracked) is not bool:
            return None
        if not NativeMemory._source_profile():
            return None
        try:
            result = NativeProbe.request("--memory-probe", "blob",
                {"unicode":unicodedata.unidata_version,"root":str(root),"path":path,"tracked":tracked,
                 "stdin_eof":True,"encoding":"utf-8"})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is dict and set(result) == {"decode_error"}:
            raw = result["decode_error"]
            if type(raw) is list and all(type(b) is int and 0 <= b <= 255 for b in raw):
                bytes(raw).decode("utf-8")  # Deliberately outside the availability catch.
            return None
        if type(result) is not dict or set(result) != {"blob"} or type(result["blob"]) is not str:
            return None
        blob = result["blob"]
        if blob and (len(blob) not in (40,64) or any(c not in "0123456789abcdef" for c in blob)):
            return None
        return result

    @staticmethod
    def files(operation, path):
        if operation not in {"record", "scan"} or type(path) is not type(Path()):
            return None
        try:
            result = NativeProbe.request("--memory-probe", operation,
                {"unicode":unicodedata.unidata_version,"path":str(path)})
        except (OSError, ValueError, RuntimeError):
            return None
        if type(result) is not dict:
            return None
        if operation == "record":
            return result if set(result) == {"record"} and (result["record"] is None or type(result["record"]) is dict) else None
        if (set(result) != {"records","unreadable"} or type(result["records"]) is not list
                or any(type(item) is not dict for item in result["records"])
                or type(result["unreadable"]) is not int or result["unreadable"] < 0):
            return None
        return result

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
